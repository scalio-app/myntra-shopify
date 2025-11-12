Myntra → Shopify (Transform + Images)

What it does
- Convert Myntra CSV/Excel to a Shopify import CSV (clean titles, correct variants, categories, optional AI Body HTML).
- Upload images to Shopify by SKU/base or directly from your browser to Shopify (staged uploads). No large files through your server.

Quick start
1) Install: `pip install -r requirements.txt`
2) Run: `uvicorn server.app:app --reload --app-dir src`
3) Open: `http://127.0.0.1:8000/ui`
4) Settings: enter Shopify store, API version, access token → Test Connection
5) Transform: Upload Myntra file → Transform → Create job → Download CSV
6) Images (recommended): Images → “Local Folder → SKU (Direct to Shopify)” → pick folder → Start Upload → attach job

Highlights
- Transform
  - CSV + Excel (.xlsx/.xls); robust header detection
  - Variants grouped/sorted; sizes normalized (S/M/L/XL/2XL)
  - Brand strip in titles; handles include styleId
  - Category/type inference; price/compare-at mapping
  - Body (HTML) via attributes or LLM (OpenAI‑compatible)
- Images
  - Direct staged uploads from browser → Shopify, then attach by SKU
  - Server‑path tools: By SKU, By Base, Broadcast
  - Delay + 429 backoff for rate limits
- Web UI
  - Dashboard, Uploads, Transform, Jobs, Images, Settings
  - DaisyUI styling, toasts, dark mode, live job updates

Brand & vendor (Settings → Brand & Vendor)
- Brand Strip Value (e.g., “zummer”), Vendor Name (CSV Vendor), Brand Name & Audience (LLM)

Notes
- Credentials/settings saved in `data/settings.json` (don’t commit secrets)
- Results in `results/` (CSV/JSON)
- CLI (optional): `python3 src/myntra_to_shopify.py --input file.csv --output out.csv`

Run with Docker
- Build: `docker build -t myntra-shopify .`
- Run: `docker run --rm -p 8000:8000 -v $(pwd)/data:/app/data -v $(pwd)/uploads:/app/uploads -v $(pwd)/results:/app/results myntra-shopify`
- Open: http://127.0.0.1:8000/ui

Before pushing to GitHub
- Ensure `.gitignore` excludes: `data/settings.json`, `data/app.sqlite3`, `uploads/`, `results/`, `.cache/`, `.env`.
- Scrub any secrets from tracked files.
