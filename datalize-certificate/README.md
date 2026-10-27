# Datalize Certificate Generator

Static certificate site for `https://certificate.datalize.cloud/<ID>/`, similar to Udemy certificates.
Each certificate gets its own page with the PNG, the PDF, an **Add to LinkedIn profile** button, share buttons and a QR code for verification.

## Cài đặt (1 lần)
```bash
pip install jinja2 qrcode pillow playwright
playwright install chromium
```

## Dùng
1. Sửa `config.json`: tên khoá, số giờ/buổi, skills, **tên + chức danh người ký** (có thể thêm ảnh chữ ký PNG nền trong suốt vào `signature_image`, ví dụ `assets/signature.png`), `linkedin_org_id` nếu Datalize có LinkedIn Page (khi đó LinkedIn hiện đúng logo công ty).
2. Điền `data/students.csv`:

| cột | ghi chú |
|---|---|
| name | tên đầy đủ, có dấu được |
| email | để chống trùng; **không** được xuất ra site |
| course | mã khoá trong `config.json` (vd `PBI`) |
| type | `completion` (làm xong final project) hoặc `participation` (chỉ tham gia) |
| project | tên dự án final, bỏ trống nếu là participation |
| issue_date | `YYYY-MM-DD`, bỏ trống = hôm nay |

3. Chạy:
```bash
python gen.py data/students.csv     # cấp cert mới cho dòng mới, render
python gen.py --rebuild             # render lại toàn bộ sau khi sửa template/config
python gen.py --revoke DLZ-XXXXXXXX # thu hồi cert (trang hiện REVOKED)
python gen.py --list
```
Chạy lại cùng CSV thì không bị trùng: cùng email + khoá + loại giữ nguyên ID (nếu sửa tên/dự án thì chỉ cập nhật).
Link gửi học viên nằm ở `data/issued_links.csv`.

`data/registry.json` là nguồn dữ liệu gốc (có email). **Hãy backup file này và đừng upload nó lên site**; chỉ upload thư mục `site/`.

## Deploy lên certificate.datalize.cloud

**Cách A: Cloudflare Pages (miễn phí, khuyên dùng)**
```bash
npx wrangler pages deploy site --project-name datalize-certificate
```
Sau đó vào Cloudflare → Pages → datalize-certificate → Custom domains → thêm `certificate.datalize.cloud`. Nếu DNS của datalize.cloud nằm trên Cloudflare thì nó tự tạo CNAME; nếu không thì tạo CNAME `certificate` → `datalize-certificate.pages.dev`.
`404.html` được dùng tự động khi ID không tồn tại.

**Cách B: VPS/Nginx**
```nginx
server {
  server_name certificate.datalize.cloud;
  root /var/www/certificate/site;
  location / { try_files $uri $uri/ =404; }
  error_page 404 /404.html;
}
```
Copy lên server: `rsync -av --delete site/ user@server:/var/www/certificate/site/`, sau đó chạy `certbot --nginx -d certificate.datalize.cloud`.

## Cấu trúc
```
config.json            issuer, courses, signer, loại cert
data/students.csv      input
data/registry.json     danh sách cert đã cấp (private)
templates/             certificate.html (mẫu cert A4 ngang), page.html (trang public), index.html (trang tra cứu / 404)
assets/                logo, favicon, font (Vietnamese subsets), site.css
site/                  output, upload nguyên thư mục này
  index.html           tra cứu theo ID
  <ID>/index.html      trang certificate
  <ID>/certificate.png|pdf, og.jpg (ảnh preview khi share)
```
Muốn đổi logo thì thay `assets/logo.svg` (nền trong suốt; ở panel tối logo được tự đổi sang màu trắng).
