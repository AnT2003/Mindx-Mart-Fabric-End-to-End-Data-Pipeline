# MINDX-Mart — End-to-End Data Pipeline on Microsoft Fabric

**Phần 1 — Final Project.** A production-style **Medallion** (Bronze → Silver → Gold) data pipeline on
Microsoft Fabric for the retailer *MINDX-Mart*: ingest raw CSVs, enforce data quality, model a star
schema with slowly-changing dimensions, and serve the required business marts — all config-driven,
idempotent, audited, and unit-tested.

## What makes it production-grade
- **Config-driven** — one `config/pipeline_config.json` is the single source of truth for paths, table
  names, partitions, DQ rules and SCD specs. No hard-coded values in the notebooks.
- **Reusable library** — `notebooks/00_common_utils` (logger, audit, DQ engine, MERGE, SCD1/SCD2,
  calendar, OPTIMIZE/VACUUM) pulled in via `%run`.
- **Data-quality engine** — rules classify each row REJECT (→ quarantine) or WARN (→ kept + flagged);
  per-rule failure counts logged to `audit_dq_results`.
- **Observability** — every stage logs to `audit_pipeline_run_log` (rows in/out/quarantined, duration,
  status), all tied together by a `batch_id`.
- **Idempotent incremental loads** — Delta **MERGE** upserts everywhere; safe to re-run.
- **SCD Type 2** dimensions (`dim_customer`, `dim_product`) + **Unknown member (-1)** for safe joins.
- **Performance & maintenance** — partitioning + `OPTIMIZE … ZORDER` + `VACUUM`.
- **Tested** — pure rule logic in `src/`, 38 pytest unit tests, plus a real-data local simulation.

## Repository layout
```
Final Project/
├── Data/                              # source CSVs (given)
├── config/
│   └── pipeline_config.json           # single source of truth (paths, tables, DQ rules, SCD/partitions)
├── notebooks/
│   ├── 00_data_quality_assessment.ipynb # BƯỚC 0: khảo sát chất lượng dữ liệu thô (6 chiều) -> findings
│   ├── 00_common_utils.ipynb          # shared library (%run): audit, DQ engine, MERGE, SCD1/2, calendar
│   ├── 01_bronze_ingestion.ipynb      # Bronze: raw CSV -> Parquet, schema-enforced, partitioned
│   ├── 02_silver_cleaning.ipynb       # Silver: DQ engine -> clean + quarantine, MERGE upsert
│   └── 03_gold_modeling.ipynb         # Gold: SCD2 dims + calendar + fact MERGE + marts + OPTIMIZE
├── pipeline/
│   ├── bronze_copy_pipeline.json      # Data Factory Copy pipeline (Bronze)
│   └── master_orchestration_pipeline.json  # chained Bronze -> Silver -> Gold (retries, batch_id, on-failure)
├── sql/
│   └── gold_views.sql                 # marts as SQL views (alternative to Delta tables)
├── src/
│   └── mindx_transforms.py            # pure, testable reference rules (shared with tests + simulation)
├── tests/
│   └── test_transforms.py             # pytest unit tests (38) — no Spark needed
├── erd/
│   ├── mindx_mart_star_schema.drawio  # ERD (draw.io)
│   └── erd_description.md             # ERD write-up + Mermaid
├── docs/
│   ├── architecture.md                # design principles & layer responsibilities
│   ├── data_quality_assessment.md     # BƯỚC 0: báo cáo khảo sát chất lượng (findings -> rules)
│   ├── data_anomalies.md              # every anomaly + DQ rule + validated numbers
│   ├── data_dictionary.md             # every table & column
│   ├── naming_conventions.md          # naming standards
│   └── deployment_guide.md            # step-by-step Fabric deployment
├── analysis/
│   ├── profile_data.py                # raw anomaly profiling
│   └── local_simulation.py            # config-driven Silver+Gold simulation (real numbers)
├── deploy/
│   ├── Deploy-ToFabric.ps1            # one-command automated deployment to your Fabric tenant
│   └── README.md                      # Trial setup + run + troubleshooting
└── README.md
```

## Phương pháp: khảo sát chất lượng TRƯỚC, thiết kế pipeline SAU
Dự án bắt đầu bằng một **Data Quality Assessment** ([docs/data_quality_assessment.md](docs/data_quality_assessment.md))
khảo sát dữ liệu thô theo 6 chiều (Completeness, Uniqueness, Validity, Consistency, Accuracy/Range,
Structure) → ra **14 phát hiện** (5 REJECT · 6 WARN · 3 CLEAN). *Chính các phát hiện này* mới định
nghĩa luật trong `config/pipeline_config.json` và logic làm sạch ở Silver — mọi luật đều truy vết được
về một phát hiện cụ thể.
```
upload raw → 00_data_quality_assessment (findings) → config rules → Bronze → Silver → Gold → Power BI
```

## The three Medallion layers
| Layer | Notebook | Output | Highlights |
|---|---|---|---|
| 🥉 Bronze | `01_bronze_ingestion` (+ Data Factory Copy) | Parquet in `Files/Bronze/` | string schema, lineage cols, partition by load date |
| 🥈 Silver | `02_silver_cleaning` | `silver_sales(_quarantine)`, `silver_exchange_rate(_quarantine)` | config DQ engine, MERGE upsert, `audit_dq_results` |
| 🥇 Gold | `03_gold_modeling` | `dim_*`, `fact_sales`, `gold_*` marts | SCD2, calendar, surrogate keys + unknown member, OPTIMIZE |

## The two required marts
1. **`gold_monthly_revenue_vnd_by_category`** — monthly `Total_Revenue_VND` per category (sales × FX rate).
2. **`gold_promo_effectiveness_by_region`** — % of orders using a discount code, per region.

Both apply the **"Lọc dữ liệu ảo"** filter: exclude `order_status = 'Failed'` and `feedback_score` ∉ 1–5.

## How to run
- **Deploy to Fabric automatically (one command):** [deploy/README.md](deploy/README.md) — runs
  `deploy/Deploy-ToFabric.ps1`, which signs you in (device-code), creates the workspace + Lakehouse,
  uploads the config + CSVs, and imports all notebooks. Then run notebooks 01→02→03.
- **On Fabric manually:** follow [docs/deployment_guide.md](docs/deployment_guide.md).
- **Locally (validation, no Fabric):**
  ```powershell
  python -m pytest tests/ -q          # 38 unit tests on the rule engine
  python analysis/local_simulation.py # end-to-end simulation on the real CSVs
  ```

## Validated results (real source data — reproduced by the test simulation)
| Metric | Value |
|---|---|
| Silver sales clean / quarantine | 4,896 / 354 (246 duplicate + 108 negative shipping) |
| Silver exchange_rate clean / quarantine | 24 / 0 |
| fact_sales rows (item grain) | 9,850 → 5,355 after the fake-data filter |
| Exchange-rate join coverage | 100% (0 unmatched) |
| Revenue / category (all months) | ~13.1B – 13.8B VND each |
| Overall promo usage | 29.86% of reported orders |

## Mapping to the assignment requirements
| Requirement | Where |
|---|---|
| Bronze via Data Factory, CSV→Parquet in `Files/Bronze/` | `pipeline/bronze_copy_pipeline.json` (+ `notebooks/01_*`) |
| Silver via PySpark, clean + quarantine Delta tables | `notebooks/02_silver_cleaning.ipynb` |
| Gold star/snowflake schema | `notebooks/03_gold_modeling.ipynb`, `erd/` |
| ERD in draw.io | `erd/mindx_mart_star_schema.drawio` |
| Monthly `Total_Revenue_VND` by category | `gold_monthly_revenue_vnd_by_category` / `sql/gold_views.sql` |
| Promo effectiveness % by region | `gold_promo_effectiveness_by_region` / `sql/gold_views.sql` |
| Filter Failed + feedback ∉ 1–5 | applied in Gold notebook & SQL views |
