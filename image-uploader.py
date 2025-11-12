#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import sys
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # optional dependency


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass
class ShopifyConfig:
    store: str
    token: str
    api_version: str


def load_env(dotenv_path: Optional[str]) -> None:
    if dotenv_path is None:
        # try default .env in cwd if present
        default_env = Path.cwd() / ".env"
        if default_env.exists() and load_dotenv:
            load_dotenv(default_env)  # type: ignore
        return
    p = Path(dotenv_path)
    if p.exists() and load_dotenv:
        load_dotenv(p)  # type: ignore


def get_config(args: argparse.Namespace) -> ShopifyConfig:
    store = args.store or os.getenv("SHOPIFY_STORE")
    token = args.token or os.getenv("SHOPIFY_ACCESS_TOKEN")
    api_version = args.api_version or os.getenv("SHOPIFY_API_VERSION", "2024-07")

    missing = []
    if not store:
        missing.append("--store or SHOPIFY_STORE")
    if not token:
        missing.append("--token or SHOPIFY_ACCESS_TOKEN")
    if missing:
        fail(f"Missing required config: {', '.join(missing)}")

    store = store.strip()
    if store.startswith("https://"):
        store = store[len("https://") :]
    if store.endswith("/"):
        store = store[:-1]

    return ShopifyConfig(store=store, token=token, api_version=api_version)


def get_images_dir(args: argparse.Namespace) -> Path:
    images_dir = args.images_dir or os.getenv("IMAGES_DIR")
    if not images_dir:
        fail("Missing images directory: pass --images-dir or set IMAGES_DIR in env/.env")
    return Path(images_dir)


def fail(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def build_session(cfg: ShopifyConfig) -> requests.Session:
    # Backwards-compatible helper; prefer myntra_shopify.shopify_client where possible
    s = requests.Session()
    s.headers.update(
        {
            "X-Shopify-Access-Token": cfg.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "shopify-image-uploader/1.0",
        }
    )
    s.base_url = f"https://{cfg.store}/admin/api/{cfg.api_version}"
    logging.getLogger(__name__).debug(f"Session base_url={s.base_url}")
    return s


def list_images(images_dir: Path) -> List[Path]:
    if not images_dir.exists() or not images_dir.is_dir():
        fail(f"Images directory not found: {images_dir}")
    files: List[Path] = []
    for p in images_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
    logging.getLogger(__name__).debug(f"list_images: dir={images_dir} count={len(files)}")
    return files


def list_images_shallow(images_dir: Path) -> List[Path]:
    if not images_dir.exists() or not images_dir.is_dir():
        fail(f"Images directory not found: {images_dir}")
    files: List[Path] = []
    for p in images_dir.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
    logging.getLogger(__name__).debug(f"list_images_shallow: dir={images_dir} count={len(files)}")
    return files


def extract_sku(
    path: Path,
    mode: str,
    regex: Optional[str],
    images_root: Optional[Path] = None,
    parent_depth: Optional[int] = None,
    parent_regex: Optional[str] = None,
) -> Optional[str]:
    name = path.name
    stem = Path(name).stem
    if mode == "parent":
        # Determine SKU based on parent or ancestor folder
        candidate: Optional[Path] = None
        if parent_depth and parent_depth > 0:
            cur = path
            for _ in range(parent_depth):
                cur = cur.parent
            candidate = cur
        else:
            # auto-walk upwards until images_root looking for a folder that matches regex
            cur = path.parent
            stop = images_root.resolve() if images_root else None
            pat = re.compile(parent_regex or r"^[A-Za-z0-9-_]+$")
            while True:
                if stop is not None and cur.resolve() == stop:
                    break
                if pat.match(cur.name or ""):
                    candidate = cur
                    break
                if cur.parent == cur:
                    break
                cur = cur.parent
        return candidate.name if candidate else path.parent.name

    # filename-based modes
    if regex:
        m = re.search(regex, name)
        if m:
            return m.group(1) if m.groups() else m.group(0)
        return None
    if mode == "stem":
        return stem
    if mode == "prefix":
        m = re.match(r"([A-Za-z0-9-_]+)", stem)
        return m.group(1) if m else None
    return None


def _gid_to_int(gid: str) -> int:
    try:
        return int(gid.rsplit("/", 1)[-1])
    except Exception:
        return int(gid)


def find_variants_by_sku(session: requests.Session, cfg: ShopifyConfig, sku: str) -> List[Dict]:
    # Delegate to shared client
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, find_variants_by_sku as _find
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _find(session, sc, sku)


def _graphql(session: requests.Session, cfg: ShopifyConfig, query: str, variables: Dict) -> Dict:
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, graphql as _gql
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _gql(session, sc, query, variables)


def fetch_all_products_with_variants(session: requests.Session, cfg: ShopifyConfig) -> List[Dict]:
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, fetch_all_products_with_variants as _fetch
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _fetch(session, sc)


def base_from_variant_sku(sku: str) -> str:
    # Strip trailing letters to get the non-size base code
    return re.sub(r"[A-Za-z]+$", "", sku or "")


def upload_image_to_product(
    session: requests.Session,
    cfg: ShopifyConfig,
    product_id: int,
    image_b64: str,
    filename: str,
    alt_text: Optional[str],
    variant_id: Optional[int],
    position: Optional[int] = None,
) -> Dict:
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, upload_image_to_product as _upload
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _upload(session, sc, product_id, image_b64, filename, alt_text, variant_id, position)


def to_base64(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_product_variants(session: requests.Session, cfg: ShopifyConfig, product_id: int) -> List[Dict]:
    # Keep for compatibility (not used elsewhere here)
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, get_product_info as _info
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    product = _info(session, sc, product_id)
    return product.get("variants", [])


def get_product_info(session: requests.Session, cfg: ShopifyConfig, product_id: int) -> Dict:
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, get_product_info as _info
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _info(session, sc, product_id)


def get_product_images(session: requests.Session, cfg: ShopifyConfig, product_id: int) -> List[Dict]:
    from myntra_shopify.shopify_client import ShopifyConfig as Cfg, get_product_images as _imgs
    sc = Cfg(store=cfg.store, token=cfg.token, api_version=cfg.api_version)
    return _imgs(session, sc, product_id)


def broadcast_image_to_products(
    session: requests.Session,
    cfg: ShopifyConfig,
    image_path: Path,
    alt_text: Optional[str],
    product_ids: Optional[List[int]],
    limit: Optional[int],
    dry_run: bool,
    skip_if_alt_exists: bool,
    delay: float,
) -> int:
    if not image_path.exists() or not image_path.is_file():
        fail(f"Broadcast image not found: {image_path}")

    resolved = image_path.resolve()
    alt_text = alt_text or resolved.stem

    targets: List[int]
    if product_ids:
        targets = [int(pid) for pid in product_ids]
    else:
        products = fetch_all_products_with_variants(session, cfg)
        targets = sorted({int(p.get("product_id")) for p in products if p.get("product_id")})

    if limit and limit > 0:
        targets = targets[:limit]

    if not targets:
        print("No product IDs available for broadcast.")
        return 0

    print(f"Broadcasting image '{resolved.name}' to {len(targets)} product(s)")
    if dry_run:
        print("Dry run: no uploads will be performed.")

    log = logging.getLogger(__name__)
    image_b64 = None if dry_run else to_base64(resolved)

    uploaded = 0
    skipped = 0
    previewed = 0
    errors = 0

    for pid in targets:
        try:
            existing = get_product_images(session, cfg, pid)
        except Exception as e:
            print(f"product_id={pid} -> error:unable-to-fetch-images {e}")
            errors += 1
            continue

        if skip_if_alt_exists and alt_text and any((img.get("alt") or "") == alt_text for img in existing):
            print(f"product_id={pid} -> skip:alt-exists alt='{alt_text}'")
            skipped += 1
            continue

        position = len(existing) + 1 if existing else 1

        if dry_run:
            print(
                f"product_id={pid} -> dry-run:would-upload alt='{alt_text}' position={position}"
            )
            previewed += 1
            continue

        try:
            _image = upload_image_to_product(
                session=session,
                cfg=cfg,
                product_id=pid,
                image_b64=image_b64 or "",
                filename=resolved.name,
                alt_text=alt_text,
                variant_id=None,
                position=position,
            )
        except Exception as e:
            print(f"product_id={pid} -> error:upload-failed {e}")
            errors += 1
            continue

        img_id = _image.get("id") if isinstance(_image, dict) else None
        print(f"product_id={pid} -> ok:uploaded image_id={img_id} position={position}")
        uploaded += 1
        if delay > 0:
            time.sleep(delay)

    print(
        f"Broadcast complete. uploaded={uploaded} skipped={skipped} previewed={previewed} errors={errors}"
    )
    log.info(
        "Broadcast summary: uploaded=%s skipped=%s previewed=%s errors=%s target_count=%s",
        uploaded,
        skipped,
        previewed,
        errors,
        len(targets),
    )
    return 0 if errors == 0 else 1


def process_file(
    path: Path,
    session: requests.Session,
    cfg: ShopifyConfig,
    sku_mode: str,
    sku_regex: Optional[str],
    images_root: Path,
    parent_depth: Optional[int],
    parent_regex: Optional[str],
    link_to_variant: bool,
    alt_from: str,
    dry_run: bool,
    match_multiple: str,
) -> Tuple[str, str]:
    sku = extract_sku(
        path=path,
        mode=sku_mode,
        regex=sku_regex,
        images_root=images_root,
        parent_depth=parent_depth,
        parent_regex=parent_regex,
    )
    if not sku:
        return (str(path), "skip:no-sku")

    # For dry-run, avoid network calls and only show intended action
    if dry_run:
        alt_text = Path(path.name).stem if alt_from == "stem" else None
        return (
            str(path),
            "dry-run:would-upload "
            + f"sku={sku} "
            + (f"alt='{alt_text}' " if alt_text else "")
            + ("link-to-variant " if link_to_variant else ""),
        )

    variants = find_variants_by_sku(session, cfg, sku)
    if not variants:
        return (str(path), f"error:no-variant-for-sku:{sku}")

    chosen_variants: List[Dict]
    if match_multiple == "first":
        chosen_variants = [variants[0]]
    else:
        chosen_variants = variants

    product_id = int(chosen_variants[0]["product_id"])  # same for all in list
    alt_text = None
    if alt_from == "stem":
        alt_text = Path(path.name).stem

    image_b64 = to_base64(path)
    variant_id = int(chosen_variants[0]["id"]) if link_to_variant else None
    try:
        _image = upload_image_to_product(
            session=session,
            cfg=cfg,
            product_id=product_id,
            image_b64=image_b64,
            filename=path.name,
            alt_text=alt_text,
            variant_id=variant_id,
        )
        return (str(path), f"ok:uploaded sku={sku} product_id={product_id} variant_id={variant_id}")
    except Exception as e:
        return (str(path), f"error:upload-failed sku={sku} reason={e}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upload product images to Shopify by matching SKU to filenames")
    p.add_argument("--store", help="Shopify store domain, e.g. myshop.myshopify.com")
    p.add_argument("--token", help="Shopify Admin API access token")
    p.add_argument("--api-version", default="2024-07", help="Shopify Admin API version (default: 2024-07)")
    p.add_argument("--dotenv", help="Path to .env file (optional)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v for INFO, -vv for DEBUG)")

    p.add_argument("--images-dir", help="Directory containing images to upload (or set IMAGES_DIR env var)")
    p.add_argument(
        "--get-skus-for-product",
        metavar="PRODUCT_ID",
        type=int,
        nargs="+",
        help="Fetch and print SKUs for one or more Shopify product IDs, then exit",
    )
    p.add_argument(
        "--get-product-info",
        metavar="PRODUCT_ID",
        type=int,
        nargs="+",
        dest="get_product_info_ids",
        help="Fetch and print basic info (title, status, vendor) for product IDs, then exit",
    )
    p.add_argument(
        "--find-variants-by-sku",
        metavar="SKU",
        nargs="+",
        help="Resolve one or more SKUs to variant and product IDs, then exit",
    )
    p.add_argument(
        "--upload-for-base",
        metavar="BASE_SKU",
        help="Upload images from IMAGES_DIR/<BASE_SKU> to the product whose variants start with BASE_SKU",
    )
    p.add_argument(
        "--batch-upload-bases",
        action="store_true",
        help="Process all immediate subfolders under IMAGES_DIR as base SKUs and upload to their products",
    )
    p.add_argument(
        "--bases-depth",
        type=int,
        choices=[1, 2],
        default=1,
        help="Depth for discovering base SKU folders under IMAGES_DIR: 1 = direct children (default), 2 = children of category folders",
    )
    p.add_argument(
        "--bases",
        nargs='+',
        help="When used with --batch-upload-bases, only process these base folder names",
    )
    p.add_argument(
        "--limit-bases",
        type=int,
        help="When used with --batch-upload-bases, process only the first N base folders (sorted)",
    )
    p.add_argument(
        "--offset-bases",
        type=int,
        default=0,
        help="Skip the first K base folders (after sorting) before processing",
    )
    p.add_argument(
        "--limit-files-per-base",
        type=int,
        help="Limit number of files uploaded per base folder",
    )
    p.add_argument(
        "--one-level",
        action="store_true",
        help="When uploading by base or batch, only include files directly inside each base folder (no recursion)",
    )
    p.add_argument(
        "--product-only",
        action="store_true",
        help="When uploading in --upload-for-base mode, attach images to the product only (no variant link)",
    )
    p.add_argument(
        "--only-empty-products",
        action="store_true",
        help="Only upload to products that currently have zero images; skip others",
    )
    p.add_argument(
        "--sku-mode",
        choices=["stem", "prefix", "parent"],
        default="stem",
        help="How to derive SKU (default: stem). Use 'parent' to take folder name.",
    )
    p.add_argument(
        "--sku-regex",
        help="Regex to extract SKU from filename. If provided, the first capturing group (or full match) is used.",
    )
    p.add_argument(
        "--parent-depth",
        type=int,
        help="When --sku-mode=parent, take the Nth ancestor folder (1=parent). If not set, auto-detect using --parent-regex.",
    )
    p.add_argument(
        "--parent-regex",
        help="When --sku-mode=parent and --parent-depth not set, match ancestor folder name by this regex (default: ^[A-Za-z0-9-_]+$).",
    )
    p.add_argument(
        "--match-multiple",
        choices=["first", "all"],
        default="first",
        help="If multiple variants share the SKU, pick first or consider all (default: first)",
    )
    p.add_argument(
        "--link-to-variant",
        action="store_true",
        help="Attach uploaded image to the matched variant (Shopify will also show it on the product)",
    )
    p.add_argument(
        "--alt-from",
        choices=["none", "stem"],
        default="none",
        help="Set image alt text from filename stem",
    )
    p.add_argument("--dry-run", action="store_true", help="Show what would be uploaded without calling Shopify")
    p.add_argument(
        "--broadcast-image",
        help="Upload the specified image to all products (or --broadcast-product-ids)",
    )
    p.add_argument(
        "--broadcast-alt",
        help="Alt text to set when broadcasting image (default: filename stem)",
    )
    p.add_argument(
        "--broadcast-product-ids",
        type=int,
        nargs="+",
        help="Only broadcast to these product IDs",
    )
    p.add_argument(
        "--broadcast-limit",
        type=int,
        help="Limit broadcast to the first N product IDs (after sorting)",
    )
    p.add_argument(
        "--broadcast-skip-if-alt-exists",
        action="store_true",
        help="Skip products that already have an image with the broadcast alt text",
    )
    p.add_argument(
        "--broadcast-delay",
        type=float,
        default=0.5,
        help="Delay in seconds between broadcast uploads (default: 0.5)",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    # Setup logging
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger(__name__)
    load_env(args.dotenv)
    cfg = get_config(args)
    log.info(f"Using store={cfg.store} api_version={cfg.api_version}")
    session = build_session(cfg)

    if args.broadcast_image:
        image_path = Path(args.broadcast_image).expanduser()
        product_ids = args.broadcast_product_ids if args.broadcast_product_ids else None
        return broadcast_image_to_products(
            session=session,
            cfg=cfg,
            image_path=image_path,
            alt_text=args.broadcast_alt,
            product_ids=product_ids,
            limit=args.broadcast_limit,
            dry_run=bool(args.dry_run),
            skip_if_alt_exists=bool(args.broadcast_skip_if_alt_exists),
            delay=float(args.broadcast_delay),
        )

    # Utility mode: fetch variant SKUs for product IDs
    if args.get_skus_for_product:
        for pid in args.get_skus_for_product:
            try:
                variants = get_product_variants(session, cfg, int(pid))
            except Exception as e:
                print(f"product_id={pid} -> error:{e}")
                continue
            skus = [v.get("sku") for v in variants]
            print(f"product_id={pid} -> skus={skus}")
        return 0

    # Utility mode: resolve SKUs to variant/product IDs
    if args.find_variants_by_sku:
        for sku in args.find_variants_by_sku:
            try:
                variants = find_variants_by_sku(session, cfg, sku)
            except Exception as e:
                print(f"sku={sku} -> error:{e}")
                continue
            if not variants:
                print(f"sku={sku} -> not found")
                continue
            print(
                "sku="
                + sku
                + " -> "
                + ", ".join(
                    f"variant_id={v['id']} product_id={v['product_id']} (sku={v.get('sku')})" for v in variants
                )
            )
        return 0

    # Utility: show basic product info
    if hasattr(args, "get_product_info_ids") and args.get_product_info_ids:
        for pid in args.get_product_info_ids:
            try:
                p = get_product_info(session, cfg, int(pid))
                title = p.get("title")
                status = p.get("status")
                vendor = p.get("vendor")
                handle = p.get("handle")
                published_at = p.get("published_at")
                print(f"product_id={pid} title='{title}' status={status} vendor='{vendor}' handle='{handle}' published_at={published_at}")
            except Exception as e:
                print(f"product_id={pid} -> error:{e}")
        return 0

    # Mode: Upload by base SKU (product-level)
    if args.upload_for_base:
        images_root = get_images_dir(args)
        base = args.upload_for_base.strip()
        folder = images_root / base
        if not folder.exists() or not folder.is_dir():
            fail(f"Images folder for base '{base}' not found at: {folder}")

        # Fetch all products and build mapping
        products = fetch_all_products_with_variants(session, cfg)
        # find product whose variants have SKU starting with base
        candidates = [p for p in products if any((sku or "").startswith(base) for sku in p["variant_skus"])]
        log.info(f"Base {base}: found {len(candidates)} candidate product(s)")
        if not candidates:
            fail(f"No product found whose variant SKU starts with '{base}'")
        if len(candidates) > 1:
            # try to narrow by exact base match after stripping trailing letters
            narrowed = [
                p for p in candidates if base in {base_from_variant_sku(s) for s in p["variant_skus"]}
            ]
            if len(narrowed) == 1:
                candidates = narrowed
            else:
                # Tie-breaker: choose product with fewest images (prefer zero)
                counts: List[Tuple[int, int]] = []  # (product_id, image_count)
                for p in candidates:
                    pid = int(p["product_id"])
                    imgs = get_product_images(session, cfg, pid)
                    counts.append((pid, len(imgs)))
                log.info("Candidates image counts: " + ", ".join(f"{pid}:{cnt}" for pid, cnt in counts))
                counts.sort(key=lambda t: t[1])
                chosen_pid = counts[0][0]
                candidates = [p for p in candidates if int(p["product_id"]) == chosen_pid]

        product_id = int(candidates[0]["product_id"])
        log.info(f"Base {base}: chosen product_id={product_id}")
        if args.only_empty_products:
            existing = get_product_images(session, cfg, product_id)
            if existing:
                print(f"{base}: skip -> product_id={product_id} already has {len(existing)} image(s)")
                return 0
        files = list_images_shallow(folder) if args.one_level else list_images(folder)
        if not files:
            print("No image files found.")
            return 0
        print(f"Found {len(files)} image(s) under {folder}")
        for path in files:
            if bool(args.dry_run):
                print(f"{path} -> dry-run:would-upload base={base} product_id={product_id}")
                continue
            try:
                _image = upload_image_to_product(
                    session=session,
                    cfg=cfg,
                    product_id=product_id,
                    image_b64=to_base64(path),
                    filename=path.name,
                    alt_text=(Path(path.name).stem if args.alt_from == "stem" else None),
                    variant_id=None if args.product_only or not args.link_to_variant else None,
                )
                img_id = _image.get("id") if isinstance(_image, dict) else None
                print(f"{path} -> ok:uploaded base={base} product_id={product_id} image_id={img_id}")
                time.sleep(0.5)
            except Exception as e:
                print(f"{path} -> error:upload-failed base={base} reason={e}")
        return 0

    # Mode: Batch upload by base SKU for all folders under IMAGES_DIR
    if args.batch_upload_bases:
        images_root = get_images_dir(args)
        # Fetch all products once
        products = fetch_all_products_with_variants(session, cfg)

        # Discover base folders at requested depth
        bases: List[Path] = []
        sku_name_re = re.compile(r"^[A-Za-z0-9-_]+$")
        if args.bases_depth == 1:
            bases = [d for d in images_root.iterdir() if d.is_dir() and sku_name_re.match(d.name or "")]
        else:
            # depth=2: iterate category folders, then their immediate subfolders as bases
            for cat in images_root.iterdir():
                if not cat.is_dir():
                    continue
                for d in cat.iterdir():
                    if d.is_dir() and sku_name_re.match(d.name or ""):
                        bases.append(d)
        # Filter specific bases if requested
        if args.bases:
            wanted = set(args.bases)
            bases = [d for d in bases if d.name in wanted]
        # Sort for deterministic order
        bases.sort(key=lambda p: p.name)
        # Apply offset and limit if requested
        if args.offset_bases and args.offset_bases > 0:
            bases = bases[args.offset_bases :]
        if args.limit_bases and args.limit_bases > 0:
            bases = bases[: args.limit_bases]

        if not bases:
            print("No base SKU folders found under IMAGES_DIR.")
            return 0

        print(f"Discovered {len(bases)} base SKU folder(s) under {images_root}")
        for folder in bases:
            base = folder.name
            candidates = [p for p in products if any((sku or "").startswith(base) for sku in p["variant_skus"])]
            log.info(f"Base {base}: candidates={len(candidates)}")
            if not candidates:
                print(f"{base}: skip -> no matching product by variant SKU prefix")
                continue
            if len(candidates) > 1:
                narrowed = [
                    p for p in candidates if base in {base_from_variant_sku(s) for s in p["variant_skus"]}
                ]
                if len(narrowed) == 1:
                    candidates = narrowed
                else:
                    counts: List[Tuple[int, int]] = []
                    for p in candidates:
                        pid = int(p["product_id"])
                        imgs = get_product_images(session, cfg, pid)
                        counts.append((pid, len(imgs)))
                    log.info("Candidates image counts: " + ", ".join(f"{pid}:{cnt}" for pid, cnt in counts))
                    counts.sort(key=lambda t: t[1])
                    chosen_pid = counts[0][0]
                    candidates = [p for p in candidates if int(p["product_id"]) == chosen_pid]

            product_id = int(candidates[0]["product_id"])
            log.info(f"Base {base}: chosen product_id={product_id}")
            if args.only_empty_products:
                existing = get_product_images(session, cfg, product_id)
                if existing:
                    print(f"{base}: skip -> product_id={product_id} already has {len(existing)} image(s)")
                    continue
            files = list_images_shallow(folder) if args.one_level else list_images(folder)
            if args.limit_files_per_base and args.limit_files_per_base > 0:
                files = files[: args.limit_files_per_base]
            if not files:
                print(f"{base}: no image files found in folder")
                continue
            print(f"{base}: {len(files)} image(s) -> product_id={product_id}")
            for path in files:
                if bool(args.dry_run):
                    print(f"{path} -> dry-run:would-upload base={base} product_id={product_id}")
                    continue
                try:
                    _image = upload_image_to_product(
                        session=session,
                        cfg=cfg,
                        product_id=product_id,
                        image_b64=to_base64(path),
                        filename=path.name,
                        alt_text=(Path(path.name).stem if args.alt_from == "stem" else None),
                        variant_id=None if args.product_only or not args.link_to_variant else None,
                    )
                    print(f"{path} -> ok:uploaded base={base} product_id={product_id}")
                    time.sleep(0.5)
                except Exception as e:
                    print(f"{path} -> error:upload-failed base={base} reason={e}")
        return 0

    images_dir = get_images_dir(args)
    files = list_images(images_dir)
    if not files:
        print("No image files found.")
        return 0

    print(f"Found {len(files)} image(s) under {images_dir}")
    results: List[Tuple[str, str]] = []
    for path in files:
        res = process_file(
            path=path,
            session=session,
            cfg=cfg,
            sku_mode=args.sku_mode,
            sku_regex=args.sku_regex,
            images_root=images_dir,
            parent_depth=args.parent_depth,
            parent_regex=args.parent_regex,
            link_to_variant=bool(args.link_to_variant),
            alt_from=args.alt_from,
            dry_run=bool(args.dry_run),
            match_multiple=args.match_multiple,
        )
        results.append(res)
        print(f"{res[0]} -> {res[1]}")
        if not args.dry_run:
            time.sleep(0.5)  # be nice to Shopify API

    # simple summary
    total = len(results)
    uploaded = sum(1 for _, r in results if r.startswith("ok:"))
    skipped = sum(1 for _, r in results if r.startswith("skip:"))
    errors = total - uploaded - skipped
    print(f"Done. uploaded={uploaded} skipped={skipped} errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
