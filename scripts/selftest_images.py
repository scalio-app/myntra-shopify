#!/usr/bin/env python3
"""Self-test for SKU extraction and image listing helpers.

No network required. Validates deterministic behavior of non-API logic.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from myntra_shopify.images import extract_sku, base_from_variant_sku  # type: ignore


def main() -> int:
    root = Path('/tmp/fake')
    p = root / 'CO05BE5086S.jpg'
    # stem mode
    assert extract_sku(p, mode='stem', regex=None) == 'CO05BE5086S'
    # prefix mode
    assert extract_sku(p, mode='prefix', regex=None) == 'CO05BE5086S'
    # regex mode
    assert extract_sku(p, mode='stem', regex=r'(CO\d+\w+)') == 'CO05BE5086S'
    # base-from-variant sku
    assert base_from_variant_sku('CO05BE5086S') == 'CO05BE5086'
    assert base_from_variant_sku('AB12CD34XL') == 'AB12CD34'
    print('Self-test ok: extract_sku and base_from_variant_sku pass basic checks')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

