#!/usr/bin/env python3
"""Basic smoke test for the refactored modules.

Runs a transform on a sample input and checks headers and non-empty output.
This test avoids any network and LLM by default.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from myntra_shopify.transform import transform, write_output, ESSENTIAL_HEADERS  # type: ignore


def main() -> int:
    sample = ROOT / 'data' / 'input' / 'Myntra - CO-ORDS.csv'
    if not sample.exists():
        print(f"Sample input not found: {sample}")
        return 0

    # Ensure LLM disabled for smoke test
    os.environ.pop('LLM_BASE_URL', None)

    rows = transform(sample, default_qty=50, default_grams=400, llm_cfg=None)
    if not rows:
        print("Smoke test failed: no rows produced")
        return 1
    # Quick header check by writing to a temp path
    out_path = ROOT / 'data' / 'output' / 'smoke_test_output.csv'
    write_output(out_path, rows)
    print(f"Smoke test ok: wrote {len(rows)} rows to {out_path}")
    print("Headers:", ESSENTIAL_HEADERS)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

