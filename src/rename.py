from src.classify import guess_date, guess_invoice_number, guess_client_name

CATEGORY_LABELS = {
    "invoice": "請求書",
    "receipt": "領収書",
    "contract": "契約書",
    "misc": "その他",
}

def make_new_name(orig: str, category: str, text: str) -> str:
    base, ext = (orig.rsplit(".",1)+[""])[:2]
    ext = "."+ext.lower() if ext else ""

    date = guess_date(text) or "日付不明"
    inv  = guess_invoice_number(text) or ""
    client = guess_client_name(text) or ""

    cat_label = CATEGORY_LABELS.get(category, category)

    parts = [cat_label, date]
    if inv:
        parts.append(inv)
    if client:
        parts.append(client[:10])

    return "_".join(parts) + ext
