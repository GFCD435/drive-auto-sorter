from __future__ import annotations
from typing import Dict, List, Any, Tuple, Optional
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

# 追加 import
import os, io, json, re
from difflib import SequenceMatcher
from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import]
from .ai_classifier import classify_with_ai, classify_title_with_ai
from .extractors.pdf import extract_text_from_pdf_bytes
from .extractors.image import extract_text_from_image_bytes
from .extractors.excel import extract_text_from_xlsx
from .category_rules import load_category_profiles  # type: ignore[import]

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

_DEF_TEXT_MAX = 2000
_DEF_MAX_FILES = 100
_DEF_MAX_BYTES = 20 * 1024 * 1024  # 20MB

_norm_rx = re.compile(r"\s+")

def _norm(s: str) -> str:
    return _norm_rx.sub("", s).lower()

_DEF_PLAIN_EXTS = {".txt", ".csv", ".md"}


def _rule_score(subject: str, profile: Dict[str, Any]) -> float:
    subject_norm = _norm(subject)
    if not subject_norm:
        return 0.0

    excludes = profile.get("exclude") or []
    for word in excludes:
        if not word:
            continue
        if _norm(word) and _norm(word) in subject_norm:
            return -1.0

    includes = profile.get("include") or []
    score = 0.0
    for word in includes:
        if not word:
            continue
        word_norm = _norm(word)
        if word_norm and word_norm in subject_norm:
            score += 1.0

    if score > 0:
        return score

    name_norm = _norm(profile.get("name", ""))
    if name_norm and name_norm in subject_norm:
        return 0.5
    return 0.0


def _best_profile_by_rules(subject: str, profiles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    best_profile: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for profile in profiles:
        score = _rule_score(subject, profile)
        if score < 0:
            continue
        if score > best_score:
            best_profile = profile
            best_score = score
    return best_profile if best_score > 0 else None


def _best_profile_by_similarity(title: str, profiles: List[Dict[str, Any]], threshold: float = 0.82) -> Optional[Dict[str, Any]]:
    title_lower = title.lower()
    best_profile: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for profile in profiles:
        ratio = SequenceMatcher(None, title_lower, profile.get("name", "").lower()).ratio()
        if ratio > best_score:
            best_profile = profile
            best_score = ratio
    if best_score >= threshold:
        return best_profile
    return None


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
    - まずファイルタイトルだけで子フォルダ名と照合し、判定できれば即移動
    - タイトルで判定できない場合にのみ: ダウンロード→OCR/抽出→AI分類→カテゴリ名と一致する子フォルダへ移動
    - マッチしなければ skipped
    - コスト制御: 件数上限、サイズ上限、テキスト長上限、結果キャッシュ(md5)
    """
    subfolders = list_subfolders(service, parent_id)
    files = list_files_directly_under(service, parent_id)

    # カテゴリプロファイルをロード
    profiles_by_name = load_category_profiles()

    # 子フォルダの正規化辞書とタイトル照合用辞書
    sub_by_norm: Dict[str, Dict[str, Any]] = {}
    sub_by_lower: Dict[str, Dict[str, Any]] = {}
    folder_profiles: List[Dict[str, Any]] = []
    for s in subfolders:
        base_profile = profiles_by_name.get(s["name"], {})
        folder_profile = {
            "id": s["id"],
            "name": s["name"],
            "description": base_profile.get("description", ""),
            "include": base_profile.get("include", []),
            "exclude": base_profile.get("exclude", []),
        }
        folder_profiles.append(folder_profile)
        sub_by_norm[_norm(s["name"])] = folder_profile
        sub_by_lower[s["name"].lower()] = folder_profile

    cache = _load_cache()

    moved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    ai_calls = 0
    for f in files:
        fid = f.get("id")
        fname = f.get("name", "")
        mime = f.get("mimeType", "")

        dest_profile: Optional[Dict[str, Any]] = None
        method = ""
        cat_method = ""

        rule_profile = _best_profile_by_rules(fname, folder_profiles)
        if rule_profile:
            dest_profile = rule_profile
            method = "title_rule"

        title_norm = _norm(fname)
        title_lower = fname.lower()
        if not dest_profile:
            for sub_norm, sub in sub_by_norm.items():
                if sub_norm and sub_norm in title_norm:
                    dest_profile = sub
                    method = "title_substring"
                    break
        if not dest_profile:
            for sub_lower, sub in sub_by_lower.items():
                if sub_lower and sub_lower in title_lower:
                    dest_profile = sub
                    method = "title_substring"
                    break

        if not dest_profile:
            similar_profile = _best_profile_by_similarity(fname, folder_profiles)
            if similar_profile:
                dest_profile = similar_profile
                method = "title_similarity"

        if dest_profile:
            try:
                res = move_file(service, file_id=fid, dest_folder_id=dest_profile["id"])
                moved.append({
                    "file_id": res.get("id", fid),
                    "name": res.get("name", fname),
                    "to_folder": dest_profile["name"],
                    "category": dest_profile["name"],
                    "method": method or "title",
                })
                continue
            except HttpError as e:
                skipped.append({"file_id": fid, "name": fname, "reason": f"move_failed:{e}"})
                continue

        # タイトルだけでは決められない場合、GPTで近似カテゴリを確認
        if folder_profiles:
            if ai_calls >= max_files:
                skipped.append({"file_id": fid, "name": fname, "reason": "ai_limit_reached"})
                continue
            try:
                title_guess = classify_title_with_ai(fname, folder_profiles)
                ai_calls += 1
            except Exception as e:
                skipped.append({"file_id": fid, "name": fname, "reason": f"title_ai_failed:{e}"})
                continue
            if title_guess and title_guess.upper() != "NONE":
                norm_guess = _norm(title_guess)
                dest = sub_by_norm.get(norm_guess)
                if not dest:
                    for sub_norm, sub in sub_by_norm.items():
                        if sub_norm and (sub_norm in norm_guess or norm_guess in sub_norm):
                            dest = sub
                            break
                if dest:
                    try:
                        res = move_file(service, file_id=fid, dest_folder_id=dest["id"])
                        moved.append({
                            "file_id": res.get("id", fid),
                            "name": res.get("name", fname),
                            "to_folder": dest["name"],
                            "category": dest["name"],
                            "method": "title_ai",
                            "ai_label": title_guess,
                        })
                        continue
                    except HttpError as e:
                        skipped.append({"file_id": fid, "name": fname, "reason": f"move_failed:{e}"})
                        continue

        # 追加メタ: size, md5
        meta = service.files().get(fileId=fid, fields="size,md5Checksum").execute()
        md5 = meta.get("md5Checksum")
        size = int(meta.get("size", 0)) if meta.get("size") else 0
        if size and size > max_bytes:
            skipped.append({"file_id": fid, "name": fname, "reason": f"too_large:{size}"})
            continue

        # キャッシュ判定
        cat: Optional[str] = cache.get(md5) if md5 else None
        if cat and not cat_method:
            cat_method = "cache"
        text = ""
        if not cat:
            if ai_calls >= max_files:
                skipped.append({"file_id": fid, "name": fname, "reason": "ai_limit_reached"})
                continue
            try:
                data = _download_bytes(service, fid)
            except Exception as e:
                skipped.append({"file_id": fid, "name": fname, "reason": f"download_failed:{e}"})
                continue
            text = _extract_text(fname, mime, data)[:text_max]
            if text:
                text_profile = _best_profile_by_rules(text, folder_profiles)
                if text_profile:
                    cat = text_profile["name"]
                    cat_method = "content_rule"
                else:
                    try:
                        cat = classify_with_ai(fname, text, folder_profiles)
                        ai_calls += 1
                        cat_method = "content_ai"
                    except Exception as e:
                        skipped.append({"file_id": fid, "name": fname, "reason": f"ai_failed:{e}"})
                        continue
            if md5 and cat and cat.upper() != "NONE":
                cache[md5] = cat

        if cat and cat.upper() == "NONE":
            skipped.append({"file_id": fid, "name": fname, "reason": "ai_returned_none"})
            continue

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
            entry = {
                "file_id": res.get("id", fid),
                "name": res.get("name", fname),
                "to_folder": dest["name"],
                "category": cat,
                "method": cat_method or "content",
            }
            if cat_method in {"content_ai", "cache"}:
                entry["ai_label"] = cat
            moved.append(entry)
        except HttpError as e:
            skipped.append({"file_id": fid, "name": fname, "reason": f"move_failed:{e}"})

    _save_cache(cache)
    return moved, skipped
