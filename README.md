# MINDX-Mart: End-to-End Data Pipeline on Microsoft Fabric

**Part 1 — Final Project.** A production-grade **Medallion** (Bronze → Silver → Gold) data pipeline built on Microsoft Fabric for the retailer *MINDX-Mart*. This pipeline ingests raw CSVs, enforces data quality, models a star schema with slowly changing dimensions, and serves essential business marts. It is designed to be fully config-driven, idempotent, heavily audited, and comprehensively unit-tested.

## Enterprise-Grade Features

- **Configuration-Driven Architecture**: The single source of truth is `config/pipeline_config.json`, which governs file paths, table names, partitioning, data quality rules, and SCD specifications. No hard-coded values exist within the execution notebooks.
- **Reusable PySpark Library**: Shared utilities (logging, auditing, DQ engine, MERGE logic, SCD1/SCD2 operations, calendar generation, OPTIMIZE/VACUUM) are centralized in `notebooks/00_common_utils` and pulled via `%run`.
- **Robust Data Quality Engine**: DQ rules classify every row as either REJECT (sent to a quarantine table) or WARN (kept but flagged). Failure metrics per rule are automatically recorded in an `audit_dq_results` table.
- **End-to-End Observability**: Every pipeline stage logs its execution metadata (rows in/out/quarantined, execution duration, and status) to `audit_pipeline_run_log`, tied together by a unique `batch_id`.
- **Idempotent Incremental Loads**: Delta **MERGE** upsert operations are used throughout, ensuring the pipeline can safely be re-run without duplicating data.
- **Advanced Star Schema**: Implements **SCD Type 2** for `dim_customer` and `dim_product` to track history, along with an **Unknown member (-1)** strategy to ensure fact-to-dimension joins never drop rows.
- **Table Optimization**: Enforces partition strategies, `OPTIMIZE ... ZORDER`, and `VACUUM` commands to maintain peak querying performance.
- **Test-Driven Reliability**: Pure rule logic is decoupled in `src/`, accompanied by 38 PySpark-free pytest unit tests and an end-to-end local simulation utilizing real source data.

## Methodology: Quality Assessment First, Pipeline Second

The project starts with a comprehensive **Data Quality Assessment** ([docs/data_quality_assessment.md](docs/data_quality_assessment.md)), which profiles the raw data across six dimensions (Completeness, Uniqueness, Validity, Consistency, Accuracy/Range, and Structure). 
This profiling produced **14 actionable findings** (5 REJECT · 6 WARN · 3 CLEAN). *These exact findings* dictate the rules within `config/pipeline_config.json` and the cleansing logic in the Silver layer. Every cleaning rule traces back directly to a specific assessment finding.

```text
Upload Raw CSV → Data Quality Assessment (Findings) → Config Rules → Bronze → Silver → Gold → Power BI
```

## Repository Structure

```text
Final Project/
├── Data/                              # Source CSV files
├── config/
│   └── pipeline_config.json           # Master config (paths, tables, DQ rules, SCD/partitions)
├── notebooks/
│   ├── 00_data_quality_assessment.ipynb # STEP 0: Raw data profiling across 6 dimensions -> findings
│   ├── 00_common_utils.ipynb          # Shared library (%run): audit, DQ engine, MERGE, SCD1/2, calendar
│   ├── 01_bronze_ingestion.ipynb      # Bronze: Raw CSV -> Parquet, schema-enforced, partitioned
│   ├── 02_silver_cleaning.ipynb       # Silver: DQ engine -> clean + quarantine, MERGE upsert
│   └── 03_gold_modeling.ipynb         # Gold: SCD2 dims + calendar + fact MERGE + marts + OPTIMIZE
├── pipeline/
│   ├── bronze_copy_pipeline.json      # Data Factory Copy pipeline (Bronze ingestion)
│   └── master_orchestration_pipeline.json  # Orchestration: Bronze -> Silver -> Gold (retries, batch_id)
├── sql/
│   └── gold_views.sql                 # Business marts deployed as SQL views
├── src/
│   └── mindx_transforms.py            # Pure, testable reference rules (shared with tests and simulation)
├── tests/
│   └── test_transforms.py             # 38 pytest unit tests (Spark not required)
├── erd/
│   ├── mindx_mart_star_schema.drawio  # ERD source file (draw.io)
│   └── erd_description.md             # ERD documentation and Mermaid diagram
├── docs/
│   ├── architecture.md                # Design principles and layer responsibilities
│   ├── data_quality_assessment.md     # STEP 0: Quality assessment report (findings -> rules mapping)
│   ├── data_anomalies.md              # Detailed record of anomalies, DQ rules, and validated metrics
│   ├── data_dictionary.md             # Comprehensive schema definition
│   ├── naming_conventions.md          # Naming and coding standards
│   └── deployment_guide.md            # Step-by-step Fabric deployment instructions
├── analysis/
│   ├── profile_data.py                # Raw anomaly profiling script
│   └── local_simulation.py            # Config-driven Silver+Gold simulation with realistic metrics
├── deploy/
│   ├── Deploy-ToFabric.ps1            # 1-click automated deployment script for the Fabric tenant
│   └── README.md                      # Setup, execution, and troubleshooting documentation
└── README.md
```

## The Medallion Architecture

| Layer | Implementation | Primary Output | Key Operations |
|---|---|---|---|
| 🥉 **Bronze** | `01_bronze_ingestion` (+ Data Factory Copy) | Parquet tables in `Files/Bronze/` | Strict string schema enforcement, lineage columns injection, partition by load date. |
| 🥈 **Silver** | `02_silver_cleaning` | `silver_sales(_quarantine)`, `silver_exchange_rate(_quarantine)` | Configurable DQ engine execution, MERGE upsert operations, automatic `audit_dq_results` tracking. |
| 🥇 **Gold** | `03_gold_modeling` | `dim_*`, `fact_sales`, `gold_*` business marts | SCD Type 2 dimension building, generated calendar, surrogate keys, Unknown Member generation, table optimization. |

## Delivered Business Marts

1. **`gold_monthly_revenue_vnd_by_category`**: Calculates the monthly `Total_Revenue_VND` per category (sales volume × exchange rate).
2. **`gold_promo_effectiveness_by_region`**: Evaluates the percentage of orders utilizing a discount code, aggregated by region.

Both marts inherently apply the **Virtual Data Filter** condition required by the assignment specification: automatically excluding rows where `order_status = 'Failed'` and `feedback_score` is outside the valid range of 1–5.

## Execution Guide

- **Automated Deployment to Fabric (One-Command):** Reference [deploy/README.md](deploy/README.md). Execute the PowerShell script `deploy/Deploy-ToFabric.ps1` to handle tenant authentication (device-code), provision the Workspace and Lakehouse, upload configuration assets and CSVs, and import the notebooks. Once deployed, trigger notebooks 01 → 02 → 03 sequentially.
- **Manual Fabric Setup:** Follow the step-by-step instructions in [docs/deployment_guide.md](docs/deployment_guide.md).
- **Local Validation (Without Fabric Environment):**
  ```powershell
  python -m pytest tests/ -q          # Run the 38 unit tests covering the core rule engine
  python analysis/local_simulation.py # Execute the end-to-end data simulation using local source CSVs
  ```

## Verified Data Metrics (Local Simulation against Real Sources)

| Target Metric | Output Value |
|---|---|
| Silver `sales` clean / quarantine | 4,896 / 354 (246 duplicates + 108 negative shipping metrics) |
| Silver `exchange_rate` clean / quarantine | 24 / 0 |
| `fact_sales` rows (item grain) | 9,850 → drops to 5,355 after applying the filtering logic |
| Exchange-rate join coverage | 100% (0 unmatched records) |
| Revenue per category (all months) | ~13.1B – 13.8B VND per category |
| Overall promo usage rate | 29.86% of reported valid orders |

## Final Requirements Mapping

| Assignment Requirement | Implementation Location |
|---|---|
| Bronze integration via Data Factory, CSV→Parquet to `Files/Bronze/` | `pipeline/bronze_copy_pipeline.json` and `notebooks/01_*` |
| Silver layer via PySpark, clean + quarantine Delta tables | `notebooks/02_silver_cleaning.ipynb` |
| Gold star/snowflake schema implementation | `notebooks/03_gold_modeling.ipynb` and `erd/` |
| Entity-Relationship Diagram (ERD) created in draw.io | `erd/mindx_mart_star_schema.drawio` |
| Reporting: Monthly `Total_Revenue_VND` organized by category | `gold_monthly_revenue_vnd_by_category` / `sql/gold_views.sql` |
| Reporting: Promo effectiveness percentage by region | `gold_promo_effectiveness_by_region` / `sql/gold_views.sql` |
| Exclusion of Failed orders + invalid feedback scores (∉ 1–5) | Handled universally in the Gold notebook & SQL views |
