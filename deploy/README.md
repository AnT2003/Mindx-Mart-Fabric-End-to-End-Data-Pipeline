# Deploy to Microsoft Fabric — automated

`Deploy-ToFabric.ps1` builds the whole project into your Fabric tenant in one authenticated command:
it signs you in (device-code, no installs), creates the **workspace** + **Lakehouse**, uploads the
**config + source CSVs** to OneLake, and imports the **4 notebooks** pre-attached to the Lakehouse.

> You run it (the sign-in is yours). Nothing is sent anywhere except your own Fabric tenant.

---

## Step 1 — Get a Fabric workspace + capacity (you have none yet)

1. Go to **https://app.fabric.microsoft.com** and sign in with your work account
   (`an.thai1@mservice.com.vn`).
2. Start the **free Fabric Trial**: *Account manager (top-right) → Start trial* (gives you a Trial
   capacity). If your tenant blocks self-service trials, ask IT/admin to assign you a Fabric capacity.
3. You do **not** need to pre-create the workspace — the script can create it (Step 3).

> Prereq for the script to provision items: your account needs permission to create workspaces and a
> capacity to attach. `-ListCapacities` (below) confirms what you have.

## Step 2 — See what capacities you can use
```powershell
cd "C:\Users\an.thai1\Documents\Final Project\deploy"
.\Deploy-ToFabric.ps1 -ListCapacities
```
A browser code prompt appears — open https://microsoft.com/devicelogin, paste the code, sign in.
The script then lists your capacities (note the **displayName** of your Trial capacity).

## Step 3 — Deploy
Create the workspace and deploy everything:
```powershell
.\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart" -CreateWorkspace -CapacityName "<your-capacity-name>"
```
If the workspace already exists, just:
```powershell
.\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart"
```

When it finishes you'll have, in the `MINDX-Mart` workspace:
- Lakehouse `LH_MINDX_Mart` with `Files/config/pipeline_config.json`, `Files/raw/*.csv`
- Notebooks `00_common_utils`, `01_bronze_ingestion`, `02_silver_cleaning`, `03_gold_modeling`
  (already attached to the Lakehouse).

## Step 4 — Run the pipeline (in the Fabric UI)
Open the workspace → run in order: **01 → 02 → 03**. Then inspect:
```sql
SELECT * FROM gold_monthly_revenue_vnd_by_category ORDER BY year, month, category;
SELECT * FROM gold_promo_effectiveness_by_region   ORDER BY total_orders DESC;
SELECT * FROM audit_pipeline_run_log ORDER BY start_ts DESC;
SELECT * FROM audit_dq_results       ORDER BY logged_at DESC;
```
(Or build `PL_MINDX_Master_Orchestration` from `../pipeline/` to chain Bronze→Silver→Gold in one run.)

---

## Options
| Flag | Purpose |
|---|---|
| `-ListCapacities` | sign in and list capacities, then exit |
| `-CreateWorkspace` | create the workspace if missing (needs `-CapacityName` or an active capacity) |
| `-CapacityName "<name>"` | capacity to attach when creating the workspace |
| `-SkipData` | don't upload CSVs (upload them in the UI instead) |
| `-AccessToken "<jwt>"` / `-OneLakeToken "<jwt>"` | paste tokens to bypass device-code login |

## Troubleshooting
- **Device-code login blocked / "public client not allowed"** — your tenant restricts the Azure CLI
  client. Get tokens another way and paste them:
  - In https://app.fabric.microsoft.com, open DevTools (F12) → Console and grab a token, **or** use
    `Connect-AzAccount; (Get-AzAccessToken -ResourceUrl 'https://api.fabric.microsoft.com').Token`.
  - For OneLake: a token for resource `https://storage.azure.com`.
  - Then: `.\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart" -AccessToken "<fabric>" -OneLakeToken "<storage>"`
- **No capacities listed** — finish Step 1 (start the Trial) or ask an admin for a capacity.
- **403 creating workspace** — your account lacks workspace-create rights; ask an admin to create the
  workspace, then run without `-CreateWorkspace`.
- **OneLake upload 401/403** — the storage token is missing/expired; pass `-OneLakeToken`, or use
  `-SkipData` and upload `config/pipeline_config.json` + the CSVs via the Lakehouse UI
  (into `Files/config` and `Files/raw`).
- **`%run 00_common_utils` fails** — all four notebooks must be in the same workspace and
  `00_common_utils` must keep that exact name (the importer preserves file-stem names).

## Notes
- The script is **idempotent**: re-running reuses the workspace/lakehouse and *updates* the notebook
  definitions.
- It targets the public Fabric REST + OneLake DFS APIs and Windows PowerShell 5.1 / PowerShell 7.
- It is written against the documented APIs but **cannot be tested without a live tenant** — if your
  tenant's policies differ, the troubleshooting paths above (esp. pasted tokens) cover the common cases.
