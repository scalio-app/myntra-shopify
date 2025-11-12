from __future__ import annotations
from typing import Tuple


CATEGORY_MAP = {
    "dresses": "Apparel & Accessories > Clothing > Dresses",
    "dress": "Apparel & Accessories > Clothing > Dresses",
    "shirt": "Apparel & Accessories > Clothing > Clothing Tops > Shirts",
    "shirts": "Apparel & Accessories > Clothing > Clothing Tops > Shirts",
    "blouse": "Apparel & Accessories > Clothing > Clothing Tops > Blouses",
    "blouses": "Apparel & Accessories > Clothing > Clothing Tops > Blouses",
    "t-shirt": "Apparel & Accessories > Clothing > Clothing Tops > T-Shirts",
    "t-shirts": "Apparel & Accessories > Clothing > Clothing Tops > T-Shirts",
    "tee": "Apparel & Accessories > Clothing > Clothing Tops > T-Shirts",
    "polo": "Apparel & Accessories > Clothing > Clothing Tops > Polos",
    "polos": "Apparel & Accessories > Clothing > Clothing Tops > Polos",
    "tank top": "Apparel & Accessories > Clothing > Clothing Tops > Tank Tops",
    "tank tops": "Apparel & Accessories > Clothing > Clothing Tops > Tank Tops",
    "sweatshirt": "Apparel & Accessories > Clothing > Clothing Tops > Sweatshirts",
    "sweatshirts": "Apparel & Accessories > Clothing > Clothing Tops > Sweatshirts",
    "cardigan": "Apparel & Accessories > Clothing > Clothing Tops > Cardigans",
    "cardigans": "Apparel & Accessories > Clothing > Clothing Tops > Cardigans",
    "overshirt": "Apparel & Accessories > Clothing > Clothing Tops > Overshirts",
    "overshirts": "Apparel & Accessories > Clothing > Clothing Tops > Overshirts",
    "bodysuit": "Apparel & Accessories > Clothing > Clothing Tops > Bodysuits",
    "bodysuits": "Apparel & Accessories > Clothing > Clothing Tops > Bodysuits",
    "outfit sets": "Apparel & Accessories > Clothing > Outfit Sets",
    "coord": "Apparel & Accessories > Clothing > Outfit Sets",
    "co-ord": "Apparel & Accessories > Clothing > Outfit Sets",
    "co-ords": "Apparel & Accessories > Clothing > Outfit Sets",
    # Bottoms
    "jeans": "Apparel & Accessories > Clothing > Pants > Jeans",
    "jeggings": "Apparel & Accessories > Clothing > Pants > Jeggings",
    "trousers": "Apparel & Accessories > Clothing > Pants > Trousers",
    "cargo pants": "Apparel & Accessories > Clothing > Pants > Cargo Pants",
    "chinos": "Apparel & Accessories > Clothing > Pants > Chinos",
    "joggers": "Apparel & Accessories > Clothing > Pants > Joggers",
    "leggings": "Apparel & Accessories > Clothing > Pants > Leggings",
    "pants": "Apparel & Accessories > Clothing > Pants",
    # Tops umbrella
    "tops": "Apparel & Accessories > Clothing > Clothing Tops",
}

TYPE_MAP = {
    "dresses": "DRESS",
    "dress": "DRESS",
    "shirt": "Shirt",
    "shirts": "Shirt",
    "top": "Top",
    "blouse": "Top",
    "t-shirt": "T-Shirt",
    "t-shirts": "T-Shirt",
    "tee": "T-Shirt",
    "polo": "Polo",
    "polos": "Polo",
    "tank top": "Tank Top",
    "tank tops": "Tank Top",
    "sweatshirt": "Sweatshirt",
    "sweatshirts": "Sweatshirt",
    "cardigan": "Cardigan",
    "cardigans": "Cardigan",
    "overshirt": "Overshirt",
    "overshirts": "Overshirt",
    "bodysuit": "Bodysuit",
    "bodysuits": "Bodysuit",
    "outfit sets": "Co-Ord",
    "coord": "Co-Ord",
    "co-ord": "Co-Ord",
    "co-ords": "Co-Ord",
    # Bottoms
    "jeans": "Jeans",
    "jeggings": "Jeggings",
    "trousers": "Trousers",
    "cargo pants": "Cargo Pants",
    "chinos": "Chinos",
    "joggers": "Joggers",
    "leggings": "Leggings",
    "pants": "Pants",
    # Tops umbrella
    "tops": "Top",
}


def infer_category(article_type: str, title: str) -> str:
    t = (article_type or "").strip().lower()
    if t in CATEGORY_MAP:
        return CATEGORY_MAP[t]
    ttl = (title or "").lower()
    if any(k in ttl for k in ["co-ord", "co ord", "co-ords", "co ords", "coord", "coords", "outfit set", "outfit sets"]):
        return CATEGORY_MAP["co-ord"]
    if "polo" in ttl:
        return CATEGORY_MAP["polo"]
    if "t-shirt" in ttl or "tshirt" in ttl or "tee" in ttl:
        return CATEGORY_MAP["t-shirt"]
    if "shirt" in ttl:
        return CATEGORY_MAP["shirt"]
    if "blouse" in ttl:
        return CATEGORY_MAP["blouse"]
    if "dress" in ttl:
        return CATEGORY_MAP["dress"]
    return "Apparel & Accessories > Clothing"


def infer_type(article_type: str, title: str) -> str:
    t = (article_type or "").strip().lower()
    if t in TYPE_MAP:
        return TYPE_MAP[t]
    ttl = (title or "").lower()
    if any(k in ttl for k in ["co-ord", "co ord", "co-ords", "co ords", "coord", "coords", "outfit set", "outfit sets"]):
        return "Co-Ord"
    if "dress" in ttl:
        return "DRESS"
    if any(k in ttl for k in ["shirt", "t-shirt", "tshirt", "tee", "polo", "blouse", "top"]):
        return "Top"
    return (article_type or "").strip().title() or "Top"


def map_from_source_kind(source_kind: str | None, fallback_article_type: str, title: str) -> Tuple[str, str]:
    sk = (source_kind or "").strip().lower()
    if sk in CATEGORY_MAP and sk in TYPE_MAP:
        return CATEGORY_MAP[sk], TYPE_MAP[sk]
    alias = {
        "shirt": "shirt",
        "shirts": "shirt",
        "top": "tops",
        "tops": "tops",
        "dress": "dress",
        "dresses": "dress",
        "co-ord": "co-ord",
        "co-ords": "co-ords",
        "coord": "co-ord",
        "coords": "co-ords",
        "jean": "jeans",
        "jeans": "jeans",
        "jeggings": "jeggings",
        "trouser": "trousers",
        "trousers": "trousers",
        "pant": "pants",
        "pants": "pants",
    }
    tgt = alias.get(sk)
    if tgt and tgt in CATEGORY_MAP and tgt in TYPE_MAP:
        return CATEGORY_MAP[tgt], TYPE_MAP[tgt]

    ttl = (title or '').lower()
    art = (fallback_article_type or '').lower()
    def any_in(s: str, keys: list[str]) -> bool:
        return any(k in s for k in keys)

    if sk in ("tops", "top"):
        if any_in(ttl+" "+art, ["t-shirt", "tshirt", "tee"]):
            return CATEGORY_MAP["t-shirt"], TYPE_MAP["t-shirt"]
        if any_in(ttl+" "+art, ["polo"]):
            return CATEGORY_MAP["polo"], TYPE_MAP["polo"]
        if any_in(ttl+" "+art, ["tank", "tank top"]):
            return CATEGORY_MAP["tank top"], TYPE_MAP["tank top"]
        if any_in(ttl+" "+art, ["bodysuit"]):
            return CATEGORY_MAP["bodysuit"], TYPE_MAP["bodysuit"]
        if any_in(ttl+" "+art, ["cardigan"]):
            return CATEGORY_MAP["cardigan"], TYPE_MAP["cardigan"]
        if any_in(ttl+" "+art, ["sweatshirt"]):
            return CATEGORY_MAP["sweatshirt"], TYPE_MAP["sweatshirt"]
        if any_in(ttl+" "+art, ["overshirt"]):
            return CATEGORY_MAP["overshirt"], TYPE_MAP["overshirt"]
        if any_in(ttl+" "+art, ["shirt"]):
            return CATEGORY_MAP["shirt"], TYPE_MAP["shirt"]
        return CATEGORY_MAP["tops"], TYPE_MAP["top"]

    if sk in ("pants",):
        if any_in(ttl+" "+art, ["jean"]):
            return CATEGORY_MAP["jeans"], TYPE_MAP["jeans"]
        if any_in(ttl+" "+art, ["jegging"]):
            return CATEGORY_MAP["jeggings"], TYPE_MAP["jeggings"]
        if any_in(ttl+" "+art, ["trouser"]):
            return CATEGORY_MAP["trousers"], TYPE_MAP["trousers"]
        if any_in(ttl+" "+art, ["cargo"]):
            return CATEGORY_MAP["cargo pants"], TYPE_MAP["cargo pants"]
        if any_in(ttl+" "+art, ["chino"]):
            return CATEGORY_MAP["chinos"], TYPE_MAP["chinos"]
        if any_in(ttl+" "+art, ["jogger"]):
            return CATEGORY_MAP["joggers"], TYPE_MAP["joggers"]
        if any_in(ttl+" "+art, ["legging"]):
            return CATEGORY_MAP["leggings"], TYPE_MAP["leggings"]
        return CATEGORY_MAP["pants"], TYPE_MAP["pants"]

    from .mapping import infer_category as _infer_category, infer_type as _infer_type
    return _infer_category(fallback_article_type, title), _infer_type(fallback_article_type, title)

