"""
DATA QUALITY ASSESSMENT (DQA) — bước khảo sát chất lượng dữ liệu ĐẦU TIÊN.

Đây là bước phải làm TRƯỚC khi thiết kế pipeline: khảo sát dữ liệu thô theo 6 chiều
chất lượng chuẩn (Completeness, Uniqueness, Validity, Consistency, Accuracy/Range,
Structure), chấm mức độ (severity) và đề xuất hành động (REJECT / WARN / CLEAN).
Chính các phát hiện ở đây là cơ sở để định nghĩa luật trong config/pipeline_config.json
và logic làm sạch ở tầng Silver.

Bản local (pandas) để chạy nhanh, lấy số thật. Bản PySpark chạy trên Fabric:
notebooks/00_data_quality_assessment.ipynb.

Chạy:  python analysis/data_quality_assessment.py
Xuất:  analysis/dq_assessment_findings.csv  (bảng phát hiện)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "Data"
OUT = Path(__file__).resolve().parent / "dq_assessment_findings.csv"

pd.set_option("display.width", 200)
findings = []  # (dimension, table, column, issue, severity, count, pct, action, proposed_rule)


def add(dim, table, col, issue, severity, count, total, action, rule=""):
    pct = round(count / total * 100, 2) if total else 0.0
    findings.append([dim, table, col, issue, severity, count, pct, action, rule])


def banner(t):
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


from datetime import datetime
TODAY = datetime(2026, 6, 16)


def parse_dt(v):
    v = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt)
        except (ValueError, TypeError):
            continue
    return None


def parse_date(v):
    return parse_dt(v) is not None


# =========================================================================== #
# Đọc dữ liệu thô (giữ nguyên dạng chuỗi như Bronze)
# =========================================================================== #
sales = pd.read_csv(DATA / "mindx_raw_sales_data.csv", dtype=str, keep_default_na=False)
rates = pd.read_csv(DATA / "exchange_rate_2425.csv", dtype=str, keep_default_na=False)
N = len(sales)
NR = len(rates)
banner(f"PHẠM VI KHẢO SÁT: sales={N} dòng, {sales.shape[1]} cột | exchange_rate={NR} dòng")

# =========================================================================== #
# 1) COMPLETENESS — thiếu/null/rỗng
# =========================================================================== #
banner("1) COMPLETENESS (tính đầy đủ) — tỉ lệ rỗng theo cột [sales]")
for c in sales.columns:
    empty = int((sales[c].str.strip() == "").sum())
    print(f"  {c:16s} empty={empty:6d} ({empty/N*100:5.1f}%)  distinct={sales[c].nunique():6d}")
    if empty > 0:
        sev = "WARN" if c in ("device_type", "customer_age", "discount_code", "feedback_score") else "REJECT"
        act = "Điền giá trị mặc định / null + cờ" if sev == "WARN" else "Cách ly nếu là cột bắt buộc"
        add("Completeness", "sales", c, "Giá trị rỗng", sev, empty, N, act)

# =========================================================================== #
# 2) UNIQUENESS — trùng lặp / khóa
# =========================================================================== #
banner("2) UNIQUENESS (tính duy nhất)")
dup = int(sales["order_id"].duplicated().sum())
print(f"  order_id: {N} dòng / {sales['order_id'].nunique()} mã duy nhất -> {dup} dòng trùng")
add("Uniqueness", "sales", "order_id", "Trùng khóa nghiệp vụ", "REJECT", dup, N,
    "Giữ bản ghi đầu, cách ly bản trùng", "SAL_006 duplicate_order_id")
ratedup = int(rates.duplicated(subset=["year", "month"]).sum())
print(f"  exchange_rate (year,month): {ratedup} dòng trùng")

# =========================================================================== #
# 3) VALIDITY — đúng định dạng/kiểu/miền giá trị
# =========================================================================== #
banner("3) VALIDITY (tính hợp lệ)")

# order_date
fmt = Counter()
for v in sales["order_date"]:
    v = v.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T", v):
        fmt["ISO-8601"] += 1
    elif re.match(r"^\d{2}/\d{2}/\d{4}", v):
        fmt["dd/MM/yyyy"] += 1
    else:
        fmt["KHÁC/không parse"] += 1
unparse = sum(1 for v in sales["order_date"] if not parse_date(v))
print(f"  order_date định dạng: {dict(fmt)} | không parse được: {unparse}")
add("Validity", "sales", "order_date", "Nhiều định dạng ngày (ISO + dd/MM/yyyy)", "REJECT",
    int(fmt.get("dd/MM/yyyy", 0)), N, "Parse đa định dạng -> timestamp; lỗi -> cách ly",
    "SAL_002 unparseable_order_date")

# total_amount
dollar = int(sales["total_amount"].str.contains(r"\$").sum())
nonpos = 0
for v in sales["total_amount"]:
    s = re.sub(r"[^0-9.\-]", "", v)
    try:
        if float(s) <= 0:
            nonpos += 1
    except ValueError:
        nonpos += 1
print(f"  total_amount có '$': {dollar} | không dương/không số (sau làm sạch): {nonpos}")
add("Validity", "sales", "total_amount", "Lẫn ký tự tiền tệ '$'", "CLEAN", dollar, N,
    "regexp_replace bỏ ký tự, ép double", "(làm sạch tại chỗ)")
add("Validity", "sales", "total_amount", "Giá trị <= 0 hoặc không phải số", "REJECT", nonpos, N,
    "Cách ly", "SAL_003 invalid_total_amount")

# feedback_score
fb = Counter()
for v in sales["feedback_score"]:
    v = v.strip()
    if v == "":
        fb["rỗng"] += 1
    else:
        try:
            f = float(v); fb["trong 1-5" if 1 <= f <= 5 else "ngoài thang (vd 99)"] += 1
        except ValueError:
            fb["không số"] += 1
print(f"  feedback_score: {dict(fb)}")
out_scale = fb.get("ngoài thang (vd 99)", 0) + fb.get("rỗng", 0)
add("Validity", "sales", "feedback_score", "Ngoài thang 1-5 (sentinel 99) hoặc rỗng", "WARN",
    out_scale, N, "Giữ + cờ feedback_is_valid; lọc ở Gold", "SAL_101 feedback_out_of_scale")

# items JSON
bad_items = 0
for v in sales["items"]:
    try:
        arr = json.loads(v)
        if not isinstance(arr, list) or len(arr) == 0:
            bad_items += 1
    except Exception:
        bad_items += 1
print(f"  items JSON hỏng/rỗng: {bad_items}")
add("Structure", "sales", "items", "Mảng JSON hỏng hoặc rỗng", "REJECT", bad_items, N,
    "Cách ly", "SAL_004 invalid_items_json")

# =========================================================================== #
# 4) CONSISTENCY — chuẩn hóa giá trị phân loại
# =========================================================================== #
banner("4) CONSISTENCY (tính nhất quán)")
pm = Counter(sales["payment_method"])
print(f"  payment_method biến thể: {dict(pm)}")
variants = sum(v for k, v in pm.items() if k.lower().replace("_", "").replace(" ", "") == "creditcard")
add("Consistency", "sales", "payment_method", "Cùng 1 giá trị nhiều cách viết (credit_card/CREDITCARD/Credit Card)",
    "CLEAN", variants, N, "Chuẩn hóa về Credit Card/PayPal/COD", "(làm sạch tại chỗ)")
print(f"  currency: {dict(Counter(sales['currency']))}")
print(f"  order_status: {dict(Counter(sales['order_status']))}")

# =========================================================================== #
# 5) ACCURACY / RANGE — biên giá trị số
# =========================================================================== #
banner("5) ACCURACY / RANGE (độ chính xác / biên giá trị)")
neg_ship = int(sum(1 for v in sales["shipping_cost"] if v.strip() and float(v) < 0))
print(f"  shipping_cost < 0: {neg_ship} (giá trị âm bất khả thi)")
add("Accuracy", "sales", "shipping_cost", "Giá trị âm (bất khả thi)", "REJECT", neg_ship, N,
    "Cách ly", "SAL_005 negative_or_invalid_shipping")
ages = pd.to_numeric(sales["customer_age"].replace("", None), errors="coerce")
amin, amax = ages.min(), ages.max()
out_age = int(((ages < 18) | (ages > 100)).sum())
print(f"  customer_age range: [{amin}, {amax}] | ngoài 18-100: {out_age}")
add("Accuracy", "sales", "customer_age", "Tuổi ngoài khoảng 18-100", "WARN", out_age, N,
    "Giữ + cờ cảnh báo", "SAL_102 customer_age_out_of_range")

# item price/quantity (bung items)
prices, qtys = [], []
for v in sales["items"]:
    try:
        for it in json.loads(v):
            prices.append(float(it.get("price", 0))); qtys.append(int(it.get("quantity", 0)))
    except Exception:
        pass
ps, qs = pd.Series(prices), pd.Series(qtys)
print(f"  item price: min={ps.min():.2f} max={ps.max():.2f} | quantity: min={qs.min()} max={qs.max()}")

# =========================================================================== #
# 6) STRUCTURE — cột bán cấu trúc
# =========================================================================== #
banner("6) STRUCTURE (cấu trúc) — cột JSON lồng")
bad_cust = 0
for v in sales["customer_info"]:
    try:
        d = json.loads(v)
        if not isinstance(d, dict):
            bad_cust += 1
    except Exception:
        bad_cust += 1
print(f"  customer_info parse được dạng object: {N - bad_cust}/{N} (lỗi {bad_cust})")
print("  items: mảng object {product_id, category, price, quantity} — cần explode ở Gold")
add("Structure", "sales", "customer_info", "JSON object lồng trong cột", "CLEAN", N, N,
    "from_json tách name/email/phone", "(làm sạch tại chỗ)")

# =========================================================================== #
# 7) TIMELINESS / TEMPORAL — khảo sát ngày giờ & độ phủ tỷ giá theo tháng
# =========================================================================== #
banner("7) TIMELINESS / TEMPORAL (ngày giờ)")
dts = [parse_dt(v) for v in sales["order_date"]]
ok = [d for d in dts if d is not None]
n_future = sum(1 for d in ok if d > TODAY)
n_outside = sum(1 for d in ok if d.year not in (2024, 2025))
n_midnight = sum(1 for d in ok if d.hour == 0 and d.minute == 0 and d.second == 0)
print(f"  Phạm vi ngày: {min(ok).date()} → {max(ok).date()} | phân bố năm: "
      f"{dict(Counter(d.year for d in ok))}")
print(f"  Ngày tương lai (> {TODAY.date()}): {n_future}")
print(f"  Ngoài cửa sổ 2024-2025: {n_outside}")
print(f"  Mốc đúng 00:00:00 (đáng ngờ): {n_midnight}")

# Độ phủ tỷ giá: mọi (năm, tháng) của đơn phải có dòng tỷ giá tương ứng
rate_ym = set(zip(pd.to_numeric(rates["year"]), pd.to_numeric(rates["month"])))
order_ym = Counter((d.year, d.month) for d in ok)
missing_ym = [ym for ym in order_ym if ym not in rate_ym]
orders_uncovered = sum(order_ym[ym] for ym in missing_ym)
print(f"  Độ phủ tỷ giá: {len(rate_ym)} tháng có tỷ giá, {len(order_ym)} tháng có đơn | "
      f"tháng đơn KHÔNG có tỷ giá: {len(missing_ym)} → {orders_uncovered} dòng bị ảnh hưởng")

add("Timeliness", "sales", "order_date", "Ngày trong tương lai (> hôm nay)", "REJECT",
    n_future, N, "Cách ly (đơn không thể ở tương lai)", "SAL_105 order_date_in_future")
add("Timeliness", "sales", "order_date", "Ngày ngoài cửa sổ 2024-2025 (không có tỷ giá để quy đổi)",
    "WARN", n_outside, N, "Giữ + cờ; cảnh báo quy đổi VND", "SAL_104 order_date_outside_rate_coverage")
add("Timeliness", "sales<->exchange_rate", "order year-month",
    "Tháng đơn không có dòng tỷ giá (độ phủ chéo nguồn)",
    "REJECT" if orders_uncovered else "OK", orders_uncovered, N,
    "Kiểm tra ở Gold (left join -> đếm null); bổ sung tỷ giá nếu thiếu",
    "(Gold: missing_fx count)")

# =========================================================================== #
# Exchange rate
# =========================================================================== #
banner("KHẢO SÁT exchange_rate")
ry = pd.to_numeric(rates["year"], errors="coerce")
rm = pd.to_numeric(rates["month"], errors="coerce")
rr = pd.to_numeric(rates["exchange_rate"], errors="coerce")
print(f"  year hợp lệ: {int(ry.between(2000,2100).sum())}/{NR} | month 1-12: {int(rm.between(1,12).sum())}/{NR}"
      f" | rate>0: {int((rr>0).sum())}/{NR}")
print(f"  cặp tiền tệ: {dict(Counter(zip(rates['from_currency'], rates['to_currency'])))}")
print("  -> exchange_rate sạch hoàn toàn (vẫn áp luật FX_001..FX_004 phòng thủ).")

# =========================================================================== #
# TỔNG HỢP & XUẤT
# =========================================================================== #
df = pd.DataFrame(findings, columns=["dimension", "table", "column", "issue", "severity",
                                     "count", "pct", "recommended_action", "proposed_rule"])
df.to_csv(OUT, index=False, encoding="utf-8")
banner("BẢNG PHÁT HIỆN CHẤT LƯỢNG (DQ FINDINGS)")
print(df.to_string(index=False))
banner("KẾT LUẬN")
print(f"Tổng phát hiện: {len(df)} | REJECT: {(df.severity=='REJECT').sum()} "
      f"| WARN: {(df.severity=='WARN').sum()} | CLEAN: {(df.severity=='CLEAN').sum()}")
print(f"Đã xuất bảng findings -> {OUT}")
print("\n=> Các phát hiện REJECT/WARN ở trên chính là cơ sở để định nghĩa luật trong "
      "config/pipeline_config.json (mục data_quality) và logic làm sạch ở tầng Silver.")
