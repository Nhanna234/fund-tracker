"""User-managed sidebar links to other apps. Stored per user as JSON in the settings table."""
import json
from urllib.parse import urlparse

from . import db
from .config import BREADTH_URL

KEY = "links"
MAX_LINKS = 20
DEFAULT_LINKS = [{"name": "Market breadth tracker", "url": BREADTH_URL}]


def clean_url(url: str):
    """Return a normalised http(s) URL, or None if it isn't one."""
    u = (url or "").strip()
    if u and "://" not in u:
        u = "https://" + u
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc or "." not in p.netloc and p.hostname != "localhost":
        return None
    return u


def get_links(raw_settings: dict) -> list:
    """Saved links, or the default (breadth tracker) if the user has never edited the list."""
    raw = raw_settings.get(KEY)
    if raw is None:
        return [dict(l) for l in DEFAULT_LINKS]
    try:
        items = json.loads(raw)
    except Exception:
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        url = clean_url(str(it.get("url", ""))) if isinstance(it, dict) else None
        name = str(it.get("name", "")).strip() if isinstance(it, dict) else ""
        if url and name:
            out.append({"name": name[:60], "url": url})
    return out[:MAX_LINKS]


def save_links(engine, owner, links: list):
    db.set_setting(engine, owner, KEY, json.dumps(links[:MAX_LINKS]))
