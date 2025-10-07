import fitz  # PyMuPDF

def extract_text_from_pdf_bytes(b: bytes) -> str:
    with fitz.open(stream=b, filetype="pdf") as doc:
        text = []
        for page in doc:
            text.append(page.get_text("text"))
        return "\n".join(text).strip()
