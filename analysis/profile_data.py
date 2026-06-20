"""
Local data-profiling script for MINDX-Mart Final Project.

Purpose: discover every data anomaly in the two source CSVs so the Silver-layer
cleaning logic can be designed accurately. This runs locally with pandas (not on
Fabric) and is only an investigation aid -- it is NOT part of the pipeline.
"""
import json
import re
from collections import Counter

import pandas as pd

DATA_DIR = r"C:\Users\an.thai1\Documents\Final Project\Data"
SALES = rf"{DATA_DIR}\mindx_raw_sales_data.csv"
RATES = rf"{DATA_DIR}\exchange_rate_2425.csv"

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)


def banner(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


# --------------------------------------------------------------------------- #
# Sales data
# --------------------------------------------------------------------------- #
sales = pd.read_csv(SALES, dtype=str, keep_default_na=False)
banner("SALES: shape & columns")
print("rows:", len(sales))
print("cols:", list(sales.columns))

banner("SALES: null / empty count per column")
for c in sales.columns:
    empty = (sales[c].str.strip() == "").sum()
    print(f"{c:18s} empty={empty:6d}  distinct={sales[c].nunique():6d}")

banner("SALES: order_id format & duplicates")
print("duplicated order_id:", sales["order_id"].duplicated().sum())
print("sample:", sales["order_id"].head(3).tolist())

banner("SALES: order_date formats")
fmt = Counter()
for v in sales["order_date"]:
    v = v.strip()
    if v == "":
        fmt["<empty>"] += 1
    elif re.match(r"^\d{4}-\d{2}-\d{2}T", v):
        fmt["ISO 8601 (yyyy-mm-ddT...)"] += 1
    elif re.match(r"^\d{2}/\d{2}/\d{4}", v):
        fmt["dd/mm/yyyy HH:MM"] += 1
    else:
        fmt[f"OTHER: {v[:25]}"] += 1
for k, n in fmt.most_common():
    print(f"  {n:7d}  {k}")

banner("SALES: total_amount anomalies")
dollar = sales["total_amount"].str.contains(r"\$", regex=True).sum()
print("contains '$':", dollar)
neg, nonnum = 0, 0
for v in sales["total_amount"]:
    s = v.replace("$", "").replace(",", "").strip()
    try:
        if float(s) < 0:
            neg += 1
    except ValueError:
        nonnum += 1
print("negative:", neg, " non-numeric:", nonnum)
print("samples with $:", sales.loc[sales["total_amount"].str.contains(r"\$"), "total_amount"].head(5).tolist())

banner("SALES: shipping_cost anomalies")
neg = 0
for v in sales["shipping_cost"]:
    try:
        if float(v) < 0:
            neg += 1
    except ValueError:
        pass
print("negative shipping_cost:", neg)
print("distinct negative values:", sorted({float(v) for v in sales["shipping_cost"] if v.strip() and float(v) < 0}))

banner("SALES: payment_method distinct values")
print(Counter(sales["payment_method"]).most_common())

banner("SALES: order_status distinct values")
print(Counter(sales["order_status"]).most_common())

banner("SALES: device_type distinct values")
print(Counter(sales["device_type"]).most_common())

banner("SALES: currency distinct values")
print(Counter(sales["currency"]).most_common())

banner("SALES: feedback_score distribution")
fb = Counter()
for v in sales["feedback_score"]:
    v = v.strip()
    if v == "":
        fb["<empty>"] += 1
    else:
        try:
            f = float(v)
            fb["in 1-5" if 1 <= f <= 5 else f"out-of-range:{f}"] += 1
        except ValueError:
            fb[f"nonnum:{v}"] += 1
print(fb.most_common())

banner("SALES: customer_age anomalies")
ages = []
for v in sales["customer_age"]:
    try:
        ages.append(float(v))
    except ValueError:
        pass
s = pd.Series(ages)
print(s.describe())
print("ages <0 or >120:", ((s < 0) | (s > 120)).sum())

banner("SALES: customer_info JSON parse check")
bad = 0
keys = Counter()
for v in sales["customer_info"].head(2000):
    try:
        d = json.loads(v)
        keys.update(d.keys())
    except Exception:
        bad += 1
print("parse failures (first 2000):", bad, " keys:", keys)

banner("SALES: items JSON parse check & nested keys")
bad = 0
ikeys = Counter()
maxlen = 0
for v in sales["items"].head(2000):
    try:
        arr = json.loads(v)
        maxlen = max(maxlen, len(arr))
        for it in arr:
            ikeys.update(it.keys())
    except Exception:
        bad += 1
print("parse failures (first 2000):", bad, " item keys:", ikeys, " max items/order:", maxlen)

banner("SALES: discount_code presence")
has = (sales["discount_code"].str.strip() != "").sum()
print(f"orders with discount_code: {has} ({has/len(sales)*100:.1f}%)")

# --------------------------------------------------------------------------- #
# Exchange rate data
# --------------------------------------------------------------------------- #
rates = pd.read_csv(RATES, dtype=str, keep_default_na=False)
banner("RATES: shape, columns, content")
print("rows:", len(rates), "cols:", list(rates.columns))
print(rates.to_string())
print("duplicated (year,month):", rates.duplicated(subset=["year", "month"]).sum())
print("from_currency:", Counter(rates["from_currency"]), "to_currency:", Counter(rates["to_currency"]))
