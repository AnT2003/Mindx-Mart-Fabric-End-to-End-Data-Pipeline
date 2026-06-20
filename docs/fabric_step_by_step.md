# Hướng dẫn đẩy dự án lên Microsoft Fabric — đầy đủ từ đầu đến cuối

Hai cách. Bạn chọn **một**:
- **Cách A — Giao diện (UI):** an toàn nhất cho người mới, không phụ thuộc chính sách tenant. *(khuyên dùng lần đầu)*
- **Cách B — Script tự động:** chạy 1 lệnh, nhanh hơn (xem `deploy/README.md`).

> Vị trí file trên máy: `C:\Users\an.thai1\Documents\Final Project\`
> - `config\pipeline_config.json`
> - `Data\mindx_raw_sales_data.csv`, `Data\exchange_rate_2425.csv`
> - `notebooks\00_common_utils.ipynb`, `01_bronze_ingestion.ipynb`, `02_silver_cleaning.ipynb`, `03_gold_modeling.ipynb`

---

## BƯỚC 0 — Có tài khoản & capacity Fabric (làm 1 lần)

1. Vào **https://app.fabric.microsoft.com**, đăng nhập bằng `an.thai1@mservice.com.vn`.
2. Bật **Fabric Trial**: góc trên phải → biểu tượng tài khoản → **Start trial** (được 1 Trial capacity 60 ngày).
   - Nếu nút trial bị khóa → nhờ admin gán cho bạn một **Fabric capacity** (hoặc Power BI Premium/F-SKU).
3. Cần quyền **tạo workspace**. Nếu không có, nhờ admin tạo workspace rồi gán bạn làm *Admin/Member*.

---

# CÁCH A — Làm trên giao diện Fabric (chi tiết)

## A1. Tạo Workspace
1. Menu trái → **Workspaces** → **+ New workspace**.
2. Name: `MINDX-Mart` → mở **Advanced** → **License mode = Trial** (hoặc Fabric capacity của bạn) → **Apply**.

## A2. Tạo Lakehouse
1. Trong workspace `MINDX-Mart` → **+ New item** → tìm **Lakehouse** → đặt tên `LH_MINDX_Mart` → **Create**.
2. Lakehouse mở ra với 2 nhánh: **Tables** và **Files**.

## A3. Upload config + dữ liệu nguồn vào Files
1. Ở khung **Files**, bấm dấu **…** → **New subfolder** → tạo `config`, rồi tạo tiếp `raw`.
2. Vào thư mục `config` → **…** → **Upload** → **Upload files** → chọn
   `config\pipeline_config.json` → Upload.
3. Vào thư mục `raw` → Upload 2 file: `Data\mindx_raw_sales_data.csv` và `Data\exchange_rate_2425.csv`.
4. Kiểm tra: `Files/config/pipeline_config.json`, `Files/raw/mindx_raw_sales_data.csv`,
   `Files/raw/exchange_rate_2425.csv` đều hiện ra.

> Notebook đọc config tại đường dẫn `Files/config/pipeline_config.json` — phải đặt đúng chỗ này.

## A4. Import 4 notebook
1. Vào workspace `MINDX-Mart` → **+ New item** → **Import notebook** (hoặc **Import** → *Notebook*).
2. **From this computer** → chọn cả 4 file `.ipynb` trong thư mục `notebooks\` → Import.
3. Sau khi import, tên notebook phải đúng là:
   `00_common_utils`, `01_bronze_ingestion`, `02_silver_cleaning`, `03_gold_modeling`.
   - **Quan trọng:** giữ nguyên tên `00_common_utils` (các notebook khác gọi `%run 00_common_utils`).

## A5. Gắn Lakehouse mặc định cho từng notebook
Với **mỗi** notebook (mở từng cái):
1. Khung **Explorer/Lakehouses** bên trái → **Add** → **Existing lakehouse** → chọn `LH_MINDX_Mart`.
2. Đảm bảo nó là **default lakehouse** (có dấu ghim). Đây là điều kiện để `spark.table(...)` và đường
   dẫn `Files/...` chạy đúng.

> Nếu dùng Cách B (script), bước A5 đã được tự động gắn sẵn — bỏ qua.

## A6. Chạy pipeline theo thứ tự
Chạy lần lượt (mỗi notebook bấm **Run all**, đợi xong rồi sang cái kế):

| Thứ tự | Notebook | Kết quả mong đợi |
|---|---|---|
| 1 | `01_bronze_ingestion` | Parquet trong `Files/Bronze/sales`, `Files/Bronze/exchange_rate` |
| 2 | `02_silver_cleaning` | Bảng Delta `silver_sales` ≈ **4.896**, quarantine ≈ **354**; `silver_exchange_rate` = 24 |
| 3 | `03_gold_modeling` | `dim_*`, `fact_sales` ≈ **9.850**, và 2 mart `gold_*` |

> Không bắt buộc chạy `00_common_utils` riêng — nó được `%run` tự động bởi 01/02/03.

## A7. (Tùy chọn) Dựng Data Factory Pipeline cho tầng Bronze
Đề bài yêu cầu Bronze bằng **Data Factory Pipeline**. Notebook 01 đã làm tương đương, nhưng nếu cần đúng
hình thức pipeline:
1. Workspace → **+ New item** → **Data pipeline** → tên `PL_Bronze_Ingestion`.
2. **Copy data** → Source: Lakehouse `LH_MINDX_Mart`, file `Files/raw/mindx_raw_sales_data.csv`
   (DelimitedText, *First row as header* = on, Quote `"`, Escape `"`) → Destination: Lakehouse,
   `Files/Bronze/sales`, định dạng **Parquet**.
3. Thêm 1 **Copy data** nữa cho `exchange_rate_2425.csv` → `Files/Bronze/exchange_rate` (Parquet).
4. (Tùy chọn) Tạo `PL_MINDX_Master_Orchestration`: nối Copy(Bronze) → Notebook `02_silver_cleaning`
   → Notebook `03_gold_modeling` (chạy nối tiếp khi *Succeeded*). Tham chiếu `pipeline/*.json`.

## A8. Kiểm tra kết quả (SQL endpoint)
1. Mở `LH_MINDX_Mart` → góc trên phải đổi sang **SQL analytics endpoint**.
2. **New SQL query**, chạy:
```sql
SELECT * FROM gold_monthly_revenue_vnd_by_category ORDER BY year, month, category;
SELECT * FROM gold_promo_effectiveness_by_region   ORDER BY total_orders DESC;
SELECT * FROM audit_pipeline_run_log ORDER BY start_ts DESC;   -- nhật ký chạy
SELECT * FROM audit_dq_results       ORDER BY logged_at DESC;  -- vi phạm chất lượng theo từng luật
```
3. (Tùy chọn) Tạo View nghiệp vụ bằng `sql/gold_views.sql`.

## A9. (Tùy chọn) Báo cáo Power BI
Trên SQL endpoint → **New semantic model** (chọn `fact_sales` + các `dim_*`), hoặc **New report** từ
`gold_*` để vẽ doanh thu theo category và tỷ lệ khuyến mãi theo khu vực.

---

# CÁCH B — Script tự động (1 lệnh)

Chi tiết đầy đủ trong `deploy/README.md`. Tóm tắt:
```powershell
cd "C:\Users\an.thai1\Documents\Final Project\deploy"
.\Deploy-ToFabric.ps1 -ListCapacities                              # đăng nhập + xem capacity
.\Deploy-ToFabric.ps1 -WorkspaceName "MINDX-Mart" -CreateWorkspace -CapacityName "<tên-capacity>"
```
Script sẽ: tạo workspace + Lakehouse, upload config + CSV vào OneLake, import 4 notebook (đã gắn sẵn
Lakehouse). Sau đó vào UI chạy **01 → 02 → 03** như bước A6.

Nếu tenant chặn đăng nhập device-code → dùng `-AccessToken`/`-OneLakeToken` (dán token), hoặc dùng
**Cách A**.

---

# Checklist hoàn thành (đối chiếu đề bài)
- [ ] Bronze: 2 CSV → Parquet trong `Files/Bronze/` (pipeline Data Factory hoặc notebook 01)
- [ ] Silver: PySpark làm sạch → Delta `silver_sales` + `silver_*_quarantine`
- [ ] Gold: Star Schema (`dim_*`, `fact_sales`) + ERD (`erd/…drawio`)
- [ ] Mart 1: `gold_monthly_revenue_vnd_by_category` (doanh thu VNĐ theo category/tháng)
- [ ] Mart 2: `gold_promo_effectiveness_by_region` (% đơn dùng mã giảm giá theo khu vực)
- [ ] Lọc dữ liệu ảo: loại `order_status='Failed'` và feedback ∉ 1–5 (đã áp dụng trong Gold)

# Lỗi thường gặp
| Triệu chứng | Cách xử lý |
|---|---|
| `%run 00_common_utils` báo not found | 4 notebook phải cùng workspace; giữ đúng tên `00_common_utils` |
| `spark.table(...)`/`Files/...` lỗi path | Chưa gắn **default lakehouse** cho notebook (bước A5) |
| Notebook đọc config lỗi FileNotFound | Sai vị trí — phải là `Files/config/pipeline_config.json` |
| Bronze không thấy dữ liệu | Chưa upload CSV vào `Files/raw/`, hoặc chưa chạy notebook 01 |
| Không có capacity | Làm Bước 0 (Start trial) hoặc nhờ admin gán capacity |
