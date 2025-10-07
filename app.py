# app.py
# ------------------------------------------------------------
# Streamlit Frontend for "Drive Auto Sorter"
# - OAuth は FastAPI 側 (oauth_server.py) が担当
# - ここでは UI を提供し、ブラウザの Cookie を使って
#   fetch("{BACKEND_BASE}/api/sort", { credentials: "include" }) を実行
#
# 必要な環境変数:
#   BACKEND_BASE=https://drive.gfcdapp.com
#   UI_BASE=https://ui.gfcdapp.com
# ------------------------------------------------------------

import os
import textwrap
import streamlit as st
import streamlit.components.v1 as components
import json

BACKEND_BASE = os.getenv("BACKEND_BASE", "https://drive.gfcdapp.com").rstrip("/")
UI_BASE = os.getenv("UI_BASE", "https://ui.gfcdapp.com").rstrip("/")

st.set_page_config(page_title="Drive Auto Sorter", page_icon="🗂️", layout="centered")

st.title("🗂️ Drive Auto Sorter")
st.caption("Google Drive の親フォルダ直下のファイルを、同フォルダ内のサブフォルダへ振り分けます（リネームなし）。")

# ------------------------------------------------------------
# クエリパラメータの扱い（st.experimental_* は使わない）
# ------------------------------------------------------------
# 例: /?authed=1 で戻ってきたときの表示
qp = st.query_params
authed = qp.get("authed", None)
if authed:
    st.success("Google へのログインが完了しました。仕分けを実行できます。")

# ------------------------------------------------------------
# ログイン UI
# ------------------------------------------------------------
st.subheader("1) Google にログイン")
st.write(
    "このボタンから **FastAPI (OAuth バックエンド)** の `/login` へ移動します。"
    " 同意後は自動でこの UI に戻ります。"
)

# ログイン後の戻り先を next に指定
login_url = f"{BACKEND_BASE}/login?next={UI_BASE}/?authed=1"
st.link_button("👉 Googleでログイン", login_url, type="primary")

with st.expander("ログイン状態をブラウザCookieで確認（任意）", expanded=False):
    st.write("`/api/token` を **ブラウザから** 叩いて確認します。サーバ側の Python ではなく、JavaScript の fetch を使います。")
    components.html(
        textwrap.dedent(
            f"""
            <div>
              <button id="check" style="padding:8px 12px">/api/token を確認</button>
              <pre id="out" style="white-space:pre-wrap;"></pre>
            </div>
            <script>
              const out = document.getElementById('out');
              document.getElementById('check').onclick = async () => {{
                out.textContent = "checking...";
                try {{
                  const res = await fetch("{BACKEND_BASE}/api/token", {{
                    method: "GET",
                    credentials: "include"
                  }});
                  const text = await res.text();
                  out.textContent = "HTTP " + res.status + "\\n" + text;
                }} catch (e) {{
                  out.textContent = "ERROR: " + e;
                }}
              }};
            </script>
            """
        ),
        height=140,
    )

st.divider()

# ------------------------------------------------------------
# 仕分け実行 UI
# ------------------------------------------------------------
st.subheader("2) 親フォルダIDを指定して、仕分けを実行")

fid = st.text_input(
    "Google Drive 親フォルダID",
    placeholder="例) 1AbCdEfGhIjKlmnOPQRstuVWxyz012345",
    help="Google Drive で該当フォルダを開いた時の URL: https://drive.google.com/drive/folders/<このID>",
)

# Streamlit 側のボタンを押した瞬間に JS を呼び出して結果表示
# （新しい fid が入力されるたびに、この HTML/JS は再レンダリングされる）
components.html(
    textwrap.dedent(
        f"""
        <div style="display:flex; gap:8px; align-items:center;">
          <button id="run" style="padding:8px 12px">仕分けを実行</button>
          <span id="status"></span>
        </div>
        <pre id="result" style="white-space:pre-wrap; margin-top:12px; max-height:360px; overflow:auto;"></pre>
        <script>
          const runBtn = document.getElementById('run');
          const result = document.getElementById('result');
          const status = document.getElementById('status');
          const FOLDER_ID = {json!r};

          function guardInput(fid) {{
            if (!fid || fid.trim() === "" || fid.trim() === "ここに親フォルダID") {{
              return "有効な folder_id を入力してください。";
            }}
            return null;
          }}

          runBtn.onclick = async () => {{
            result.textContent = "";
            const err = guardInput(FOLDER_ID);
            if (err) {{
              result.textContent = "⚠ " + err;
              return;
            }}
            status.textContent = "実行中...";
            try {{
              const res = await fetch("{BACKEND_BASE}/api/sort", {{
                method: "POST",
                credentials: "include",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ folder_id: FOLDER_ID }})
              }});
              const text = await res.text();
              status.textContent = "完了 (HTTP " + res.status + ")";
              result.textContent = text;
            }} catch (e) {{
              status.textContent = "失敗";
              result.textContent = "ERROR: " + e;
            }}
          }};
        </script>
        """.replace("{json!r}", repr(fid or ""))
    ),
    height=460,
)

st.caption(
    "※ このボタンはブラウザからバックエンドへリクエストします（`credentials: \"include\"`）。"
    " 先に **同じブラウザで** ログインを完了させてください。"
)

st.divider()

st.markdown(
    """
**ヘルプ:**
- まず「Googleでログイン」を押し、同意後にこの画面へ戻ってきます（`?authed=1` が付けば成功）。
- 親フォルダIDは、Google Drive でフォルダを開いたときの URL `folders/<ID>` の `<ID>` です。
- 401/403 が返る場合: ログインが未完了、または対象フォルダへの権限が無い可能性があります。
- 400 で `folder_id` エラーが出る場合: ID のタイプミスや存在しないIDが考えられます。
"""
)
