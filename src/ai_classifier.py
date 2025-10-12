from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

try:
    from openai import OpenAI  # type: ignore[import]
except ImportError as exc:  # pragma: no cover - library availability check
    raise ImportError(
        "The openai package must be installed. Ensure requirements are installed with openai>=1.0.0."
    ) from exc

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def _fold_profiles_for_prompt(profiles: Iterable[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for profile in profiles:
        name = profile.get("name", "")
        description = profile.get("description") or ""
        include = profile.get("include") or []
        include_str = ", ".join(include)
        info = f"- {name}"
        if description:
            info += f" : {description}"
        if include_str:
            info += f" (関連キーワード例: {include_str})"
        rows.append(info)
    return "\n".join(rows)


def classify_with_ai(file_name: str, text: str, folder_profiles: List[Dict[str, Any]]) -> str:
    """ファイル内容を用いて最適なフォルダ名を決定する。"""

    if not folder_profiles:
        return ""

    joined = _fold_profiles_for_prompt(folder_profiles)
    prompt = f"""
    あなたは書類の分類アシスタントです。
    以下の情報から、このファイルを分類する最も適切なフォルダ名を1つ選んでください。

    - ファイル名: {file_name}
    - 利用可能なフォルダ候補:
    {joined}
    - ファイル内容（必要に応じて参照してください）:
    {text}

    出力は候補フォルダ名のいずれかをそのまま1行だけ返してください。
    説明や要約、追加の文章は付けないでください。
    適切なフォルダが特定できない場合は "NONE" とだけ返してください。
    """

    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def classify_title_with_ai(file_name: str, folder_profiles: List[Dict[str, Any]]) -> str:
    """タイトルと候補カテゴリから最適なカテゴリ名を返す。"""

    if not folder_profiles:
        return ""

    joined = _fold_profiles_for_prompt(folder_profiles)
    prompt = f"""
    あなたは書類フォルダの分類アシスタントです。
    次のファイル名と候補カテゴリ一覧を見て、最も適切なカテゴリを1つ選んでください。

    ファイル名: {file_name}
    候補カテゴリ:
    {joined}

    出力は候補カテゴリ名のいずれかをそのまま1行で返してください。
    説明や要約、追加の文章は付けないでください。
    どれも適切でない場合は "NONE" とだけ返してください。
    """

    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()
