from __future__ import annotations
from typing import Dict, List, Any, Tuple
from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

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
