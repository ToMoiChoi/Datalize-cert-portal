# Datalize Certificate Generator

Static certificate site for `https://certificate.datalize.cloud/<ID>/`, similar to Udemy certificates.
Mỗi certificate có một trang riêng gồm ảnh PNG, file PDF, nút **Add to LinkedIn profile**, các nút share và mã QR để xác thực.

> **Quy tắc chính:**
> - Danh sách học viên nằm trong **Google Sheet dùng chung** ([Datalize Certificates – Học viên đạt output](https://docs.google.com/spreadsheets/d/1og9gE92u1plMpU_h2UX-qae2H-_LMCWySWZmR8mAlbw/edit)). Sheet này đồng thời là sổ quản lý học viên đạt output của từng khoá.
> - Mọi nội dung đều sinh ra từ Sheet + `config.json` + `templates/` + `assets/`. **Không sửa tay bất cứ file nào trong `site/`.**

---

## 1. Cài đặt (mỗi máy trainer làm 1 lần)
1. Cài **Python 3.10+** từ python.org. Khi cài nhớ tick **"Add python.exe to PATH"**.
2. Bấm đúp **`setup.bat`**. File này tạo môi trường riêng ở `%LOCALAPPDATA%\datalize-cert\venv` (đặt ngoài OneDrive để không bị sync hay khoá file), rồi cài thư viện và trình duyệt Chromium để render cert.
3. Xin admin file **`service-account.json`** và chép vào thư mục `data/`. Đây là khoá để tool đọc/ghi Sheet. Chỉ gửi file này qua kênh riêng, **không commit, không gửi vào group chat** (file đã nằm trong `.gitignore`).

Muốn chạy bằng dòng lệnh thì dùng `%LOCALAPPDATA%\datalize-cert\venv\Scripts\python.exe gen.py ...`, hoặc tự cài: `pip install -r requirements.txt` rồi `playwright install chromium`.

## 2. Quy trình cấp certificate
1. Mở Sheet, tab **Students**. Mỗi học viên một dòng; khi học viên còn đang học thì để `status = Pending`.
2. Khi học viên đạt output: kiểm tra lại họ tên, email, khoá, loại cert, tên project rồi chuyển `status` sang **Ready**.
3. Bấm đúp **`issue.bat`**. Tool sẽ:
   - cấp ID và render cert (PNG, PDF, trang web, QR) cho mọi dòng **Ready**;
   - ghi ngược `cert_id`, `cert_link`, `issued_at` vào Sheet và đổi status sang **Issued**;
   - dòng nào sai dữ liệu thì ghi `Lỗi: ...` vào cột `note` và giữ nguyên Ready. Sửa xong thì bấm `issue.bat` lại;
   - tải về các cert mà trainer khác đã cấp (hoặc vừa đổi sang Revoked), để `site/` trên máy bạn luôn đầy đủ.
4. Kiểm tra cert mới trong `site/<ID>/` theo checklist ở mục 8.
5. Upload thư mục `site/` lên hosting (mục 9), rồi gửi `cert_link` cho học viên.

**Thu hồi cert cấp sai:** đổi status của dòng đó sang **Revoked** rồi bấm `issue.bat`; trang cert sẽ hiện REVOKED. Không xoá dòng và không xoá thư mục.

**Sửa tên hoặc project của cert đã cấp:** sửa ô trong Sheet, đổi status về **Ready** rồi bấm `issue.bat`. Cert được render lại với **ID cũ**.

## 3. Google Sheet

| Cột | Ai điền | Ghi chú |
|---|---|---|
| name | Trainer | Họ tên đầy đủ, **tiếng Việt có dấu**, thứ tự Họ Đệm Tên (vd. `Nguyễn Thị Minh Phượng`). In y nguyên lên cert |
| email | Trainer | Dùng để chống cấp trùng; **không** hiện trên cert hay trang web |
| course | Trainer | Chọn từ dropdown. Dropdown được tool tự cập nhật theo `config.json` mỗi lần chạy |
| type | Trainer | `completion` (hoàn thành, nộp final project) hoặc `participation` (chỉ tham gia) |
| project | Trainer | Tên final project; để trống nếu là participation |
| organization | Trainer | Tên doanh nghiệp nếu là lớp doanh nghiệp. Chỉ dùng để quản lý/lọc, **không in lên cert** |
| issue_date | Trainer | `yyyy-mm-dd`; để trống thì tool điền ngày chạy |
| status | Trainer | `Pending` → `Ready` → `Issued`; `Revoked` để thu hồi |
| cert_id, cert_link, issued_at | **Tool** | Không sửa tay (Sheet sẽ cảnh báo). ID đã in trên cert và QR |
| note | Cả hai | Ghi chú tự do; tool ghi lỗi vào đây |

Tab **Hướng dẫn** trong Sheet tóm tắt các bước trên cho trainer.

### Thiết lập service account (admin làm 1 lần)
Tool đăng nhập Sheet bằng một **Google service account**. Nhờ vậy Sheet vẫn để private (Sheet chứa email học viên) mà không trainer nào phải đăng nhập Google trong tool.
1. Vào [console.cloud.google.com](https://console.cloud.google.com), tạo project (vd. `datalize-cert`).
2. **APIs & Services → Library**, bật **Google Sheets API**.
3. **IAM & Admin → Service Accounts → Create service account** (vd. `cert-bot`). Không cần cấp role nào.
4. Mở service account vừa tạo → **Keys → Add key → Create new key → JSON**, tải file về, đổi tên thành `service-account.json` và đặt vào `data/`.
5. Mở Sheet → **Share** → dán email của service account (dạng `cert-bot@<project>.iam.gserviceaccount.com`, có trong file JSON ở trường `client_email`) → quyền **Editor**.
6. Thêm trainer mới: share Sheet cho email Google của trainer (Editor) và gửi riêng file `service-account.json` cho họ.

Cấu hình trong `config.json`:
```json
"sheet": { "id": "<ID trong link Sheet>", "tab": "Students", "credentials": "data/service-account.json" }
```

**Lưu ý kỹ thuật:** tool tự ký token cho service account bằng thư viện `rsa` (Python thuần) và gọi trực tiếp Google Sheets REST API, không dùng `gspread`/`google-auth`. Lý do: thư viện `cryptography` đi kèm `gspread` có file DLL mà Windows Smart App Control chặn trên một số máy.

## 4. Chuẩn nội dung (`config.json`)

| Mục | Giá trị hiện tại | Ghi chú |
|---|---|---|
| `courses.PBI.name` | Power BI for Business Users | |
| `courses.PBI.hours` / `sessions` | **16** giờ / **8** buổi | 8 buổi × 2h. Khi đổi một trong hai giá trị, kiểm tra lại cho khớp nhau |
| `signers[0].name` | **Đỗ Văn Khả** | Viết tiếng Việt có dấu, thứ tự **Họ Đệm Tên**, giống cách ghi tên học viên |
| `signers[0].title` | Lead Instructor, Datalize | |
| `signers[0].signature_image` | (trống) | Có thể thêm PNG chữ ký nền trong suốt, ví dụ `assets/signature.png`. Để trống thì in tên bằng font chữ ký |
| `issuer.logo` | `assets/logo-dark.png` | Logo dùng trên panel navy của certificate |
| `issuer.linkedin_org_id` | (trống) | Điền ID LinkedIn Page của Datalize để LinkedIn hiện đúng logo công ty |

**Skills covered**: danh sách chuẩn dùng chung cho certificate và kỹ năng học viên add lên LinkedIn. Giữ đúng tên và thứ tự:

1. Microsoft Power BI
2. DAX
3. Data Modeling (Star Schema)
4. Time Intelligence
5. Data Visualization
6. Dashboard Design
7. Power BI Service
8. Row-Level Security (RLS)
9. KPI Reporting
10. Data Storytelling

Tối đa khoảng **10–11 chip**, mỗi chip ngắn gọn; nhiều hơn sẽ đẩy khối chữ ký xuống trên certificate.

**Thêm khoá mới:** thêm một mục trong `courses` với mã khoá (vd. `SQL`), tên, `hours`, `sessions`, `skills`. Lần chạy `issue.bat` tiếp theo sẽ tự thêm mã khoá vào dropdown trong Sheet.

Sau khi sửa `config.json`, `templates/` hoặc `assets/`: chạy `gen.py --rebuild` để render lại toàn bộ, kiểm tra PNG, rồi commit.

## 5. Logo & nhận diện thương hiệu
Logo chính thức lấy từ datalize.cloud (đèn bàn + chữ DATALIZE + "GET INSIGHTS EASIER"), đã tách nền trong suốt thành 2 bản:

| File | Dùng ở đâu | Màu |
|---|---|---|
| `assets/logo-dark.png` | Panel navy bên trái certificate (`issuer.logo`) | Đèn + chữ DATALIZE vàng `#FFB900`, tagline trắng |
| `assets/logo.png` | Header các trang web (`templates/page.html`, `templates/index.html`) | Navy `#083866`, tagline xám đậm |

- Khi muốn thay logo, giữ nguyên 2 tên file trên, dùng PNG nền trong suốt, chiều rộng khoảng 900px, rồi `--rebuild`.
- Đừng thêm CSS `filter` lên logo của certificate; bản `logo-dark.png` đã đúng màu thương hiệu.
- Màu chủ đạo (trong `templates/certificate.html` và `assets/site.css`): navy `#0B1F3A`, gold `#C9A227`, teal `#0EA5A0`.
- Font (đã tự host, có bộ ký tự tiếng Việt): Be Vietnam Pro (chữ thường), Playfair Display (tiêu đề, tên học viên), Great Vibes (chữ ký).

## 6. Lệnh của `gen.py`
```bash
python gen.py --sheet               # cấp cert cho các dòng Ready trong Sheet (issue.bat chạy lệnh này)
python gen.py data/students.csv     # cách dự phòng: cấp cert từ file CSV (cùng các cột như Sheet)
python gen.py --rebuild             # render lại TOÀN BỘ sau khi sửa config/template/assets
python gen.py --revoke DLZ-XXXXXXXX # thu hồi cert; nếu có Sheet thì tự đổi status dòng đó sang Revoked
python gen.py --list                # in danh sách cert đã cấp trên máy này
```
Chạy lại không tạo cert trùng: cùng email + khoá + loại cert thì giữ nguyên ID.

## 7. Cấu trúc thư mục
```
config.json              issuer, courses, signer, loại cert, thông tin Sheet
gen.py                   script build (đọc Sheet/CSV, render bằng Playwright/Chromium)
setup.bat / issue.bat    cài đặt 1 lần / cấp cert (bấm đúp)
requirements.txt         thư viện Python
data/service-account.json  khoá service account. PRIVATE, không commit
data/registry.json       sổ cấp phát trên máy này (đồng bộ từ Sheet). PRIVATE, có email
data/issued_links.csv    link gửi học viên. PRIVATE
data/students.csv        input dự phòng khi không dùng Sheet
templates/
  certificate.html       mẫu certificate A4 ngang (1123×794) → PNG + PDF
  page.html              trang public của từng certificate
  index.html             trang tra cứu theo ID và trang 404
assets/                  logo.png, logo-dark.png, favicon.svg, fonts/, site.css
site/                    OUTPUT. Upload nguyên thư mục này
  index.html, 404.html, .htaccess, robots.txt
  <ID>/index.html        trang certificate
  <ID>/certificate.png|pdf, og.jpg (ảnh preview khi share)
```

## 8. Checklist trước khi deploy
- [ ] Certificate PNG: logo rõ nét, tên học viên có dấu đúng, không bị tràn dòng
- [ ] Seal và dòng "Length" hiển thị đúng số giờ/buổi (hiện tại **16h · 8 sessions**)
- [ ] Skills đúng danh sách ở mục 4, khối chữ ký không bị đẩy lệch
- [ ] Tên người ký: **Đỗ Văn Khả**, Lead Instructor, Datalize
- [ ] Trang `site/<ID>/index.html`: logo header hiển thị đúng, nút LinkedIn/QR hoạt động
- [ ] Trong Sheet không còn dòng Ready nào có `Lỗi: ...` ở cột note
- [ ] `data/` (registry, key, links) **không** nằm trong `site/`

## 9. Deploy lên certificate.datalize.cloud

**Cách A: Hostinger (shared hosting)**: `gen.py` tự sinh `site/.htaccess` (trang 404, ép HTTPS, cache). Upload toàn bộ nội dung `site/` vào thư mục web của subdomain `certificate`. **Upload đè, không xoá file trên server**, để không mất cert do trainer khác đã upload.

**Cách B: Cloudflare Pages (miễn phí)**
```bash
npx wrangler pages deploy site --project-name datalize-certificate
```
Sau đó vào Cloudflare → Pages → datalize-certificate → Custom domains và thêm `certificate.datalize.cloud`. Nếu DNS không nằm trên Cloudflare thì tạo CNAME `certificate` → `datalize-certificate.pages.dev`. Cách này thay toàn bộ site mỗi lần deploy, nên chỉ deploy từ máy vừa chạy `issue.bat` (máy đó đã tải đủ cert của mọi trainer).

**Cách C: VPS/Nginx**
```nginx
server {
  server_name certificate.datalize.cloud;
  root /var/www/certificate/site;
  location / { try_files $uri $uri/ =404; }
  error_page 404 /404.html;
}
```
`rsync -av site/ user@server:/var/www/certificate/site/` (không dùng `--delete`), sau đó chạy `certbot --nginx -d certificate.datalize.cloud`.

## 10. Lưu ý khi làm việc chung
- **ID certificate không được đổi** sau khi đã gửi cho học viên, vì link và QR đã in trên cert.
- **Không chạy `issue.bat` cùng lúc trên 2 máy.** Nếu hai trainer cùng xử lý một dòng Ready, dòng đó có thể nhận hai ID khác nhau. Báo nhau trước khi chạy.
- Sheet là nguồn dữ liệu chung; `data/registry.json` chỉ là bản sao trên từng máy và được đồng bộ lại mỗi lần chạy `issue.bat`.
- Mọi thay đổi về nội dung/thiết kế: sửa `config.json` / `templates/` / `assets/` → `--rebuild` → kiểm tra theo checklist → commit cả nguồn lẫn `site/`.
- Repo nằm trong OneDrive: OneDrive có thể khoá thư mục trong lúc sync. `--rebuild` đã bỏ qua lỗi này và ghi đè lên file cũ. Nếu vẫn gặp lỗi quyền truy cập, tạm dừng OneDrive sync rồi chạy lại.
