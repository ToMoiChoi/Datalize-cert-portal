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
from urllib.parse import urlencode

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
    logo_src = data_uri(ROOT / CFG["issuer"]["logo"], "image/svg+xml")
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
def issue_from_csv(path):
    reg = load_registry()
    by_key = {key_of(c): c for c in reg["certificates"]}
    ids = {c["id"] for c in reg["certificates"]}
    new, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("name"):
                continue
            c = {
                "name": " ".join(row["name"].split()),
                "email": row.get("email", ""),
                "course": row.get("course", "").upper(),
                "type": (row.get("type") or "completion").lower(),
                "project": row.get("project", ""),
                "issue_date": row.get("issue_date") or date.today().isoformat(),
            }
            if c["course"] not in CFG["courses"]:
                errors.append(f"line {i}: unknown course '{c['course']}' (config.json → courses)"); continue
            if c["type"] not in CFG["types"]:
                errors.append(f"line {i}: type must be one of {list(CFG['types'])}"); continue
            try:
                datetime.strptime(c["issue_date"], "%Y-%m-%d")
            except ValueError:
                errors.append(f"line {i}: issue_date must be YYYY-MM-DD"); continue
            if key_of(c) in by_key:
                old = by_key[key_of(c)]
                changed = any(old.get(k) != c[k] for k in ("name", "project", "issue_date"))
                if changed:  # same person+course+type: keep ID, update details
                    old.update({k: c[k] for k in ("name", "project", "issue_date")})
                    new.append(old)
                continue
            c.update(id=new_id(ids), status="valid", created_at=datetime.now().isoformat(timespec="seconds"))
            ids.add(c["id"]); by_key[key_of(c)] = c
            reg["certificates"].append(c); new.append(c)
    if errors:
        print("Fix these rows first:\n  " + "\n  ".join(errors)); sys.exit(1)
    save_registry(reg)
    copy_assets(); render_static_pages()
    print(f"Rendering {len(new)} new/updated certificate(s)…")
    if new:
        render_certs(new)
    print(f"Links → {write_links(reg)}")


def rebuild():
    reg = load_registry()
    if SITE.exists():
        shutil.rmtree(SITE)
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Datalize certificate generator")
    ap.add_argument("csv", nargs="?", help="students CSV: name,email,course,type,project,issue_date")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--revoke", metavar="ID")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.revoke: revoke(a.revoke)
    elif a.rebuild: rebuild()
    elif a.list:
        for c in load_registry()["certificates"]:
            print(f"{c['id']}  {c['status']:<8} {c['type']:<13} {c['name']}")
    elif a.csv: issue_from_csv(a.csv)
    else: ap.print_help()
