from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import json
import time
import secrets

app = FastAPI(title="Drive Auto Sorter OAuth Backend", version="1.0.0")

def _set_cookie_state(resp: Response, state: str):
    resp.set_cookie(
        key="das_state",
        value=state,
        domain=".gfcdapp.com",
        path="/",
        secure=True,
        httponly=True,
        samesite="None",
        max_age=10 * 60,
    )

# ---- 設定 ----
import os
GOOGLE_CLIENT_CONFIG = {
    "web": {
        # 環境変数から読み込む（ローカルでは .env から取得）
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),

        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["https://drive.gfcdapp.com/oauth2callback"],
    }
}

UI_BASE = "https://ui.gfcdapp.com"

STATE_STORE = {}
STATE_ISSUED_AT = {}
STATE_NEXT = {}

# ---- Cookie付与関数（重要）----
def _set_cookie(resp: Response, sid: str):
    resp.set_cookie(
        key="das_session",
        value=sid,
        domain=".gfcdapp.com",  # ui↔drive 共通
        path="/",
        secure=True,
        httponly=True,
        samesite="None",
        max_age=60 * 60 * 6,  # 6時間
    )

# ---- Google OAuth Flow ----
def _new_flow(state: str):
    flow = Flow.from_client_config(
        GOOGLE_CLIENT_CONFIG,
        scopes=["https://www.googleapis.com/auth/drive"],
        redirect_uri="https://drive.gfcdapp.com/oauth2callback",
    )
    return flow

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*gfcdapp\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Health ----
@app.get("/health")
def health():
    return {"status": "ok", "time": time.strftime("%Y-%m-%dT%H:%M:%S")}

# ---- /login ----
from fastapi.responses import HTMLResponse
@app.get("/login")
def login(request: Request):
    sid = secrets.token_urlsafe(16)
    STATE_STORE[sid] = None
    STATE_ISSUED_AT[sid] = time.time()

    next_url = request.query_params.get("next") or f"{UI_BASE}/?authed=1"
    STATE_NEXT[sid] = next_url

    flow = _new_flow(state=sid)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # 200 応答で Set-Cookie を確実に保存 → JS で Google へ遷移
    html = f"""
<!doctype html>
<meta charset="utf-8">
<title>Signing in…</title>
<p>Google へリダイレクト中…</p>
<script>
  // 念のため JS でも state を保存（ヘッダでも保存しています）
  document.cookie = "das_state={sid}; Domain=.gfcdapp.com; Path=/; SameSite=None; Secure";
  location.replace({json.dumps(auth_url)});
</script>
<noscript>
  <a href="{auth_url}">続行する</a>
</noscript>
"""
    resp = HTMLResponse(content=html, status_code=200)
    _set_cookie_state(resp, sid)  # ← ここで Set-Cookie（HttpOnly, Secure, SameSite=None）
    return resp

# ---- /oauth2callback ----
@app.get("/oauth2callback")
def oauth2callback(request: Request):
    params = dict(request.query_params)
    state = params.get("state")
    code = params.get("code")
    if not state or state not in STATE_STORE:
        raise HTTPException(status_code=400, detail="invalid state")

    flow = _new_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"token exchange failed: {e}")

    creds = flow.credentials
    creds_json = json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
    )
    STATE_STORE[state] = creds_json
    STATE_ISSUED_AT[state] = time.time()

    next_url = STATE_NEXT.pop(state, f"{UI_BASE}/?authed=1")
    resp = RedirectResponse(url=next_url, status_code=307)
    _set_cookie(resp, state)
    return resp

# ---- /api/token ----
@app.get("/api/token")
def get_token(request: Request):
    sid = request.cookies.get("das_session")
    if not sid or sid not in STATE_STORE:
        raise HTTPException(status_code=401, detail="Unauthorized (no credentials)")

    creds_json = STATE_STORE[sid]
    if not creds_json:
        raise HTTPException(status_code=401, detail="Not ready yet")
    return JSONResponse(content=json.loads(creds_json))

# ---- /api/sort ----
@app.post("/api/sort")
def api_sort(req: Request):
    body = req.json()
    folder_id = body.get("folder_id")
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id missing")

    sid = req.cookies.get("das_session")
    if not sid or sid not in STATE_STORE:
        raise HTTPException(status_code=401, detail="Unauthorized")

    creds_data = json.loads(STATE_STORE[sid])
    creds = Credentials.from_authorized_user_info(creds_data)
    service = build("drive", "v3", credentials=creds)

    moved, skipped = [], []
    # TODO: 実際の仕分けロジックを呼び出す
    return {"moved": moved, "skipped": skipped}
