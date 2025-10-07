# oauth_server.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os, json, time, secrets, threading

# ====== 環境設定 ======
UI_BASE = os.getenv("UI_BASE", "https://ui.gfcdapp.com")
API_BASE = os.getenv("API_BASE", "https://drive.gfcdapp.com")
DOMAIN = os.getenv("COOKIE_DOMAIN", ".gfcdapp.com")

# PrivateTmp 対策: /var/lib/das/ のような永続パスを使う
STATE_DIR = os.getenv("STATE_DIR", "/var/lib/das")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
STATE_TTL_SEC = 10 * 60

# Google OAuth 設定（必ず環境変数で渡す）
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive"]
REDIRECT_URI = f"{API_BASE}/oauth2callback"

# メモリ上の state
STATE_STORE: dict[str, dict] = {}
_lock = threading.Lock()

app = FastAPI(title="Drive Auto Sorter OAuth Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[UI_BASE],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _now() -> float:
    return time.time()

def _ensure_state_dir():
    os.makedirs(STATE_DIR, exist_ok=True)

def _load_state():
    _ensure_state_dir()
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        with _lock:
            # TTL で掃除
            now = _now()
            STATE_STORE.clear()
            for k, v in data.items():
                if now - v.get("ts", 0) < STATE_TTL_SEC:
                    STATE_STORE[k] = v
    except FileNotFoundError:
        pass
    except Exception as e:
        print("WARN: failed to load state:", e)

def _save_state():
    _ensure_state_dir()
    tmp = STATE_FILE + ".tmp"
    with _lock:
        now = _now()
        data = {k: v for k, v in STATE_STORE.items() if now - v.get("ts", 0) < STATE_TTL_SEC}
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print("ERROR: failed to save state:", e)

def _set_cookie_state(resp: Response, state: str):
    resp.set_cookie(
        key="das_state",
        value=state,
        domain=DOMAIN,
        path="/",
        secure=True,
        httponly=True,
        samesite="None",
        max_age=STATE_TTL_SEC,
    )

def _get_cookie_state(request: Request) -> str | None:
    return request.cookies.get("das_state")

def _new_flow(state: str | None = None) -> Flow:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set")
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "project_id": "drive-auto-sorter",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=GOOGLE_SCOPES,
        state=state,
    )

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/login")
def login(next: str | None = None):
    """Google の同意画面へリダイレクト。cookie と state を永続化"""
    _load_state()
    sid = secrets.token_urlsafe(16)
    next_url = next or f"{UI_BASE}/?authed=1"
    with _lock:
        STATE_STORE[sid] = {"next": next_url, "ts": _now()}
    _save_state()

    flow = _new_flow(state=sid)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )
    resp = RedirectResponse(url=auth_url, status_code=307)
    _set_cookie_state(resp, sid)
    return resp

@app.get("/oauth2callback")
def oauth2callback(request: Request):
    """Google から code & state が返る。state を検証してトークン交換し、UI に戻す。"""
    _load_state()

    params = dict(request.query_params)
    state = params.get("state")
    code = params.get("code")
    if not state:
        raise HTTPException(status_code=400, detail="missing state")

    cookie_state = _get_cookie_state(request)
    if cookie_state != state:
        # Cookie とクエリの state が一致しない（クロスサイト/別タブや TTL 切れ）
        raise HTTPException(status_code=400, detail="invalid state")

    with _lock:
        meta = STATE_STORE.get(state)

    if not meta:
        # TTL 切れ or 別 /tmp のケース
        raise HTTPException(status_code=400, detail="invalid state")

    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    flow = _new_flow(state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"token exchange failed: {e}")

    creds = flow.credentials
    creds_json = json.dumps(
        {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
    )

    # 1回使った state は破棄
    with _lock:
        STATE_STORE.pop(state, None)
    _save_state()

    # 次の画面へ（UI に戻る）
    next_url = meta.get("next") or f"{UI_BASE}/?authed=1"
    # UI 側で /api/token を叩いて取りに来る実装なら state->token の一時保存も可能
    # 今回はシンプルにトークンの JSON を直表示（必要なら /api/token で取り出す形に変更してOK）
    # ここでは UI に戻す
    resp = RedirectResponse(url=next_url, status_code=307)
    # Cookie は消しても良い（任意）
    resp.delete_cookie("das_state", domain=DOMAIN, path="/")
    # もし UI から /api/token を叩く設計なら、STATE_STOREにトークンを紐づけて保存しておく
    return resp

@app.get("/api/token")
def api_token(request: Request):
    """必要ならここで state->token を返す形にする（簡易スタブ）"""
    return JSONResponse({"detail": "Not Implemented"}, status_code=404)
