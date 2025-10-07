from __future__ import annotations
import os
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_service():
    # ユーザーOAuth（tokens.jsonに保存）
    creds = None
    if os.path.exists("tokens.json"):
        creds = Credentials.from_authorized_user_file("tokens.json", SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("tokens.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def list_files_in_folder(svc, folder_id: str) -> List[Dict]:
    q = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken, files(id,name,mimeType,parents,createdTime,modifiedTime,md5Checksum)"
    files, page_token = [], None
    while True:
        resp = svc.files().list(q=q, fields=fields, pageToken=page_token).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

def ensure_subfolder(svc, parent_id: str, name: str) -> str:
    q = f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed=false"
    resp = svc.files().list(q=q, fields="files(id,name)").execute()
    if resp.get("files"):
        return resp["files"][0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = svc.files().create(body=meta, fields="id").execute()
    return folder["id"]

def move_and_rename(svc, file_id: str, new_parent: str, old_parents: List[str], new_name: Optional[str], dry_run: bool=True):
    if dry_run:
        return {"status": "DRY_RUN", "new_parent": new_parent, "new_name": new_name}
    # 親の付替え
    svc.files().update(fileId=file_id, addParents=new_parent, removeParents=",".join(old_parents) if old_parents else None, fields="id,parents").execute()
    # 名前変更
    if new_name:
        svc.files().update(fileId=file_id, body={"name": new_name}, fields="id,name").execute()
    return {"status": "OK"}
