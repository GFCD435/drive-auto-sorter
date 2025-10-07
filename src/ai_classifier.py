import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def classify_with_ai(file_name: str, text: str) -> str:
    """
    AIにファイルのカテゴリを判定させる
    """
    prompt = f"""
    あなたは書類の分類アシスタントです。
    以下の情報から、このファイルのカテゴリを1つ、日本語で返してください。

    - ファイル名: {file_name}
    - 内容の一部: {text[:500]}

    出力はカテゴリ名だけにしてください（例: "請求書", "領収書", "契約書", "履歴書", "その他"）。
    """

    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        max_tokens=20,
        temperature=0
    )
    return resp["choices"][0]["message"]["content"].strip()
