"""
Local end-to-end simulation of Silver + Gold using the SAME rule engine the
notebooks use (src/mindx_transforms.py + config/pipeline_config.json).

It loads the real CSVs, applies the config-driven DQ rules, builds the fact at
item grain, joins the exchange rate, and computes the two marts -- printing the
expected counts/metrics documented in docs/data_anomalies.md.

Run:  python analysis/local_simulation.py
(No Spark / Fabric required. This is a correctness check, not the pipeline.)
"""
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import mindx_transforms as mt  # noqa: E402

DATA = ROOT / "Data"
CFG = mt.load_config()


def banner(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# --------------------------------------------------------------------------- #
# SILVER — exchange rate
# --------------------------------------------------------------------------- #
fx_rules = CFG["data_quality"]["exchange_rate"]
fx_raw = pd.read_csv(DATA / "exchange_rate_2425.csv", dtype=str, keep_default_na=False)
fx_clean, fx_q = [], []
for _, r in fx_raw.iterrows():
    stage = mt.build_fx_stage(r.to_dict())
    res = mt.apply_dq(stage, fx_rules)
    (fx_clean if res["is_clean"] else fx_q).append({**r.to_dict(), **stage})
banner("SILVER exchange_rate")
print("clean:", len(fx_clean), " quarantine:", len(fx_q))
rate_lookup = {(c["year_num"], c["month_num"]): c["rate_num"] for c in fx_clean}

# --------------------------------------------------------------------------- #
# SILVER — sales (config-driven DQ)
# --------------------------------------------------------------------------- #
sales_rules = CFG["data_quality"]["sales"]
sales_raw = pd.read_csv(DATA / "mindx_raw_sales_data.csv", dtype=str, keep_default_na=False)

seen = set()
clean_rows, q_reasons = [], Counter()
for _, r in sales_raw.iterrows():
    raw = r.to_dict()
    oid = (raw.get("order_id") or "").strip()
    is_dup = oid in seen
    seen.add(oid)
    stage = mt.build_sales_stage(raw, is_duplicate=is_dup)
    res = mt.apply_dq(stage, sales_rules)
    if res["is_clean"]:
        clean_rows.append(stage)
    else:
        q_reasons[res["quarantine_reason"]] += 1

banner("SILVER sales")
print("raw rows           :", len(sales_raw))
print("clean silver_sales :", len(clean_rows))
print("quarantine         :", sum(q_reasons.values()))
print("quarantine reasons :")
for reason, n in q_reasons.most_common():
    print(f"   {reason:32s} {n}")

# --------------------------------------------------------------------------- #
# GOLD — explode to item grain, join FX, apply report filter, build marts
# --------------------------------------------------------------------------- #
fact = []
for s in clean_rows:
    for ln, it in enumerate(s["items"]):
        line_usd = float(it.get("price", 0)) * int(it.get("quantity", 0))
        rate = rate_lookup.get((s["order_year"], s["order_month"]))
        fact.append({
            "order_id": s["order_id"], "line_number": ln,
            "year": s["order_year"], "month": s["order_month"],
            "category": it.get("category"), "location": s["location"],
            "order_status": s["order_status"], "has_discount": s["discount_code"] is not None,
            "feedback_is_valid": s["feedback_is_valid"],
            "quantity": int(it.get("quantity", 0)),
            "line_amount_usd": line_usd,
            "exchange_rate": rate,
            "line_amount_vnd": (line_usd * rate) if rate is not None else None,
        })
fact = pd.DataFrame(fact)
banner("GOLD fact_sales (item grain)")
print("fact rows:", len(fact), " missing exchange rate:", int(fact["exchange_rate"].isna().sum()))

# report filter: order_status != 'Failed' AND feedback_is_valid
reported = fact[(fact["order_status"] != "Failed") & (fact["feedback_is_valid"])].copy()
banner("GOLD report filter (Loc du lieu ao)")
print("before:", len(fact), " after:", len(reported))

banner("MART 1 — Total_Revenue_VND by category (all months)")
print(reported.groupby("category")["line_amount_vnd"].sum()
      .sort_values(ascending=False).map(lambda x: f"{x:,.0f}").to_string())

banner("MART 2 — promo effectiveness")
og = reported.groupby("order_id").agg(location=("location", "first"),
                                       has_discount=("has_discount", "max")).reset_index()
print(f"overall promo usage: {og['has_discount'].mean()*100:.2f}% of {len(og)} reported orders")
print("\nAll checks reflect the same config-driven rules the Fabric notebooks apply.")
