import re
import unicodedata


SIZE_MAP = {
    "xx-small": "xs", "x-small": "xs", "xs": "xs", "extra small": "xs",
    "s": "s", "small": "s",
    "m": "m", "medium": "m",
    "l": "l", "large": "l",
    "xl": "xl", "x-large": "xl",
    "xxl": "2xl", "2xl": "2xl", "xx-large": "2xl",
}

SIZE_ORDER = ["xs", "s", "m", "l", "xl", "2xl"]


def strip_leading_brand(text: str, brand: str = "zummer") -> str:
    if not text:
        return ""
    cleaned = re.sub(rf"^\s*{re.escape(brand)}\b[\s\-_:]*", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def slugify_for_handle(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s)
    s = s.strip('-').lower()
    return s


def normalize_size(s: str) -> str:
    if not s:
        return ""
    key = s.strip().lower()
    return SIZE_MAP.get(key, key)

