from io import BytesIO
from PIL import Image
import pytesseract

def extract_text_from_image_bytes(b: bytes) -> str:
    img = Image.open(BytesIO(b))
    return pytesseract.image_to_string(img, lang="jpn+eng")
