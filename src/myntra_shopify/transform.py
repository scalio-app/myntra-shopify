from __future__ import annotations
from pathlib import Path
from collections import defaultdict
import re
import os

from .normalize import normalize_size, slugify_for_handle, strip_leading_brand, SIZE_ORDER
from .mapping import map_from_source_kind
from .describe import build_body_html, generate_body_via_llm
from .io import read_rows, write_shopify_csv, read_any_rows


ESSENTIAL_HEADERS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Product Category",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Status",
]


def transform_rows(
    src_all: list,
    default_qty: int = 50,
    default_grams: int = 400,
    llm_cfg: dict | None = None,
    limit_products: int = 0,
    llm_max_products: int = 0,
    inventory_qty_blank: bool = False,
) -> list:
    src = [r for r in src_all if (r.get("vendorSkuCode") or "").strip()]
    if not src:
        return []
    groups: dict = defaultdict(list)
    for row in src:
        key = (row.get("styleGroupId") or row.get("SKUCode") or row.get("styleId") or "").strip()
        groups[key].append(row)

    out_rows = []
    group_items = list(groups.items())
    if limit_products and limit_products > 0:
        group_items = group_items[:limit_products]

    used_llm_products = 0
    for group_key, items in group_items:
        def size_key(it):
            sz = normalize_size(it.get("Standard Size") or it.get("Brand Size") or "")
            try:
                return SIZE_ORDER.index(sz)
            except ValueError:
                return len(SIZE_ORDER)
        items_sorted = sorted(items, key=size_key)
        items_kept = [it for it in items_sorted if (it.get("vendorSkuCode") or "").strip()]
        if not items_kept:
            continue

        first = items_sorted[0]
        raw_title = (first.get("productDisplayName") or first.get("vendorArticleName") or "").strip()
        title_no_brand = strip_leading_brand(raw_title, brand=os.getenv("BRAND_STRIP_VALUE", "zummer"))
        title = title_no_brand or raw_title
        handle_base = slugify_for_handle(title) or slugify_for_handle(group_key)
        # Always append styleId to handle for uniqueness/traceability
        style_id = (first.get("styleId") or "").strip()
        # Normalize Excel-int-like values (e.g., '5225.0' -> '5225')
        if style_id:
            import re as _re
            m = _re.match(r"^(\d+)(?:\.0+)?$", style_id)
            if m:
                style_id = m.group(1)
        if style_id:
            handle_base = f"{handle_base}-{slugify_for_handle(style_id)}"

        article_type = (first.get("articleType") or "").strip()
        source_kind = first.get("_source_kind")
        product_category, product_type = map_from_source_kind(source_kind, article_type, raw_title)

        context = {
            "title": title,
            "product_type": product_type,
            "fabric": (first.get("Fabric") or first.get("Fabric 2") or "").strip(),
            "shape": (first.get("Shape") or "").strip(),
            "neck": (first.get("Neck") or "").strip(),
            "sleeve_length": (first.get("Sleeve Length") or "").strip(),
            "length": (first.get("Length") or "").strip(),
            "pattern": (first.get("Pattern") or first.get("Print or Pattern Type") or "").strip(),
            "occasion": (first.get("Occasion") or "").strip(),
            "color": (first.get("Prominent Colour") or "").strip(),
            "care": (first.get("Wash Care") or first.get("materialCareDescription") or "").strip(),
            "fit": (first.get("Fit") or "").strip(),
            "season": (first.get("season") or "").strip(),
            "usage": (first.get("Usage") or "").strip(),
            "brand": (llm_cfg or {}).get("brand") or os.getenv("LLM_BRAND", ""),
            "audience": (llm_cfg or {}).get("audience") or os.getenv("LLM_AUDIENCE", ""),
        }
        body_html = build_body_html(first)

        prefer_llm = bool((llm_cfg or {}).get("prefer", False))
        can_use_llm = bool(llm_cfg and llm_cfg.get("enabled"))
        within_llm_cap = (llm_max_products <= 0) or (used_llm_products < llm_max_products)
        if can_use_llm and within_llm_cap and (prefer_llm or not body_html):
            llm_html = generate_body_via_llm(handle_base, context, llm_cfg or {})
            if llm_html:
                body_html = llm_html
                used_llm_products += 1

        selling_price = (first.get("Selling Price") or first.get("Selling price") or "").strip()
        mrp = (first.get("MRP") or "").strip()
        def to_price(v):
            v = re.sub(r"[^0-9\.]+", "", v)
            return v
        price = to_price(selling_price) if selling_price else to_price(mrp)
        compare_at = to_price(mrp) if selling_price else ""

        vendor = os.getenv("VENDOR", "").strip() or "Zummer"
        # Keep Variant Inventory Qty empty as per spec
        qty_value = ""

        for idx, row in enumerate(items_kept):
            std_size = normalize_size(row.get("Standard Size") or row.get("Brand Size") or "")
            std_size = std_size.upper() if std_size else ""
            sku = (row.get("vendorSkuCode") or "").strip()

            out = {h: "" for h in ESSENTIAL_HEADERS}
            out["Handle"] = handle_base
            out["Title"] = title
            out["Body (HTML)"] = body_html
            out["Vendor"] = vendor
            out["Product Category"] = product_category
            out["Type"] = product_type
            out["Tags"] = ""
            out["Published"] = "true" if idx == 0 else ""
            out["Option1 Name"] = "Size" if idx == 0 else ""
            out["Option1 Value"] = std_size
            out["Variant SKU"] = sku
            out["Variant Grams"] = str(default_grams)
            out["Variant Inventory Tracker"] = "shopify"
            out["Variant Inventory Qty"] = qty_value
            out["Variant Inventory Policy"] = "deny"
            out["Variant Fulfillment Service"] = "manual"
            out["Variant Price"] = price
            out["Variant Compare At Price"] = compare_at
            out["Variant Requires Shipping"] = "true"
            out["Variant Taxable"] = "true"
            out["Status"] = "active" if idx == 0 else ""

            out_rows.append(out)

    return out_rows


def transform(
    input_path: Path,
    default_qty: int = 50,
    default_grams: int = 400,
    llm_cfg: dict | None = None,
    limit_products: int = 0,
    llm_max_products: int = 0,
    inventory_qty_blank: bool = False,
) -> list:
    src_all = read_any_rows(input_path)
    return transform_rows(
        src_all,
        default_qty=default_qty,
        default_grams=default_grams,
        llm_cfg=llm_cfg,
        limit_products=limit_products,
        llm_max_products=llm_max_products,
        inventory_qty_blank=inventory_qty_blank,
    )


def write_output(output_path: Path, rows: list) -> None:
    write_shopify_csv(output_path, rows, ESSENTIAL_HEADERS)
