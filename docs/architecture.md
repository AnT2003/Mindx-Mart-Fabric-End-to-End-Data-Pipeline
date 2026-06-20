# Architecture

## Overview

A production-style **Medallion** (Bronze → Silver → Gold) lakehouse on Microsoft Fabric, driven by a
single configuration file and a shared utilities library, with built-in data quality, auditing, and
slowly-changing dimensions.

```
   [BƯỚC 0] 00_data_quality_assessment  ──(14 findings: 5 REJECT/6 WARN/3 CLEAN)──┐
            khảo sát raw theo 6 chiều                                            │ định hướng luật
                                                                                 ▼
                 config/pipeline_config.json   (single source of truth)
                                │
        ┌───────────────────────┼───────────────────────────┐
        ▼                       ▼                             ▼
   Files/raw/*.csv      notebooks/00_common_utils      src/mindx_transforms.py
        │              (logger · audit · DQ engine ·    (pure reference rules
        │               merge · SCD1/SCD2 · calendar)    + unit tests)
        ▼
 ┌──────────────┐   Data Factory Copy   ┌──────────────┐   PySpark DQ    ┌──────────────┐   PySpark model
 │   RAW (csv)  │ ───────────────────▶ │ BRONZE parquet│ ─────────────▶ │ SILVER delta │ ─────────────▶ ┌────────────┐
 └──────────────┘                       │ Files/Bronze/ │   + quarantine  │ clean + q'tine│   SCD2 + fact   │ GOLD delta │
                                         └──────────────┘                 └──────────────┘                 │ star + marts│
                                                                                                            └────────────┘
                                   audit_pipeline_run_log  ·  audit_dq_results   (observability)
```

## Design principles

| Principle | How it is implemented |
|---|---|
| **Config-driven** | Paths, table names, partitions, DQ rules, SCD specs all live in `config/pipeline_config.json`. Notebooks contain *no* hard-coded table names or rules. |
| **DRY / single source of truth** | One utilities notebook (`00_common_utils`) included via `%run`. DQ rules defined once; the Spark engine and the Python reference (`src/`) both read them. |
| **Idempotency** | Silver & Gold use Delta **MERGE** upserts keyed on business keys. Re-running a batch does not duplicate rows. |
| **Data quality as a first-class concern** | A rules engine classifies each row REJECT (→ quarantine) or WARN (→ kept + flagged); per-rule failure counts are logged to `audit_dq_results`. |
| **Observability** | Every layer/entity writes a row to `audit_pipeline_run_log` (rows in/out/quarantined, duration, status, message). |
| **History** | `dim_customer` & `dim_product` are **SCD Type 2** (valid_from / valid_to / is_current). |
| **Referential safety** | Every dimension has an **Unknown member (sk = -1)**; fact lookups `coalesce` missing keys to -1 so joins never silently drop facts. |
| **Performance** | Partitioning (Bronze by load date; Silver/fact by year+month) and `OPTIMIZE … ZORDER` + `VACUUM` on Gold. |
| **Testability** | Pure rule logic in `src/mindx_transforms.py`, covered by `tests/` (pytest, no cluster), and exercised over real data by `analysis/local_simulation.py`. |

## Layer responsibilities

### Bước 0 — Data Quality Assessment (`00_data_quality_assessment`)
- **Chạy đầu tiên**, đọc dữ liệu thô (`Files/raw`), khảo sát theo 6 chiều chất lượng và ghi bảng
  `dq_assessment_findings`.
- Đây là bước **đo lường trước khi thiết kế**: các phát hiện REJECT/WARN/CLEAN ở đây là cơ sở để định
  nghĩa luật trong `config/pipeline_config.json` và logic làm sạch ở Silver. Xem
  `docs/data_quality_assessment.md`.

### Bronze (`01_bronze_ingestion`)
- Read raw CSV with an **explicit string schema** (no inference → nothing coerced/dropped).
- Add lineage columns `_ingested_at`, `_source_file`, `_batch_id`, `_load_date`.
- Persist Parquet under `Files/Bronze/`, partitioned by `_load_date`. No business logic.
- Required deliverable form is a **Data Factory Copy pipeline** (`pipeline/bronze_copy_pipeline.json`);
  the notebook is the code-equivalent invoked by the master pipeline.

### Silver (`02_silver_cleaning`)
- Parse/normalise into typed, derived columns (date, amount, payment, items/customer JSON, flags).
- Apply the **config DQ rules** → split clean / quarantine; log `audit_dq_results`.
- **MERGE-upsert** the clean output into `silver_sales` / `silver_exchange_rate`; append quarantine.

### Gold (`03_gold_modeling`)
- Build dimensions: generated `dim_date`; **SCD2** `dim_customer`, `dim_product`; **SCD1**
  `dim_location`, `dim_payment_method`; reference `dim_exchange_rate`.
- Build `fact_sales` at **order-item grain**, convert USD→VND via the monthly rate, attach surrogate
  keys (unknown → -1), MERGE-upsert, then `OPTIMIZE/ZORDER/VACUUM`.
- Build the two marts with the *Lọc dữ liệu ảo* filter applied.

## Batch & lineage
A `batch_id` (timestamp) is generated by the master pipeline and threaded through every notebook
(`notebookutils.notebook.exit` / parameters). All rows written in a run carry `_batch_id`, so a single
run is traceable end-to-end across Bronze, Silver, Gold, and both audit tables.
