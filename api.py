from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["api"])

@router.get("/token")
def token(request: Request):
    # ここではとりあえず「ログインできた」と返す（必要なら Cookie の検査に差し替え）
    return {"ok": True}

class SortBody(BaseModel):
    parent_id: str

@router.post("/sort")
def sort_files(body: SortBody, request: Request):
    # あとで Google Drive の実処理に置き換える
    return {"status": "ok", "received_parent_id": body.parent_id, "moved": 0}
