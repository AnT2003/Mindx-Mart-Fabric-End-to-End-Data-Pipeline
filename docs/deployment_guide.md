# Deployment Guide — Running the Pipeline on Microsoft Fabric

## 0. Prerequisites
- A Microsoft Fabric workspace (Trial or capacity).
- Source files: `Data/mindx_raw_sales_data.csv`, `Data/exchange_rate_2425.csv`.

## 1. Create a Lakehouse
1. **New → Lakehouse** → `LH_MINDX_Mart`.
2. Under **Files**, create:
   - `Files/raw/` and upload the two CSVs.
   - `Files/config/` and upload **`config/pipeline_config.json`** (the notebooks read it from here).

## 2. Import the notebooks
Import all notebooks and attach the Lakehouse to each:
`00_data_quality_assessment`, `00_common_utils`, `01_bronze_ingestion`, `02_silver_cleaning`, `03_gold_modeling`.

> The layer notebooks call `%run 00_common_utils`, so `00_common_utils` must exist in the same
> workspace with the **exact** name `00_common_utils`.

## 3. Bronze — Data Factory Copy pipeline (required deliverable)
Create `PL_Bronze_Ingestion` with two **Copy data** activities (CSV → Parquet), per
`pipeline/bronze_copy_pipeline.json`:
- `Copy_Sales_CSV_to_Bronze_Parquet`: source `Files/raw/mindx_raw_sales_data.csv` (DelimitedText,
  header on, Quote `"`, Escape `"`) → sink `Files/Bronze/sales` (Parquet).
- `Copy_ExchangeRate_CSV_to_Bronze_Parquet`: source `Files/raw/exchange_rate_2425.csv` → sink
  `Files/Bronze/exchange_rate` (Parquet).

(`notebooks/01_bronze_ingestion` performs the identical landing in code and is what the master
pipeline invokes for repeatability — use whichever the brief expects to see.)

## 4. Run order (manual)
Run in sequence, attaching the Lakehouse:
0. `00_data_quality_assessment` → khảo sát dữ liệu thô, tạo bảng `dq_assessment_findings`
   (bước đo lường định hướng luật — xem `docs/data_quality_assessment.md`).
1. `PL_Bronze_Ingestion` (or `01_bronze_ingestion`) → Parquet under `Files/Bronze/`.
2. `02_silver_cleaning` → `silver_sales` ≈ 4,896, quarantine ≈ 354; `silver_exchange_rate` = 24.
   Check `audit_dq_results` for per-rule failure counts.
3. `03_gold_modeling` → `dim_*`, `fact_sales` ≈ 9,850, and the two `gold_*` marts.

## 5. Orchestrate (recommended) — one click end-to-end
Build `PL_MINDX_Master_Orchestration` per `pipeline/master_orchestration_pipeline.json`:
- a `batch_id` pipeline parameter (defaults to `utcNow()` formatted `yyyyMMddHHmmss`),
- two **Copy** activities (Bronze),
- a **Notebook** activity for `02_silver_cleaning`, then one for `03_gold_modeling`, chained on
  **Succeeded**, each passing `batch_id`,
- a failure-path Notebook activity (dependency condition **Failed**) for alerting.

After importing the notebooks, paste their notebook ids + workspace id into the activity definitions.

## 6. (Optional) SQL views
On the Lakehouse **SQL analytics endpoint** (or a Warehouse) run `sql/gold_views.sql` to expose the
marts as always-fresh views.

## 7. Power BI report
Build a semantic model on `fact_sales` + the `dim_*` tables (star schema), or read the `gold_*` marts
directly, for the revenue-by-category and promo-by-region reports.

## 8. Observability
- `audit_pipeline_run_log` — one row per layer/entity per run (status, row counts, duration).
- `audit_dq_results` — per-rule failure counts per run.
Filter both by `batch_id` to trace a single end-to-end run.

## 9. ERD
`erd/mindx_mart_star_schema.drawio` — open in https://app.diagrams.net. Mermaid copy in
`erd/erd_description.md`.

---

### Local validation (no Fabric needed)
```powershell
python -m pytest tests/ -q            # 38 unit tests on the cleaning/DQ rules
python analysis/profile_data.py       # raw anomaly profiling
python analysis/local_simulation.py   # config-driven Silver+Gold simulation with expected numbers
```
The simulation uses the **same** `config/pipeline_config.json` rules the Fabric notebooks apply, so the
counts it prints are the counts you should see on Fabric.
