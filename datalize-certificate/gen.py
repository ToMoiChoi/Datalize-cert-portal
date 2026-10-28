#!/usr/bin/env python3
"""
Datalize certificate generator.

  python gen.py data/students.csv      # issue certs for new rows, render them
  python gen.py --rebuild              # re-render every cert from the registry (after editing templates/config)
  python gen.py --revoke DLZ-XXXXXXXX  # mark a cert revoked and re-render it
  python gen.py --list                 # print all issued certs

Output: site/ (static, upload as-is), data/registry.json (private source of truth),
        data/issued_links.csv (name, email, link – to send to students).
"""
import argparse, base64, csv, io, json, re, secrets, shutil, sys, unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
DATA = ROOT / "data"
REGISTRY = DATA / "registry.json"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))


# ---------- registry ----------
def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {"certificates": []}


def save_registry(reg):
    DATA.mkdir(exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def new_id(existing):
    while True:
        cid = f"{CFG['id_prefix']}-" + "".join(secrets.choice(ALPHABET) for _ in range(8))
        if cid not in existing:
            return cid


def key_of(c):
    who = (c.get("email") or c["name"]).strip().lower()
    return f"{who}|{c['course']}|{c['type']}"


# ---------- helpers ----------
def slug(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


def long_date(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")


def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def qr_data_uri(url):
    qr = qrcode.QRCode(border=0, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="#0B1F3A", back_color="white").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def name_size(name):
    n = len(name)
    return 60 if n <= 20 else 54 if n <= 26 else 46 if n <= 32 else 40


def context(c):
    course = CFG["courses"][c["course"]]
    ctype = CFG["types"][c["type"]]
    base = CFG["base_url"].rstrip("/")
    cert_url = f"{base}/{c['id']}/"
    d = datetime.strptime(c["issue_date"], "%Y-%m-%d")
    li = {
        "startTask": "CERTIFICATION_NAME",
        "name": f"{course['name']}" + ("" if c["type"] == "completion" else " (Participation)"),
        "issueYear": d.year, "issueMonth": d.month,
        "certUrl": cert_url, "certId": c["id"],
    }
    org_id = CFG["issuer"].get("linkedin_org_id")
    li.update({"organizationId": org_id} if org_id else {"organizationName": CFG["issuer"]["name"]})
    jsonld = {
        "@context": "https://schema.org", "@type": "EducationalOccupationalCredential",
        "name": f"{ctype['title']} – {course['name']}", "credentialCategory": "certificate",
        "identifier": c["id"], "url": cert_url, "dateCreated": c["issue_date"],
        "recognizedBy": {"@type": "Organization", "name": CFG["issuer"]["name"], "url": CFG["issuer"]["website"]},
        "about": {"@type": "Course", "name": course["name"]},
    }
    return dict(
        cert=c, course=course, ctype=ctype, issuer=CFG["issuer"], signers=CFG["signers"],
        cert_url=cert_url, short_url=cert_url.replace("https://", "").rstrip("/"),
        issue_date_long=long_date(c["issue_date"]), issue_year=d.year,
        name_size=name_size(c["name"]),
        linkedin_add_url="https://www.linkedin.com/profile/add?" + urlencode(li),
        file_stem=f"{slug(CFG['issuer']['name'])}-{c['type']}-{slug(c['name'])}",
        jsonld=json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/"),
    )


# ---------- rendering ----------
def copy_assets():
    SITE.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "assets", SITE / "assets", dirs_exist_ok=True)


def render_static_pages():
    year = date.today().year
    common = dict(issuer=CFG["issuer"], id_prefix=CFG["id_prefix"], year=year)
    (SITE / "index.html").write_text(env.get_template("index.html").render(
        root="", title="Verify a certificate", robots="index,follow",
        message=f"Enter the certificate ID printed on any {CFG['issuer']['name']} certificate.", **common), encoding="utf-8")
    (SITE / "404.html").write_text(env.get_template("index.html").render(
        root="/", title="Certificate not found", robots="noindex",
        message="We couldn't find a certificate with that ID. Check the ID and try again.", **common), encoding="utf-8")
    (SITE / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    # Hostinger shared hosting (LiteSpeed/Apache): 404 page, HTTPS, caching
    (SITE / ".htaccess").write_text(
        "ErrorDocument 404 /404.html\nDirectoryIndex index.html\nOptions -Indexes\n"
        "RewriteEngine On\nRewriteCond %{HTTPS} off\nRewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]\n"
        "<IfModule mod_expires.c>\nExpiresActive On\nExpiresByType image/png \"access plus 30 days\"\n"
        "ExpiresByType font/woff2 \"access plus 1 year\"\n</IfModule>\n", encoding="utf-8")


def render_certs(certs):
    from playwright.sync_api import sync_playwright
    logo_src = data_uri(ROOT / CFG["issuer"]["logo"], "image/svg+xml" if CFG["issuer"]["logo"].endswith(".svg") else "image/png")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1123, "height": 794}, device_scale_factor=2)
        for c in certs:
            out = SITE / c["id"]
            out.mkdir(parents=True, exist_ok=True)
            ctx = context(c)
            tmp = out / "_render.html"
            tmp.write_text(env.get_template("certificate.html").render(
                root="../", logo_src=logo_src, qr_src=qr_data_uri(ctx["cert_url"]), **ctx), encoding="utf-8")
            page.goto(tmp.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            page.screenshot(path=str(out / "certificate.png"), clip={"x": 0, "y": 0, "width": 1123, "height": 794})
            page.pdf(path=str(out / "certificate.pdf"), width="297mm", height="210mm", print_background=True,
                     margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            tmp.unlink()
            make_og(out / "certificate.png", out / "og.jpg")
            (out / "index.html").write_text(env.get_template("page.html").render(**ctx), encoding="utf-8")
            print(f"  ✓ {c['id']}  {c['name']}  ({c['type']})")
        browser.close()


def make_og(png, jpg):
    """1200x630 social preview: certificate centred on brand navy."""
    bg = Image.new("RGB", (1200, 630), "#0B1F3A")
    cert = Image.open(png).convert("RGB")
    h = 570
    cert = cert.resize((round(cert.width * h / cert.height), h), Image.LANCZOS)
    bg.paste(cert, ((1200 - cert.width) // 2, 30))
    bg.save(jpg, quality=88, optimize=True)


def write_links(reg):
    path = DATA / "issued_links.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "email", "course", "type", "issue_date", "status", "url"])
        for c in reg["certificates"]:
            w.writerow([c["id"], c["name"], c.get("email", ""), c["course"], c["type"], c["issue_date"],
                        c["status"], f"{CFG['base_url'].rstrip('/')}/{c['id']}/"])
    return path


# ---------- commands ----------
FIELDS = ("name", "email", "course", "type", "project", "issue_date", "organization")


def cert_url(cid):
    return f"{CFG['base_url'].rstrip('/')}/{cid}/"


def parse_row(row):
    """Normalise one input row (CSV line or Sheet row). Returns (cert, error); cert is None for blank rows."""
    row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
    if not row.get("name"):
        return None, None
    c = {
        "name": " ".join(row["name"].split()),
        "email": row.get("email", ""),
        "course": row.get("course", "").upper(),
        "type": (row.get("type") or "completion").lower(),
        "project": row.get("project", ""),
        "issue_date": row.get("issue_date") or date.today().isoformat(),
        "organization": row.get("organization", ""),
    }
    if c["course"] not in CFG["courses"]:
        return c, f"unknown course '{c['course']}' (config.json → courses)"
    if c["type"] not in CFG["types"]:
        return c, f"type must be one of {list(CFG['types'])}"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            c["issue_date"] = datetime.strptime(c["issue_date"], fmt).date().isoformat()
            return c, None
        except ValueError:
            pass
    return c, "issue_date must be YYYY-MM-DD"


def upsert(reg, c, cid=None):
    """Add a cert, or update the one with this ID (or, without an ID, the same person+course+type).
    Returns (cert, changed)."""
    certs = reg["certificates"]
    if cid:
        old = next((x for x in certs if x["id"] == cid), None)
    else:
        old = next((x for x in certs if key_of(x) == key_of(c)), None)
    if old:
        changed = any(old.get(k, "") != c.get(k, "") for k in FIELDS)
        old.update({k: c[k] for k in FIELDS})
        return old, changed
    c.update(id=cid or new_id({x["id"] for x in certs}), status="valid",
             created_at=datetime.now().isoformat(timespec="seconds"))
    certs.append(c)
    return c, True


def publish(reg, todo):
    save_registry(reg)
    copy_assets(); render_static_pages()
    todo = list({c["id"]: c for c in todo}.values())
    print(f"Rendering {len(todo)} new/updated certificate(s)…")
    if todo:
        render_certs(todo)
    print(f"Links → {write_links(reg)}")


def issue_from_csv(path):
    reg = load_registry()
    todo, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            c, err = parse_row(row)
            if err:
                errors.append(f"line {i}: {err}")
            elif c:
                cert, changed = upsert(reg, c)  # same person+course+type keeps its ID
                if changed:
                    todo.append(cert)
    if errors:
        print("Fix these rows first:\n  " + "\n  ".join(errors)); sys.exit(1)
    publish(reg, todo)


# ---------- Google Sheet ----------
# The shared Sheet is the source of truth when several trainers issue certs: rows marked Ready get issued,
# and rows already Issued/Revoked (possibly by another trainer) are pulled into the local registry and site/.
class SheetTab:
    """Minimal Google Sheets client: service-account JWT signed with pure-Python `rsa` + REST calls.
    Avoids gspread/cryptography, whose DLLs Windows Smart App Control can block."""
    API = "https://sheets.googleapis.com/v4/spreadsheets/"

    def __init__(self, creds_path, spreadsheet_id, tab):
        self.sid, self.tab = spreadsheet_id, tab
        self.token = self._token(json.loads(Path(creds_path).read_text(encoding="utf-8")))
        meta = self._call("GET", f"{self.sid}?fields=sheets.properties")
        hit = [s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == tab]
        if not hit:
            sys.exit(f"Sheet has no tab named '{tab}'")
        self.id = hit[0]

    @staticmethod
    def _token(info):
        import time, rsa
        from pyasn1.codec.der import decoder
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
        now = int(time.time())
        claim = {"iss": info["client_email"], "scope": "https://www.googleapis.com/auth/spreadsheets",
                 "aud": info["token_uri"], "iat": now, "exp": now + 3600}
        msg = b64(b'{"alg":"RS256","typ":"JWT"}') + b"." + b64(json.dumps(claim).encode())
        pem = info["private_key"].split("-----")[2]  # PKCS#8 body
        pkcs1 = bytes(decoder.decode(base64.b64decode(pem))[0][2])
        jwt = msg + b"." + b64(rsa.sign(msg, rsa.PrivateKey.load_pkcs1(pkcs1, "DER"), "SHA-256"))
        body = urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
        with urlopen(Request(info["token_uri"], body), timeout=30) as r:
            return json.load(r)["access_token"]

    def _call(self, method, path, body=None):
        req = Request(self.API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=60) as r:
                return json.load(r)
        except HTTPError as e:
            sys.exit(f"Google Sheets API error {e.code}: {e.read().decode(errors='replace')[:400]}")

    def _a1(self, rng):
        return quote(f"'{self.tab}'!{rng}", safe="")

    def values(self):
        return self._call("GET", f"{self.sid}/values/{self._a1('A:Z')}").get("values", [])

    def write(self, cells):
        """cells: [(row, col_index0, value)] written as if typed in the UI (dates become dates)."""
        data = [{"range": f"'{self.tab}'!{col_letter(c)}{r}", "values": [[v]]} for r, c, v in cells]
        self._call("POST", f"{self.sid}/values:batchUpdate", {"valueInputOption": "USER_ENTERED", "data": data})

    def batch(self, requests):
        self._call("POST", f"{self.sid}:batchUpdate", {"requests": requests})


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def open_sheet():
    s = CFG.get("sheet") or {}
    creds = ROOT / s.get("credentials", "data/service-account.json")
    if not s.get("id"):
        sys.exit("config.json → sheet.id is empty (see README → Google Sheet)")
    if not creds.exists():
        sys.exit(f"Missing {creds.relative_to(ROOT)} (see README → Google Sheet)")
    return SheetTab(creds, s["id"], s.get("tab", "Students"))


def issue_from_sheet(sheet=None):
    sheet = sheet or open_sheet()
    rows = sheet.values()
    head = [h.strip().lower() for h in rows[0]] if rows else []
    missing = [h for h in ("name", "status", "cert_id", "cert_link", "issued_at", "note") if h not in head]
    if missing:
        sys.exit(f"Sheet is missing columns: {missing}")
    records = [(n, dict(zip(head, r + [""] * (len(head) - len(r))))) for n, r in enumerate(rows[1:], start=2)]
    cells, errors = [], 0

    def put(n, col, value):
        cells.append((n, head.index(col), value))

    reg = load_registry()
    todo = []

    # 1) certs already issued, by anyone: make sure they exist in the local registry and site/
    for n, row in records:
        status, cid = row["status"].strip().lower(), row["cert_id"].strip().upper()
        if status not in ("issued", "revoked") or not cid:
            continue
        c, err = parse_row(row)
        if err or not c:
            print(f"  ! row {n} ({cid}): {err or 'no name'}"); continue
        cert, changed = upsert(reg, c, cid)
        want = "revoked" if status == "revoked" else "valid"
        if cert["status"] != want:
            cert["status"], changed = want, True
        if changed or not (SITE / cid / "certificate.png").exists():
            todo.append(cert)

    # 2) rows marked Ready: issue (or re-render under the same ID if the row already has one)
    done = []
    for n, row in records:
        if row["status"].strip().lower() != "ready":
            continue
        c, err = parse_row(row)
        if not c:
            continue
        if err:
            errors += 1
            put(n, "note", f"Lỗi: {err}"); print(f"  ! row {n}: {err}"); continue
        cert, _ = upsert(reg, c, row["cert_id"].strip().upper() or None)
        cert["status"] = "valid"
        todo.append(cert); done.append((n, row, cert))

    publish(reg, todo)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for n, row, cert in done:  # write back only after rendering succeeded
        put(n, "cert_id", cert["id"]); put(n, "cert_link", cert_url(cert["id"]))
        put(n, "issued_at", stamp); put(n, "status", "Issued")
        if "issue_date" in head and not row["issue_date"].strip():
            put(n, "issue_date", cert["issue_date"])
        if row["note"].startswith("Lỗi"):
            put(n, "note", "")
    if cells:
        sheet.write(cells)
    if "course" in head:
        sync_course_dropdown(sheet, head.index("course"))
    print(f"Sheet: {len(done)} issued, {len(todo) - len(done)} synced from other trainers/edits, {errors} row(s) with errors")


def sync_course_dropdown(sheet, col):
    """Keep the Sheet's course dropdown in line with config.json → courses."""
    sheet.batch([{"setDataValidation": {
        "range": {"sheetId": sheet.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": k} for k in CFG["courses"]]},
                 "strict": True, "showCustomUi": True,
                 "inputMessage": "Mã khoá trong config.json. Tool tự cập nhật danh sách này mỗi lần chạy."}}}])


def mark_revoked_in_sheet(cid):
    if not (CFG.get("sheet") or {}).get("id"):
        return
    try:
        sheet = open_sheet()
        rows = sheet.values()
        head = [h.strip().lower() for h in rows[0]]
        i_id, i_status = head.index("cert_id"), head.index("status")
        hits = [n for n, r in enumerate(rows[1:], start=2) if len(r) > i_id and r[i_id].strip().upper() == cid]
        if hits:
            sheet.write([(n, i_status, "Revoked") for n in hits])
            print(f"Sheet: row(s) {hits} → Revoked")
    except (SystemExit, Exception) as e:  # revoking locally must not fail because the Sheet is unreachable
        print(f"  ! could not update the Sheet: {e}")


def rebuild():
    reg = load_registry()
    if SITE.exists():
        shutil.rmtree(SITE, ignore_errors=True)  # OneDrive/Explorer may lock empty folders; leftovers are overwritten below
    copy_assets(); render_static_pages()
    print(f"Rebuilding {len(reg['certificates'])} certificate(s)…")
    render_certs(reg["certificates"])
    print(f"Links → {write_links(reg)}")


def revoke(cid):
    reg = load_registry()
    hit = [c for c in reg["certificates"] if c["id"] == cid.upper()]
    if not hit:
        print("No such ID"); sys.exit(1)
    hit[0]["status"] = "revoked"
    save_registry(reg); copy_assets(); render_certs(hit); write_links(reg)
    mark_revoked_in_sheet(hit[0]["id"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Vietnamese names in a Windows console
    ap = argparse.ArgumentParser(description="Datalize certificate generator")
    ap.add_argument("csv", nargs="?", help="students CSV: name,email,course,type,project,issue_date")
    ap.add_argument("--sheet", action="store_true", help="issue rows marked Ready in the shared Google Sheet")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--revoke", metavar="ID")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.revoke: revoke(a.revoke)
    elif a.sheet: issue_from_sheet()
    elif a.rebuild: rebuild()
    elif a.list:
        for c in load_registry()["certificates"]:
            print(f"{c['id']}  {c['status']:<8} {c['type']:<13} {c['name']}")
    elif a.csv: issue_from_csv(a.csv)
    else: ap.print_help()
