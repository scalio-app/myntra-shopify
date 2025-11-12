"""
Myntra → Shopify transformer library.

This package provides modular building blocks for:
- Reading Myntra CSVs
- Mapping and normalization
- Building Body (HTML) with optional LLM
- Emitting Shopify-compatible CSV rows

Public API (stable surface under construction):
- io.read_rows, io.write_shopify_csv
- mapping.infer_category, mapping.infer_type, mapping.map_from_source_kind
- normalize.slugify_for_handle, normalize.strip_leading_brand, normalize.normalize_size, normalize.SIZE_ORDER
- describe.build_body_html, describe.generate_body_via_llm
- transform.ESSENTIAL_HEADERS, transform.transform_rows, transform.transform
"""

from . import io, mapping, normalize, describe, transform  # re-export modules

__all__ = [
    "io",
    "mapping",
    "normalize",
    "describe",
    "transform",
]

