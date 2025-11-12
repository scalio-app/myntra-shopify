# Myntra → Shopify CSV Transformer

A Python utility to convert Myntra product listing CSVs into Shopify-compatible product CSVs with correct variant handling, taxonomy mapping, and optional LLM-generated Body (HTML) descriptions.

## Features
- Groups variants by `styleGroupId` and preserves exact `vendorSkuCode` as Shopify `Variant SKU`.
- Normalizes vendor to `Zummer` and strips leading brand from Title and Handle.
- Maps Myntra `articleType` to Shopify Product Category (taxonomy strings).
- Pricing: uses Selling Price when available, otherwise MRP (Compare At set to MRP when Selling Price exists).
- Variants: Option1 = Size with normalized values (xs, s, m, l, xl, 2xl).
- Inventory defaults: tracker=shopify, qty=50, policy=deny, fulfillment=manual.
- LLM descriptions via OpenAI-compatible API (cloud or local server like `http://127.0.0.1:1234`).
- Caching of descriptions per handle; refresh option to regenerate.
- LLM usage control: prefer LLM output (`--llm-prefer`) or fall back to LLM only when attribute-based description is empty. Cap LLM usage per run with `--llm-max-products`.
- Env-first configuration via `.env` (plus `--env-file` override).

## Project Structure
```
./
├─ .env                 # Your local overrides (not committed)
├─ .env.example         # Template of supported variables
├─ README.md
├─ src/
│  └─ myntra_to_shopify.py
├─ data/
│  ├─ input/
│  │  └─ (place Myntra CSVs here)
│  └─ output/
│     └─ (generated Shopify CSVs)
```

## Setup
- Python 3.9+ (standard library only)
- Copy `.env.example` to `.env` and adjust values:

```bash
cp .env.example .env
# Edit .env
```

## .env Variables (common)
- DEFAULT_QTY, DEFAULT_GRAMS
- LLM_BASE_URL (e.g., `https://api.openai.com` or `http://127.0.0.1:1234`)
- LLM_ENDPOINT (`chat` or `completions`)
- LLM_MODEL (e.g., `gpt-4o-mini`, `qwen/qwen3-8b`)
- LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT, LLM_RATE_SLEEP, LLM_CACHE_DIR
- LLM_BRAND (default: Zummer), LLM_AUDIENCE
- OPENAI_API_KEY (only for cloud use)

## Usage
Local server example (no API key needed):
```bash
python3 src/myntra_to_shopify.py \
  --input "data/input/Myntra - DRESS.csv" \
  --output "data/output/shopify_import_llm_local.csv" \
  --llm-enable --llm-prefer \
  --env-file .env
```
Notes:
- `.env` in project root is auto-loaded. `--env-file` lets you point to a different env file or re-apply overrides.
- With local server defaults in `.env` (LLM_BASE_URL=`http://127.0.0.1:1234`, LLM_ENDPOINT=`completions`, LLM_MODEL=`qwen/qwen3-8b`), requests will target your local instance.

OpenAI cloud example:
```bash
export OPENAI_API_KEY=... # or set in .env
python3 src/myntra_to_shopify.py \
  --input "data/input/Myntra - DRESS.csv" \
  --output "data/output/shopify_import_llm_cloud.csv" \
  --llm-enable --llm-prefer \
  --env-file .env
```

## Regenerating copy
- Delete the cached file in `LLM_CACHE_DIR/{handle}.html` or run with `--llm-refresh`.

## Security
- Do not hardcode API keys in code. Prefer `.env` or `--llm-api-key-file`.
- The legacy script in `~/Downloads/myntra_to_shopify.py` should not be used; it contains a hardcoded key.
