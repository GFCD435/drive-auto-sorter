import os
import re
import argparse
from datetime import datetime
from dotenv import load_dotenv
from src import gdrive

CATS = [
    ("invoice",   re.compile(r"請求|invoice", re.I)),
    ("receipt",   re.compile(r"領収|receipt", re.I)),
    ("contract",  re.compile(r"契約|contract", re.I)),
    ("spreadsheet", re.compile(r"\.(xlsx|xls|csv)$", re.I)),
    ("photo",     re.compile(r"\.(jpg|jpeg|png|heic|webp)$", re.I)),
]

def guess_category(name: str, mime: str) -> str:
    for cat, rx in CATS:
        if rx.search(name):
            return cat
    if mime.startswith("image/"):
        return "photo"
    if mime == "application/pdf":
        return "pdf"
    if "spreadsheet" in mime or mime.endswith("excel"):
        return "spreadsheet"
    return "misc"

def make_new_name(orig: str, category: str) -> str:
    base, ext = (orig.rsplit(".",1)+[""])[:2]
    ext = "."+ext.lower() if ext else ""
    date = datetime.now().strftime("%Y%m%d")
    base = re.sub(r"\s+", "_", base)[:30]
    return f"{category}_{date}_{base}{ext}"

def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="対象の親フォルダID（Google Drive）")
    ap.add_argument("--dry-run", action="store_true", default=os.getenv("DRY_RUN","true").lower()=="true")
    args = ap.parse_args()

    svc = gdrive.get_service()
    files = gdrive.list_files_in_folder(svc, args.root)
    print(f"Found {len(files)} items")

    for f in files:
        if f["mimeType"] == "application/vnd.google-apps.folder":
            continue
        name, mime = f["name"], f["mimeType"]
        cat = guess_category(name, mime)
        sub_id = gdrive.ensure_subfolder(svc, args.root, cat)
        new_name = make_new_name(name, cat)
        parents = f.get("parents", [])
        res = gdrive.move_and_rename(svc, f["id"], sub_id, parents, new_name, dry_run=args.dry_run)
        print(f"[{res['status']}] {name} -> {cat}/{new_name}")

if __name__ == "__main__":
    main()
