#!/usr/bin/env python3
import sys
from pathlib import Path
from collections import Counter

sys.path.append(str(Path(__file__).resolve().parents[1] / 'src'))
from myntra_to_shopify import read_rows  # type: ignore

def main():
    root = Path('data/input')
    files = [p for p in sorted(root.glob('*.csv')) if 'dress' not in p.name.lower()]
    rows = []
    for p in files:
        rs = read_rows(p)
        rows.extend(rs)

    c_type = Counter([(r.get('articleType') or '').strip().lower() for r in rows])
    c_has_sp = sum(1 for r in rows if (r.get('Selling Price') or r.get('Selling price') or '').strip())
    c_has_mrp = sum(1 for r in rows if (r.get('MRP') or '').strip())
    c_size_std = sum(1 for r in rows if (r.get('Standard Size') or '').strip())
    c_size_brand = sum(1 for r in rows if (r.get('Brand Size') or '').strip())

    print('Files considered (non-dress):')
    for p in files:
        print(f'- {p.name}')
    print(f"\nTotal input rows: {len(rows)}")
    print(f"Rows with Selling Price: {c_has_sp}")
    print(f"Rows with MRP: {c_has_mrp}")
    print(f"Rows with Standard Size: {c_size_std}")
    print(f"Rows with Brand Size: {c_size_brand}")

    print('\nTop articleType values:')
    for k, v in c_type.most_common(20):
        print(f'- {k or "(missing)"}: {v}')

if __name__ == '__main__':
    main()

