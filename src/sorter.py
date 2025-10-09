from __future__ import annotations
from typing import Dict, List, Any, Tuple, Optional
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

# 追加 import
import os, io, json, re
from googleapiclient.http import MediaIoBaseDownload
from .ai_classifier import classify_with_ai
from .extractors.pdf import extract_text_from_pdf_bytes
from .extractors.image import extract_text_from_image_bytes
from .extractors.excel import extract_text_from_xlsx

CACHE_PATH = "/var/lib/das/classify-cache.json"
os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)

def _load_cache() -> Dict[str, str]:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(data: Dict[str, str]):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)

# 既存関数群

def list_subfolders(service: Resource, parent_id: str) -> List[Dict[str, Any]]:
    q = (
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    files: List[Dict[str, Any]] = []
    page_token = None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id,name)", pageToken=page_token
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

def list_files_directly_under(service: Resource, parent_id: str) -> List[Dict[str, Any]]:
    q = (
        f"'{parent_id}' in parents and "
        "mimeType != 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    files: List[Dict[str, Any]] = []
    page_token = None
    while True:
        resp = service.files().list(
            q=q, fields="nextPageToken, files(id,name,parents,mimeType)", pageToken=page_token
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

def move_file(service: Resource, file_id: str, dest_folder_id: str) -> Dict[str, Any]:
    meta = service.files().get(fileId=file_id, fields="parents,name").execute()
    prev_parents = ",".join(meta.get("parents", [])) if meta.get("parents") else None
    return service.files().update(
        fileId=file_id,
        addParents=dest_folder_id,
        removeParents=prev_parents,
        fields="id,name,parents"
    ).execute()

def sort_files_by_subfolder_name(service: Resource, parent_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    subfolders = list_subfolders(service, parent_id)
    files = list_files_directly_under(service, parent_id)

    sub_by_name: Dict[str, Dict[str, str]] = {
        s["name"].lower(): {"id": s["id"], "name": s["name"]} for s in subfolders
    }

    moved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for f in files:
        fname = f.get("name", "")
        fid = f.get("id")
        low = fname.lower()

        dest = None
        for sub_name, sub in sub_by_name.items():
            if sub_name and sub_name in low:
                dest = sub
                break

        if not dest:
            skipped.append({"file_id": fid, "name": fname, "reason": "no_subfolder_name_match"})
            continue

        try:
            res = move_file(service, file_id=fid, dest_folder_id=dest["id"])
            moved.append({"file_id": res.get("id", fid), "name": res.get("name", fname), "to_folder": dest["name"]})
        except HttpError as e:
            skipped.append({"file_id": fid, "name": fname, "reason": f"move_failed: {e}"})

    return moved, skipped

# ---- AI OCR + 分類 ----

_DEF_TEXT_MAX = 500
_DEF_MAX_FILES = 100
_DEF_MAX_BYTES = 20 * 1024 * 1024  # 20MB

_norm_rx = re.compile(r"\s+")

def _norm(s: str) -> str:
    return _norm_rx.sub("", s).lower()

_DEF_PLAIN_EXTS = {".txt", ".csv", ".md"}


def _download_bytes(service: Resource, file_id: str) -> bytes:
    buf = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return buf.getvalue()


def _extract_text(name: str, mime: str, data: bytes) -> str:
    nl = name.lower()
    try:
        if mime == "application/pdf" or nl.endswith(".pdf"):
            return extract_text_from_pdf_bytes(data)
        if mime.startswith("image/") or any(nl.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".heic")):
            return extract_text_from_image_bytes(data)
        if nl.endswith(".xlsx") or mime in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",):
            return extract_text_from_xlsx(data)
        if any(nl.endswith(ext) for ext in _DEF_PLAIN_EXTS):
            # プレーンテキストとして先頭だけ
            return data.decode(errors="ignore")
    except Exception:
        return ""
    return ""


def ai_sort_files(service: Resource, parent_id: str, *, text_max: int=_DEF_TEXT_MAX, max_files: int=_DEF_MAX_FILES, max_bytes: int=_DEF_MAX_BYTES) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    - 親直下の子フォルダ名をカテゴリとして採用
    - 親直下のファイルを順に: ダウンロード→OCR/抽出→AI分類→カテゴリ名と一致する子フォルダへ移動
    - マッチしなければ skipped
    - コスト制御: 件数上限、サイズ上限、テキスト長上限、結果キャッシュ(md5)
    """
    subfolders = list_subfolders(service, parent_id)
    files = list_files_directly_under(service, parent_id)

    # 子フォルダの正規化辞書
    sub_by_norm: Dict[str, Dict[str, str]] = {}
    for s in subfolders:
        sub_by_norm[_norm(s["name"])] = {"id": s["id"], "name": s["name"]}

    cache = _load_cache()

    moved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    processed = 0
    for f in files:
        if processed >= max_files:
            break
        fid = f.get("id")
        fname = f.get("name", "")
        mime = f.get("mimeType", "")

        # 追加メタ: size, md5
        meta = service.files().get(fileId=fid, fields="size,md5Checksum").execute()
        md5 = meta.get("md5Checksum")
        size = int(meta.get("size", 0)) if meta.get("size") else 0
        if size and size > max_bytes:
            skipped.append({"file_id": fid, "name": fname, "reason": f"too_large:{size}"})
            continue

        # キャッシュ判定
        cat: Optional[str] = cache.get(md5) if md5 else None
        text = ""
        if not cat:
            try:
                data = _download_bytes(service, fid)
            except Exception as e:
                skipped.append({"file_id": fid, "name": fname, "reason": f"download_failed:{e}"})
                continue
            text = _extract_text(fname, mime, data)[:text_max]
            try:
                cat = classify_with_ai(fname, text) if text else None
            except Exception as e:
                skipped.append({"file_id": fid, "name": fname, "reason": f"ai_failed:{e}"})
                continue
            if md5 and cat:
                cache[md5] = cat

        # マッチング（正規化して完全一致、なければ部分一致）
        norm_cat = _norm(cat or "")
        dest = None
        if norm_cat in sub_by_norm:
            dest = sub_by_norm[norm_cat]
        else:
            for sub_norm, sub in sub_by_norm.items():
                if sub_norm and (sub_norm in norm_cat or norm_cat in sub_norm):
                    dest = sub
                    break

        if not dest:
            skipped.append({"file_id": fid, "name": fname, "reason": f"no_match:{cat}"})
            continue

        try:
            res = move_file(service, file_id=fid, dest_folder_id=dest["id"])
            moved.append({
                "file_id": res.get("id", fid),
                "name": res.get("name", fname),
                "to_folder": dest["name"],
                "category": cat,
            })
            processed += 1
        except HttpError as e:
            skipped.append({"file_id": fid, "name": fname, "reason": f"move_failed:{e}"})

    _save_cache(cache)
    return moved, skipped
