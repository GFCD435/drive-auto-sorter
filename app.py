# app.py
# ------------------------------------------------------------
# Drive Auto Sorter Frontend (Streamlit)
# ------------------------------------------------------------
# Google OAuth は FastAPI 側 (oauth_server.py) に実装。
# ここは UI と fetch() によるバックエンド呼び出しを担当。
# ------------------------------------------------------------

import os
import textwrap
import streamlit as st
import streamlit.components.v1 as components
import json

# ==== 環境設定 ====
BACKEND_BASE = os.getenv("BACKEND_BASE", "https://drive.gfcdapp.com").rstrip("/")
UI_BASE = os.getenv("UI_BASE", "https://ui.gfcdapp.com").rstrip("/")

# ==== ページ設定 ====
st.set_page_config(page_title="Drive Auto Sorter", page_icon="🗂️", layout="centered")

st.title("🗂️ Drive Auto Sorter")
st.caption("Google Drive の親フォルダ直下のファイルを、サブフォルダに自動仕分けします（リネームなし）。")

# ==== クエリパラメータ処理 ====
qp = st.query_params
authed = qp.get("authed")
if authed:
    st.success("✅ Google へのログインが完了しました。仕分けを実行できます。")

# ==== Google ログイン ====
st.subheader("1) Google にログイン")
st.write(
    "このボタンから **FastAPI バックエンド** の `/login` に移動します。"
    " 同意後、自動的にこの画面に戻ります。"
)

login_url = f"{BACKEND_BASE}/login?next={UI_BASE}/?authed=1"
st.link_button("👉 Googleでログイン", login_url, type="primary")

with st.expander("ログイン状態をCookieで確認（任意）", expanded=False):
    components.html(
        textwrap.dedent(f"""
        <div>
          <button id="check" style="padding:8px 12px;">/api/token を確認</button>
          <pre id="out" style="white-space:pre-wrap;"></pre>
        </div>
        <script>
          document.getElementById('check').onclick = async () => {{
            const out = document.getElementById('out');
            out.textContent = "Checking...";
            try {{
              const res = await fetch("{BACKEND_BASE}/api/token", {{
                method: "GET",
                credentials: "include"
              }});
              const txt = await res.text();
              out.textContent = "HTTP " + res.status + "\\n" + txt;
            }} catch (e) {{
              out.textContent = "ERROR: " + e;
            }}
          }};
        </script>
        """),
        height=160,
    )

st.divider()

# ==== 仕分け実行 ====
st.subheader("2) 親フォルダIDを指定して、仕分けを実行")

fid = st.text_input(
    "Google Drive 親フォルダID",
    placeholder="例) 1AbCdEfGhIjKlmnOPQRstuVWxyz012345",
    help="Google Drive で対象フォルダを開いたときの URL に含まれる ID を入力してください。",
)

# ==== ボタン + JS連携 ====
components.html(
    textwrap.dedent(f"""
    <div style="display:flex; gap:8px; align-items:center;">
      <button id="run" style="padding:8px 12px;">仕分けを実行</button>
      <span id="status"></span>
    </div>
    <pre id="result" style="white-space:pre-wrap; margin-top:10px; max-height:300px; overflow:auto;"></pre>
    <script>
      const runBtn = document.getElementById('run');
      const result = document.getElementById('result');
      const status = document.getElementById('status');
      const FOLDER_ID = {json.dumps(fid or "")};

      runBtn.onclick = async () => {{
        result.textContent = "";
        status.textContent = "";
        if (!FOLDER_ID || FOLDER_ID.trim() === "") {{
          result.textContent = "⚠ 親フォルダIDを入力してください。";
          return;
        }}
        status.textContent = "実行中...";
        try {{
          const res = await fetch("{BACKEND_BASE}/api/sort", {{
            method: "POST",
            credentials: "include",
            headers: {{
              "Content-Type": "application/json"
            }},
            body: JSON.stringify({{ parent_id: FOLDER_ID }})
          }});
          const txt = await res.text();
          status.textContent = "完了 (HTTP " + res.status + ")";
          result.textContent = txt;
        }} catch (e) {{
          status.textContent = "失敗";
          result.textContent = "ERROR: " + e;
        }}
      }};
    </script>
    """),
    height=460,
)

st.caption("※ ボタンはブラウザからバックエンドへ直接リクエストします。事前に同じブラウザでログインしてください。")

st.divider()

st.markdown(
    """
### 🔍 ヘルプ
- 「Googleでログイン」を押して認可後、この画面に `?authed=1` が付いて戻れば成功です。
- 親フォルダIDは、Google Drive で開いたURL中の `folders/<ID>` の `<ID>` 部分です。
- 実行時に 401/403 → ログイン未完了 or 権限不足。
- 400 → IDの形式エラー。
"""
)
