from __future__ import annotations
import re
from pathlib import Path
from typing import List, Optional


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def list_images(images_dir: Path) -> List[Path]:
    if not images_dir.exists() or not images_dir.is_dir():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")
    files: List[Path] = []
    for p in images_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
    return files


def list_images_shallow(images_dir: Path) -> List[Path]:
    if not images_dir.exists() or not images_dir.is_dir():
        raise FileNotFoundError(f"Images directory not found: {images_dir}")
    files: List[Path] = []
    for p in images_dir.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
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
        candidate: Optional[Path] = None
        if parent_depth and parent_depth > 0:
            cur = path
            for _ in range(parent_depth):
                cur = cur.parent
            candidate = cur
        else:
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


def base_from_variant_sku(sku: str) -> str:
    return re.sub(r"[A-Za-z]+$", "", sku or "")

