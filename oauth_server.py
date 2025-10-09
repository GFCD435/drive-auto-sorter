import os, json, base64, time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from google_auth_oauthlib.flow import Flow
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ui.gfcdapp.com",
        "https://*.gfcdapp.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ui.gfcdapp.com"],
    allow_credentials=True,           # Cookie を跨いで使うので必須
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# --- Proxy/Host handling ---
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["drive.gfcdapp.com", "localhost", "127.0.0.1", "*.gfcdapp.com"]
)

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REDIRECT_URI = f"{BASE_URL}/oauth2callback"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

COOKIE_NAME     = "das_state"
COOKIE_DOMAIN   = ".gfcdapp.com"
COOKIE_SECURE   = True
COOKIE_SAMESITE = "none"
COOKIE_PATH     = "/"

# セッション/クレデンシャル保存の共通モジュール
from src import session

# 既存の state ヘルパは session に置き換え

def save_state(key, payload):
    session.state_set(key, payload)

def load_state(key):
    return session.state_get(key)

def new_flow():
    client_config = {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    flow.redirect_uri = REDIRECT_URI  # 明示・念のため
    return flow

@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")

@app.get("/login")
def login(next: str = "https://ui.gfcdapp.com/?authed=1"):
    flow = new_flow()
    auth_url, google_state = flow.authorization_url(

        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    local_state = base64.urlsafe_b64encode(json.dumps({
        "google_state": google_state,
        "next": next,
        "iat": int(time.time())
    }).encode()).decode().rstrip("=")

    save_state(local_state, {"google_state": google_state, "next": next, "iat": int(time.time())})

    resp = RedirectResponse(url=auth_url, status_code=307)
    resp.set_cookie(
        key=COOKIE_NAME, value=local_state,
        domain=COOKIE_DOMAIN, path=COOKIE_PATH,
        secure=COOKIE_SECURE, httponly=True, samesite=COOKIE_SAMESITE,
        max_age=600,
    )
    return resp

@app.get("/oauth2callback")
def oauth2callback(request: Request, state: str = "", code: str = ""):
    cookie_state = request.cookies.get(COOKIE_NAME)
    if not cookie_state:
        raise HTTPException(status_code=400, detail="missing state cookie")

    rec = load_state(cookie_state)
    if not rec:
        raise HTTPException(status_code=400, detail="state not found")

    if state != rec.get("google_state"):
        raise HTTPException(status_code=400, detail="state mismatch")

    flow = new_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"fetch_token error: {type(e).__name__}: {e}", status_code=400)
    
    print("CALLBACK OK: state=", state) 
    
    # クレデンシャルを保存
    try:
        creds_json = flow.credentials.to_json()
        session.creds_save(cookie_state, creds_json)
    except Exception as e:
        print("failed to save credentials:", e)
    
    # 後片付け（リプレイ対策）
    save_state(cookie_state, {"used": True, "at": int(time.time())})
    
    nxt = rec.get("next") or "https://ui.gfcdapp.com/?authed=1"
    return RedirectResponse(url=nxt, status_code=302)

from api import router as app_router
app.include_router(app_router, prefix="/api")
