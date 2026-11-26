"""Free Wikimedia Commons documentary still-image source with licence provenance."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import html

API = "https://commons.wikimedia.org/w/api.php"
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
USER_AGENT = "SINTU-AI-YOUTUBE-STUDIO/1.0 (documentary media sourcing; contact: project maintainers)"


class CommonsImageUnavailable(Exception):
    """No safely licensed and downloadable Commons image matched the scene."""


def _request(url: str, *, timeout: int = 20, limit: int = MAX_DOWNLOAD_BYTES) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_host = urllib.parse.urlparse(response.geturl()).hostname or ""
        if final_host not in {"commons.wikimedia.org", "upload.wikimedia.org"}:
            raise CommonsImageUnavailable("Commons redirected to an untrusted host.")
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise CommonsImageUnavailable("Commons image response was empty or exceeded the size limit.")
    return data


def _plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def _is_reusable_license(name: str) -> bool:
    """Allow commercial reuse and adaptations; reject NC/ND licences."""
    normalized = re.sub(r"\s+", " ", (name or "").strip()).lower()
    if re.search(r"\b(nc|non[- ]commercial|nd|no[- ]derivatives)\b", normalized):
        return False
    return bool(
        re.fullmatch(r"cc0(?: 1\.0)?", normalized)
        or re.fullmatch(r"cc by(?:-sa)?(?: 2\.0| 2\.5| 3\.0| 4\.0)?", normalized)
        or re.fullmatch(r"public domain", normalized)
        or re.fullmatch(r"pd[- ][a-z0-9 .-]+", normalized)
    )


def fetch_documentary_image(query: str) -> tuple[bytes, dict]:
    """Find a Commons file with an explicit reusable licence and download it."""
    words = re.findall(r"[\w-]+", query, flags=re.UNICODE)
    search = " ".join(words[:14]).strip()
    if len(search) < 3:
        raise CommonsImageUnavailable("Documentary image search query is too short.")
    params = urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": f"filetype:bitmap {search}", "gsrnamespace": 6,
        "gsrlimit": 15, "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": 1600,
        "format": "json", "formatversion": 2,
    })
    try:
        payload = json.loads(_request(f"{API}?{params}", limit=2 * 1024 * 1024))
    except (OSError, ValueError, TimeoutError) as exc:
        raise CommonsImageUnavailable(f"Wikimedia Commons search failed ({type(exc).__name__}).") from None
    pages = payload.get("query", {}).get("pages", [])
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        licence = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        if not _is_reusable_license(licence):
            continue
        image_url = info.get("thumburl") or info.get("url") or ""
        parsed = urllib.parse.urlparse(image_url)
        if parsed.scheme != "https" or parsed.hostname != "upload.wikimedia.org":
            continue
        try:
            raw = _request(image_url)
        except (OSError, CommonsImageUnavailable, TimeoutError):
            continue
        attribution = {
            "provider": "Wikimedia Commons",
            "title": _plain(page.get("title", "")),
            "source_url": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(page.get("title", "").replace(" ", "_")),
            "file_url": image_url,
            "license": licence,
            "license_url": _plain((meta.get("LicenseUrl") or {}).get("value", "")),
            "artist": _plain((meta.get("Artist") or {}).get("value", "")),
            "credit": _plain((meta.get("Credit") or {}).get("value", "")),
            "attribution_required": bool((meta.get("AttributionRequired") or {}).get("value", "").lower() == "true"),
            "search_query": search,
        }
        return raw, attribution
    raise CommonsImageUnavailable("No matching Commons image with an explicit reusable licence was found.")