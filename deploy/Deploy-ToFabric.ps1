<#
.SYNOPSIS
    One-command deployment of the MINDX-Mart pipeline into Microsoft Fabric.

.DESCRIPTION
    Signs you in with the OAuth 2.0 device-code flow (no az/fab install required), then:
      1. resolves or creates the target workspace (assigns a capacity if asked),
      2. creates the Lakehouse,
      3. uploads config/pipeline_config.json + the two source CSVs into OneLake (Files/),
      4. imports the 4 notebooks, pre-attached to the Lakehouse so they run immediately.

    The script is idempotent: existing workspace/lakehouse/notebooks are reused/updated.

.PARAMETER WorkspaceName
    Target Fabric workspace name. Reused if it exists.

.PARAMETER LakehouseName
    Lakehouse name to create/use inside the workspace.

.PARAMETER CapacityName
    (Optional) Capacity to assign when creating a new workspace. Needed only if the workspace
    does not already exist. Run with -ListCapacities to see available ones.

.PARAMETER CreateWorkspace
    Create the workspace if it does not exist (requires a capacity).

.PARAMETER SkipData
    Skip uploading the CSVs (e.g. upload them manually in the UI).

.PARAMETER ListCapacities
    Just sign in and list the capacities you can use, then exit.

.PARAMETER AccessToken
    (Optional) Paste a Fabric API bearer token to bypass device-code login.

.PARAMETER OneLakeToken
    (Optional) Paste a storage-scope (https://storage.azure.com) bearer token for OneLake uploads.

.EXAMPLE
    .\Deploy-ToFabric.ps1 -ListCapacities

.EXAMPLE
    .\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart" -CreateWorkspace -CapacityName "Trial-..."

.EXAMPLE
    .\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart"   # workspace already exists
#>
[CmdletBinding()]
param(
    [string]$WorkspaceName = "MINDX-Mart",
    [string]$LakehouseName = "LH_MINDX_Mart",
    [string]$CapacityName,
    [switch]$CreateWorkspace,
    [switch]$SkipData,
    [switch]$ListCapacities,
    [string]$AccessToken,
    [string]$OneLakeToken,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Azure CLI public client id — supports the device-code flow in most tenants.
$CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
$AUTHORITY = "https://login.microsoftonline.com/organizations/oauth2/v2.0"
$FABRIC_API = "https://api.fabric.microsoft.com/v1"

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "    [!]  $m" -ForegroundColor Yellow }

# --------------------------------------------------------------------------- #
# Auth — device code flow
# --------------------------------------------------------------------------- #
function Get-DeviceCodeToken {
    param([string]$Scope)
    $dc = Invoke-RestMethod -Method Post -Uri "$AUTHORITY/devicecode" `
            -Body @{ client_id = $CLIENT_ID; scope = $Scope }
    Write-Host "`n$($dc.message)`n" -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds([int]$dc.expires_in)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds ([int]$dc.interval)
        try {
            return Invoke-RestMethod -Method Post -Uri "$AUTHORITY/token" -Body @{
                grant_type  = "urn:ietf:params:oauth:grant-type:device_code"
                client_id   = $CLIENT_ID
                device_code = $dc.device_code
            }
        } catch {
            $err = ($_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue).error
            if ($err -eq "authorization_pending" -or $err -eq "slow_down") { continue }
            throw
        }
    }
    throw "Device-code login timed out."
}

function Get-RefreshedToken {
    param([string]$RefreshToken, [string]$Scope)
    Invoke-RestMethod -Method Post -Uri "$AUTHORITY/token" -Body @{
        grant_type    = "refresh_token"
        client_id     = $CLIENT_ID
        refresh_token = $RefreshToken
        scope         = $Scope
    }
}

# Acquire tokens (Fabric control-plane + OneLake data-plane)
if ($AccessToken) {
    $script:FabricToken = $AccessToken
    $script:OneLakeTok  = $OneLakeToken
    Write-Ok "Using pasted access token(s)."
} else {
    Write-Step "Sign in to Microsoft Fabric (device code)"
    $tok = Get-DeviceCodeToken -Scope "https://api.fabric.microsoft.com/.default offline_access"
    $script:FabricToken = $tok.access_token
    Write-Ok "Signed in."
    if (-not $SkipData) {
        try {
            $st = Get-RefreshedToken -RefreshToken $tok.refresh_token -Scope "https://storage.azure.com/.default offline_access"
            $script:OneLakeTok = $st.access_token
            Write-Ok "OneLake (storage) token acquired."
        } catch {
            Write-Warn2 "Could not get a storage token automatically; data upload may need -OneLakeToken. ($_)"
        }
    }
}

function Invoke-Fabric {
    param(
        [string]$Method, [string]$Path, $Body,
        [string]$BaseUrl = $FABRIC_API
    )
    $headers = @{ Authorization = "Bearer $script:FabricToken" }
    $uri = if ($Path -match '^https?://') { $Path } else { "$BaseUrl$Path" }
    $req = @{ Method = $Method; Uri = $uri; Headers = $headers; UseBasicParsing = $true }
    if ($null -ne $Body) {
        $req.Body = ($Body | ConvertTo-Json -Depth 100)
        $req.ContentType = "application/json"
    }
    $resp = Invoke-WebRequest @req
    # Long-running operation -> poll until complete
    if ($resp.StatusCode -eq 202 -and $resp.Headers["Location"]) {
        $op = $resp.Headers["Location"]
        do {
            Start-Sleep -Seconds ([int]([string]$resp.Headers["Retry-After"]) + 2)
            $resp = Invoke-WebRequest -Method Get -Uri $op -Headers $headers -UseBasicParsing
            $state = ($resp.Content | ConvertFrom-Json).status
        } while ($state -in @("Running", "NotStarted", "Undefined"))
        if ($state -eq "Failed") { throw "Operation failed: $($resp.Content)" }
        # fetch result if available
        if ($resp.Headers["Location"]) {
            $resp = Invoke-WebRequest -Method Get -Uri $resp.Headers["Location"] -Headers $headers -UseBasicParsing
        }
    }
    if ($resp.Content) { return ($resp.Content | ConvertFrom-Json) }
    return $null
}

# --------------------------------------------------------------------------- #
# Capacities
# --------------------------------------------------------------------------- #
Write-Step "Listing capacities"
$caps = (Invoke-Fabric GET "/capacities").value
if (-not $caps -or $caps.Count -eq 0) {
    Write-Warn2 "No capacities found. Start a free Fabric Trial (see deploy/README.md, step 1), then re-run."
} else {
    $caps | ForEach-Object { Write-Host ("    - {0}  (id={1}, state={2})" -f $_.displayName, $_.id, $_.state) }
}
if ($ListCapacities) { return }

# --------------------------------------------------------------------------- #
# Workspace
# --------------------------------------------------------------------------- #
Write-Step "Resolving workspace '$WorkspaceName'"
$ws = (Invoke-Fabric GET "/workspaces").value | Where-Object { $_.displayName -eq $WorkspaceName } | Select-Object -First 1
if (-not $ws) {
    if (-not $CreateWorkspace) { throw "Workspace '$WorkspaceName' not found. Re-run with -CreateWorkspace -CapacityName <name>." }
    $cap = if ($CapacityName) { $caps | Where-Object { $_.displayName -eq $CapacityName } | Select-Object -First 1 }
           else { $caps | Where-Object { $_.state -eq "Active" } | Select-Object -First 1 }
    if (-not $cap) { throw "No capacity to assign. Pass -CapacityName or start a Trial." }
    $ws = Invoke-Fabric POST "/workspaces" @{ displayName = $WorkspaceName }
    Invoke-Fabric POST "/workspaces/$($ws.id)/assignToCapacity" @{ capacityId = $cap.id } | Out-Null
    Write-Ok "Created workspace '$WorkspaceName' on capacity '$($cap.displayName)'."
} else {
    Write-Ok "Using existing workspace (id=$($ws.id))."
}
$wsId = $ws.id

# --------------------------------------------------------------------------- #
# Lakehouse
# --------------------------------------------------------------------------- #
Write-Step "Creating/Resolving Lakehouse '$LakehouseName'"
$lh = (Invoke-Fabric GET "/workspaces/$wsId/lakehouses").value | Where-Object { $_.displayName -eq $LakehouseName } | Select-Object -First 1
if (-not $lh) {
    $lh = Invoke-Fabric POST "/workspaces/$wsId/lakehouses" @{ displayName = $LakehouseName }
    Write-Ok "Created Lakehouse (id=$($lh.id))."
} else {
    Write-Ok "Using existing Lakehouse (id=$($lh.id))."
}
$lhId = $lh.id

# --------------------------------------------------------------------------- #
# Upload data to OneLake (Files/)
# --------------------------------------------------------------------------- #
function Send-OneLakeFile {
    param([string]$RelPath, [string]$LocalPath)
    if (-not $script:OneLakeTok) { throw "No OneLake token; pass -OneLakeToken or omit -SkipData." }
    $base = "https://onelake.dfs.fabric.microsoft.com/$wsId/$lhId/Files/$RelPath"
    $h = @{ Authorization = "Bearer $script:OneLakeTok"; "x-ms-version" = "2021-08-06" }
    $bytes = [IO.File]::ReadAllBytes($LocalPath)
    Invoke-WebRequest -Method Put   -Uri "$base?resource=file" -Headers $h -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Patch -Uri "$base?action=append&position=0" -Headers $h `
        -Body $bytes -ContentType "application/octet-stream" -UseBasicParsing | Out-Null
    Invoke-WebRequest -Method Patch -Uri "$base?action=flush&position=$($bytes.Length)" -Headers $h -UseBasicParsing | Out-Null
    Write-Ok "Uploaded Files/$RelPath ($($bytes.Length) bytes)"
}

if (-not $SkipData) {
    Write-Step "Uploading config + source data to OneLake"
    Send-OneLakeFile "config/pipeline_config.json"        (Join-Path $ProjectRoot "config\pipeline_config.json")
    Send-OneLakeFile "raw/mindx_raw_sales_data.csv"       (Join-Path $ProjectRoot "Data\mindx_raw_sales_data.csv")
    Send-OneLakeFile "raw/exchange_rate_2425.csv"         (Join-Path $ProjectRoot "Data\exchange_rate_2425.csv")
} else {
    Write-Warn2 "Skipping data upload (-SkipData). Upload config + CSVs to Files/config and Files/raw manually."
}

# --------------------------------------------------------------------------- #
# Import notebooks (pre-attached to the Lakehouse)
# --------------------------------------------------------------------------- #
function Import-Notebook {
    param([string]$LocalPath)
    $name = [IO.Path]::GetFileNameWithoutExtension($LocalPath)
    $nb = Get-Content $LocalPath -Raw | ConvertFrom-Json
    # Inject Fabric default-lakehouse attachment so %run + spark.table work out of the box
    if (-not $nb.metadata) { $nb | Add-Member -NotePropertyName metadata -NotePropertyValue ([pscustomobject]@{}) -Force }
    $dep = [pscustomobject]@{ lakehouse = [pscustomobject]@{
        default_lakehouse              = $lhId
        default_lakehouse_name         = $LakehouseName
        default_lakehouse_workspace_id = $wsId
    } }
    $nb.metadata | Add-Member -NotePropertyName dependencies -NotePropertyValue $dep -Force
    $json  = $nb | ConvertTo-Json -Depth 100
    $b64   = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $body  = @{
        displayName = $name
        definition  = @{ format = "ipynb"; parts = @(@{ path = "notebook-content.ipynb"; payload = $b64; payloadType = "InlineBase64" }) }
    }
    $existing = (Invoke-Fabric GET "/workspaces/$wsId/notebooks").value | Where-Object { $_.displayName -eq $name } | Select-Object -First 1
    if ($existing) {
        Invoke-Fabric POST "/workspaces/$wsId/notebooks/$($existing.id)/updateDefinition" @{ definition = $body.definition } | Out-Null
        Write-Ok "Updated notebook '$name'"
    } else {
        Invoke-Fabric POST "/workspaces/$wsId/notebooks" $body | Out-Null
        Write-Ok "Imported notebook '$name'"
    }
}

Write-Step "Importing notebooks"
Get-ChildItem (Join-Path $ProjectRoot "notebooks") -Filter *.ipynb | Sort-Object Name | ForEach-Object {
    Import-Notebook $_.FullName
}

# --------------------------------------------------------------------------- #
# Done
# --------------------------------------------------------------------------- #
Write-Step "Deployment complete"
Write-Host @"
    Workspace : $WorkspaceName  (id=$wsId)
    Lakehouse : $LakehouseName  (id=$lhId)

    Next steps in https://app.fabric.microsoft.com :
      1. Open the workspace -> run notebook  01_bronze_ingestion
      2. Run  02_silver_cleaning   (creates silver_* Delta tables + audit_dq_results)
      3. Run  03_gold_modeling     (creates dim_*, fact_sales, gold_* marts)
      (or build PL_MINDX_Master_Orchestration from pipeline/ to chain them.)

    Audit:  SELECT * FROM audit_pipeline_run_log;   SELECT * FROM audit_dq_results;
"@ -ForegroundColor Green
