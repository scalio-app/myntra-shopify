from __future__ import annotations
import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests


@dataclass
class ShopifyConfig:
    store: str
    token: str
    api_version: str = "2024-07"

    @property
    def base_url(self) -> str:
        return f"https://{self.store}/admin/api/{self.api_version}"


def build_session(cfg: ShopifyConfig) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "X-Shopify-Access-Token": cfg.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "myntra-shopify/1.0",
        }
    )
    return s


def _rest_post(session: requests.Session, url: str, payload: Dict) -> requests.Response:
    backoff = 1.0
    while True:
        resp = session.post(url, data=json.dumps(payload))
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            time.sleep(retry_after)
            backoff = min(backoff * 2, 10.0)
            continue
        return resp


def _rest_get(session: requests.Session, url: str) -> requests.Response:
    backoff = 1.0
    while True:
        resp = session.get(url)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            time.sleep(retry_after)
            backoff = min(backoff * 2, 10.0)
            continue
        return resp


def graphql(session: requests.Session, cfg: ShopifyConfig, query: str, variables: Dict) -> Dict:
    url = f"https://{cfg.store}/admin/api/{cfg.api_version}/graphql.json"
    backoff = 1.0
    payload = {"query": query, "variables": variables}
    while True:
        resp = session.post(url, data=json.dumps(payload))
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            time.sleep(retry_after)
            backoff = min(backoff * 2, 10.0)
            continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise requests.HTTPError(f"GraphQL error: {data['errors']}")
        return data


def find_variants_by_sku(session: requests.Session, cfg: ShopifyConfig, sku: str) -> List[Dict]:
    gql_url = f"https://{cfg.store}/admin/api/{cfg.api_version}/graphql.json"
    query = {
        "query": (
            "query($q:String!){"
            " productVariants(first:50, query:$q){"
            "  edges{ node{ id sku product{ id } } }"
            " }"
            "}"
        ),
        "variables": {"q": f"sku:{sku}"},
    }

    def _gid_to_int(gid: str) -> int:
        try:
            return int(gid.rsplit("/", 1)[-1])
        except Exception:
            return int(gid)

    backoff = 1.0
    while True:
        resp = session.post(gql_url, data=json.dumps(query))
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            time.sleep(retry_after)
            backoff = min(backoff * 2, 10.0)
            continue
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors") or data.get("error")
        if errors:
            raise requests.HTTPError(f"GraphQL error: {errors}")
        edges = (((data.get("data") or {}).get("productVariants") or {}).get("edges")) or []
        out: List[Dict] = []
        for e in edges:
            node = e.get("node") or {}
            v_gid = node.get("id")
            p_gid = (node.get("product") or {}).get("id")
            if not v_gid or not p_gid:
                continue
            out.append(
                {
                    "id": _gid_to_int(v_gid),
                    "product_id": _gid_to_int(p_gid),
                    "sku": node.get("sku"),
                }
            )
        return out


def fetch_all_products_with_variants(session: requests.Session, cfg: ShopifyConfig) -> List[Dict]:
    # Returns a list of {product_id:int, variant_skus:[str], variant_ids:[int]}
    def _gid_to_int(gid: str) -> int:
        try:
            return int(gid.rsplit("/", 1)[-1])
        except Exception:
            return int(gid)

    query = (
        "query($cursor:String){"
        " products(first:100, after:$cursor){"
        "  pageInfo{ hasNextPage endCursor }"
        "  edges{ cursor node{ id variants(first:100){ edges{ node{ id sku } } } } }"
        " }"
        "}"
    )
    cursor: Optional[str] = None
    results: List[Dict] = []
    while True:
        data = graphql(session, cfg, query, {"cursor": cursor})
        products = ((data.get("data") or {}).get("products") or {})
        edges = products.get("edges") or []
        for e in edges:
            node = (e.get("node") or {})
            p_gid = node.get("id")
            if not p_gid:
                continue
            p_id = _gid_to_int(p_gid)
            v_edges = (((node.get("variants") or {}).get("edges")) or [])
            skus: List[str] = []
            v_ids: List[int] = []
            for ve in v_edges:
                v = ve.get("node") or {}
                if v.get("sku"):
                    skus.append(str(v.get("sku")))
                if v.get("id"):
                    v_ids.append(_gid_to_int(v.get("id")))
            results.append({"product_id": p_id, "variant_skus": skus, "variant_ids": v_ids})
        if products.get("pageInfo", {}).get("hasNextPage"):
            cursor = products.get("pageInfo", {}).get("endCursor")
        else:
            break
    return results


def get_product_images(session: requests.Session, cfg: ShopifyConfig, product_id: int) -> List[Dict]:
    url = f"{cfg.base_url}/products/{product_id}/images.json"
    resp = _rest_get(session, url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("images", [])


def get_product_info(session: requests.Session, cfg: ShopifyConfig, product_id: int) -> Dict:
    url = f"{cfg.base_url}/products/{product_id}.json"
    resp = _rest_get(session, url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("product") or {}


def get_shop_info(session: requests.Session, cfg: ShopifyConfig) -> Dict:
    """Fetch basic shop info to verify credentials and store identity."""
    url = f"{cfg.base_url}/shop.json"
    resp = _rest_get(session, url)
    resp.raise_for_status()
    data = resp.json() or {}
    return data.get("shop") or {}


def staged_uploads_create(session: requests.Session, cfg: ShopifyConfig, files: List[Dict]) -> List[Dict]:
    """Request staged upload targets from Shopify for direct browser uploads.

    files: list of {filename, mimeType, fileSize}
    Returns list of {url, resourceUrl, parameters: [{name,value}]} in the same order.
    """
    mutation = (
        "mutation stagedUploadsCreate($input:[StagedUploadInput!]!){"
        " stagedUploadsCreate(input:$input){"
        "  stagedTargets{ url resourceUrl parameters{ name value } }"
        "  userErrors{ field message }"
        " }"
        "}"
    )
    # Prepare inputs
    inputs = []
    for f in files:
        inputs.append({
            "resource": "IMAGE",
            "filename": f.get("filename"),
            "mimeType": f.get("mimeType", "image/jpeg"),
            "httpMethod": "POST",
            "fileSize": int(f.get("fileSize") or 0),
        })
    data = graphql(session, cfg, mutation, {"input": inputs})
    out = (((data.get("data") or {}).get("stagedUploadsCreate") or {}).get("stagedTargets") or [])
    # Map parameters array into dict for convenience on client
    results: List[Dict] = []
    for i, t in enumerate(out):
        params = {p.get("name"): p.get("value") for p in (t.get("parameters") or [])}
        results.append({
            "url": t.get("url"),
            "resourceUrl": t.get("resourceUrl"),
            "parameters": params,
            "filename": files[i].get("filename"),
            "mimeType": files[i].get("mimeType"),
        })
    return results


def upload_image_from_src(session: requests.Session, cfg: ShopifyConfig, product_id: int, src_url: str, filename: str = "", alt_text: str | None = None, variant_id: int | None = None) -> Dict:
    """Attach an image by URL (Shopify will fetch the image)."""
    url = f"{cfg.base_url}/products/{product_id}/images.json"
    payload: Dict[str, object] = {
        "image": {
            "src": src_url,
            "filename": filename,
        }
    }
    if alt_text:
        payload["image"]["alt"] = alt_text  # type: ignore[index]
    if variant_id:
        payload["image"]["variant_ids"] = [variant_id]  # type: ignore[index]
    resp = _rest_post(session, url, payload)
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise requests.HTTPError(f"{resp.status_code}: {detail}")
    return resp.json().get("image", {})


def upload_image_to_product(
    session: requests.Session,
    cfg: ShopifyConfig,
    product_id: int,
    image_b64: str,
    filename: str,
    alt_text: Optional[str] = None,
    variant_id: Optional[int] = None,
    position: Optional[int] = None,
) -> Dict:
    url = f"{cfg.base_url}/products/{product_id}/images.json"
    payload: Dict[str, object] = {"image": {"attachment": image_b64, "filename": filename}}
    if alt_text:
        payload["image"]["alt"] = alt_text  # type: ignore[index]
    if variant_id:
        payload["image"]["variant_ids"] = [variant_id]  # type: ignore[index]
    if position:
        payload["image"]["position"] = position  # type: ignore[index]
    resp = _rest_post(session, url, payload)
    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise requests.HTTPError(f"{resp.status_code}: {detail}")
    return resp.json().get("image", {})
