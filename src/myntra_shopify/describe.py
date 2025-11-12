from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List


def csv_html_escape(s: str) -> str:
    s = str(s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def build_body_html(row: dict) -> str:
    from .normalize import strip_leading_brand

    parts = []
    for key in [
        "Product Details",
        "styleNote",
        "materialCareDescription",
        "sizeAndFitDescription",
    ]:
        val = row.get(key) or ""
        val = str(val).strip()
        if val:
            parts.append(strip_leading_brand(val, brand=os.getenv("BRAND_STRIP_VALUE", "zummer")))
    if not parts:
        fabric = (row.get("Fabric") or row.get("Fabric 2") or "").strip()
        shape = (row.get("Shape") or "").strip()
        neck = (row.get("Neck") or "").strip()
        sleeve = (row.get("Sleeve Length") or "").strip()
        length = (row.get("Length") or "").strip()
        pattern = (row.get("Pattern") or row.get("Print or Pattern Type") or "").strip()
        attrs = [fabric, shape, neck, sleeve, length, pattern]
        desc = ", ".join([a for a in attrs if a])
        if desc:
            parts.append(desc)
    if not parts:
        return ""
    html = "".join([f"<p>{csv_html_escape(p)}</p>" for p in parts])
    return html


# --- Optional LLM integration (OpenAI-compatible) ---
def build_llm_messages(context: Dict) -> List[Dict]:
    brand_name = context.get("brand") or os.getenv("LLM_BRAND", "")
    ban_brand = f"Do not mention the brand name ({brand_name}) in your output." if brand_name else "Do not mention any brand name in your output."
    system = (
        "/no_think You are an expert high-quality fashion ecommerce copywriter for Shopify."
        "Write one HTML paragraph (<p>...</p>) containing 3–5 short lines separated by <br>."
        "Keep the tone fresh, playful, conversational, and never too salesy."
        f"{ban_brand}"
        "Return ONLY the final HTML paragraph of 3-5 lines as the output. Do NOT include any analysis, planning, or explanations other than the final HTML paragraph. Whatever you finally output will go into the Body (HTML) field of the Shopify product and read my real customers."
    )
    attrs = []
    for key in [
        "title", "product_type", "fabric", "shape", "neck", "sleeve_length",
        "length", "pattern", "occasion", "color", "care", "fit", "season", "usage",
        "brand", "audience",
    ]:
        val = context.get(key)
        if val:
            attrs.append(f"{key}: {val}")
    attr_text = "\n".join(attrs)
    user = (
        "Write a 3–5 line Shopify product description (Body HTML) based on the following product details.\n"
        f"{attr_text}\n"
        "Constraints:\n"
        "- Use the Title above as context; do not repeat it verbatim.\n"
        "- Output ONE <p> block only, with each line separated by <br>.\n"
        "- Tone: fresh, playful, conversational (not too salesy).\n"
        "- Focus: fabric, fit, key design details (neckline, sleeve, length).\n"
        "- Include how it suits vacations, brunches, kitty parties, or casual outings.\n"
        "- Make it trendy yet wearable every day.\n"
        "- End with a fun, friendly styling or usage tip as the final line.\n"
        "- Do not start with the brand name.\n"
        "- IMPORTANT: Return ONLY the final <p>...</p> block; no analysis or extra text."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _http_post_json(url: str, payload: dict, api_key: str = "", timeout: int = 30) -> dict | None:
    import urllib.request
    import urllib.error

    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body.decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception):
        return None


def _call_chat(base_url: str, api_key: str, model: str, messages: list, temperature: float = 0.7, max_tokens: int = 250, timeout: int = 30) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    parsed = _http_post_json(url, payload, api_key=api_key, timeout=timeout)
    if not parsed:
        return ""
    return (parsed.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()


def _call_completions(base_url: str, api_key: str, model: str, prompt: str, temperature: float = 0.7, max_tokens: int = 250, timeout: int = 30) -> str:
    url = base_url.rstrip("/") + "/v1/completions"
    payload = {"model": model, "prompt": prompt, "temperature": temperature, "max_tokens": max_tokens}
    parsed = _http_post_json(url, payload, api_key=api_key, timeout=timeout)
    if not parsed:
        return ""
    choices = parsed.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("text") or "").strip()


def generate_body_via_llm(handle: str, context: dict, cfg: dict) -> str:
    if not cfg or not cfg.get("enabled"):
        return ""

    cache_dir = cfg.get("cache_dir")
    refresh = bool(cfg.get("refresh"))
    if cache_dir and not refresh:
        cache_path = Path(cache_dir) / f"{handle}.html"
        if cache_path.exists():
            try:
                return cache_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass

    messages = build_llm_messages(context)

    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        key_file = (cfg.get("api_key_file") or "").strip()
        if key_file:
            try:
                api_key = Path(key_file).read_text(encoding="utf-8").strip()
            except Exception:
                api_key = ""
    if not api_key:
        api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), "").strip()

    base_url = (cfg.get("base_url") or "https://api.openai.com").strip()
    endpoint = (cfg.get("endpoint") or "chat").strip()

    is_local = base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")
    if not api_key and not is_local:
        return ""

    model = cfg.get("model", "gpt-4o-mini")
    temperature = float(cfg.get("temperature", 0.7))
    max_tokens = int(cfg.get("max_tokens", 250))
    timeout = int(cfg.get("timeout", 30))

    if endpoint == "completions":
        sys_txt = "\n".join([m["content"] for m in messages if m.get("role") == "system"]).strip()
        usr_txt = "\n".join([m["content"] for m in messages if m.get("role") == "user"]).strip()
        prompt = (sys_txt + "\n\n" + usr_txt).strip()
        html = _call_completions(base_url, api_key, model, prompt, temperature, max_tokens, timeout)
    else:
        html = _call_chat(base_url, api_key, model, messages, temperature, max_tokens, timeout)

    html = (html or "").strip()
    if html:
        lower = html.lower()
        if "<p" in lower:
            try:
                paras = re.findall(r"(?is)<p[^>]*>.*?</p>", html)
                if paras:
                    html = paras[-1].strip()
            except Exception:
                pass
        else:
            html = csv_html_escape(html).replace("\n", "<br>")
            html = f"<p>{html}</p>"

    if html and cache_dir:
        try:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            (Path(cache_dir) / f"{handle}.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
    time.sleep(float(cfg.get("rate_sleep", 0)))
    return html
