from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

from src import session
from src import sorter

router = APIRouter(tags=["api"])

COOKIE_NAME = "das_state"


def _get_creds_from_request(request: Request) -> Credentials:
    state = request.cookies.get(COOKIE_NAME)
    if not state:
        raise HTTPException(status_code=401, detail="missing auth cookie")
    creds_json = session.creds_load(state)
    if not creds_json:
        raise HTTPException(status_code=401, detail="not authorized")
    return Credentials.from_authorized_user_info(json.loads(creds_json))


@router.get("/token")
def token(request: Request) -> Dict[str, Any]:
    _ = _get_creds_from_request(request)
    return {"ok": True}


class SortBody(BaseModel):
    parent_id: str
    mode: Optional[str] = "simple"  # "simple" | "ai"
    max_files: Optional[int] = 100
    text_max: Optional[int] = 500


@router.post("/sort")
def sort_files(body: SortBody, request: Request):
    creds = _get_creds_from_request(request)
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    if (body.mode or "simple").lower() == "ai":
        moved, skipped = sorter.ai_sort_files(
            service,
            body.parent_id,
            text_max=body.text_max or 500,
            max_files=body.max_files or 100,
        )
    else:
        moved, skipped = sorter.sort_files_by_subfolder_name(service, body.parent_id)

    return {
        "status": "ok",
        "parent_id": body.parent_id,
        "moved_count": len(moved),
        "skipped_count": len(skipped),
        "moved": moved,
        "skipped": skipped,
        "mode": (body.mode or "simple").lower(),
    }
