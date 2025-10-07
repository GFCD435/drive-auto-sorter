import re
from typing import Optional

DATE_RX = r"(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})"

def guess_category(text: str) -> str:
    if re.search(r"請求書|INVOICE", text, re.I):
        return "invoice"
    if re.search(r"領収書|RECEIPT", text, re.I):
        return "receipt"
    if re.search(r"契約", text):
        return "contract"
    return "misc"

def guess_date(text: str) -> Optional[str]:
    m = re.search(DATE_RX, text)
    if m:
        yyyy, mm, dd = m.groups()
        return f"{int(yyyy):04d}{int(mm):02d}{int(dd):02d}"
    return None

def guess_invoice_number(text: str) -> Optional[str]:
    m = re.search(r"(請求書番号|INVOICE NO[:：]?)\s*([A-Za-z0-9-]+)", text, re.I)
    return m.group(2) if m else None

def guess_client_name(text: str) -> Optional[str]:
    m = re.search(r"(株式会社.*?)[\s　]", text)
    return m.group(1) if m else None


