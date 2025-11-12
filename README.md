# Myntra → Shopify (Transform + Images)

Convert Myntra CSV/Excel into a Shopify import CSV and upload product images (including direct, staged uploads from your browser to Shopify). Ships with a polished web UI and job tracking.

## Features

- Transform
  - CSV + Excel (.xlsx/.xls) support with robust header detection
  - Variants grouped/sorted; sizes normalized (S/M/L/XL/2XL)
  - Brand strip in titles; SEO handles (includes styleId)
  - Category/type inference; price/compare‑at mapping
  - Body (HTML) via attributes or LLM (OpenAI‑compatible)
- Images
  - Local Folder → SKU (direct staged uploads from browser → Shopify) + attach by SKU
  - Server‑path tools: By SKU, By Base, Broadcast
  - Friendly to rate limits (delay + 429 backoff)
- Web UI
  - Dashboard, Uploads, Transform, Jobs, Images, Settings
  - DaisyUI styling, toasts, dark mode, live job updates

## Quick Start

```bash
pip install -r requirements.txt
uvicorn server.app:app --reload --app-dir src
# Open http://127.0.0.1:8000/ui
```

1) Settings → enter Shopify Store (e.g., yourstore.myshopify.com), API Version (e.g., 2024-07), Access Token → Test Connection
2) Uploads → upload Myntra CSV/Excel
3) Transform → pick file → set options → Create job → Download CSV
4) Images (recommended) → Local Folder → SKU (Direct to Shopify) → pick folder → Start Upload → attach job

## Brand & Vendor

Settings → Brand & Vendor:
- Brand Strip Value (e.g., `zummer`) — stripped from titles/descriptions
- Vendor Name — used in Shopify CSV
- Brand Name & Audience — used for LLM copy (optional)

## Run with Docker

```bash
docker build -t myntra-shopify .
docker run --rm -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/results:/app/results \
  myntra-shopify
# Open http://127.0.0.1:8000/ui
```

## Notes

- Credentials/settings are saved in `data/settings.json` (do not commit secrets)
- Job results go to `results/` (CSV/JSON)
- Optional CLI: `python3 src/myntra_to_shopify.py --input file.csv --output out.csv`

Run with Docker
- Build: `docker build -t myntra-shopify .`
- Run: `docker run --rm -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/uploads:/app/uploads -v $(pwd)/results:/app/results myntra-shopify`
- Open: http://127.0.0.1:8000/ui

Before pushing to GitHub
- Ensure `.gitignore` excludes: `data/settings.json`, `data/app.sqlite3`, `uploads/`, `results/`, `.cache/`, `.env`.
- Scrub any secrets from tracked files.
