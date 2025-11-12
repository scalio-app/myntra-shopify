from __future__ import annotations
import json
from pathlib import Path
from typing import Dict


SETTINGS_PATH: Path | None = None


def init_settings(path: Path) -> None:
    global SETTINGS_PATH
    SETTINGS_PATH = path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        save_settings(default_settings())


def default_settings() -> Dict:
    return {
        "default_qty": 50,
        "default_grams": 400,
        "llm_enable_default": False,
        "llm_prefer_default": False,
        "llm_max_products_default": 0,
        "images_delay_default": 0.5,
        "shopify_store": "",
        "shopify_api_version": "2024-07",
        "shopify_access_token": "",
        # Brand & Vendor (defaults match current repo behavior)
        "brand_strip_value": "zummer",
        "brand_name": "Zummer",
        "brand_audience": "Modern Indian women, 25–35",
        "vendor_name": "Zummer",
        # Branding (for header/footer/UI)
        "branding_name": "Scalio",
        "branding_home_url": "https://scalio.app",
        "branding_logo_url": "",
        "branding_tagline": "Free Myntra → Shopify tool by Scalio",
        "branding_theme": "corporate",
    }


def get_settings() -> Dict:
    assert SETTINGS_PATH is not None
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        base = default_settings()
        base.update(data or {})
        return base
    except Exception:
        return default_settings()


def save_settings(data: Dict) -> None:
    assert SETTINGS_PATH is not None
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))
