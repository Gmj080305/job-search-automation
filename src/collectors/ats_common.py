"""Shared helpers for public ATS career-site collectors."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def clean_html(value: object) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def absolute_url(base: str, href: object) -> str:
    return urljoin(base, str(href or "").strip())


def same_https_host(url: str, host: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == host
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def jsonld_objects(html: str):
    """Yield JSON-LD objects from script tags without requiring @type=JobPosting."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.get_text(strip=True)
        if not text:
            continue
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            # One malformed JSON-LD block should not make the whole page unusable.
            continue


def iter_job_postings(value: object):
    if isinstance(value, list):
        for item in value:
            yield from iter_job_postings(item)
    elif isinstance(value, dict):
        raw_type = value.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(t).rstrip("/").split("/")[-1] == "JobPosting" for t in types):
            yield value
        graph = value.get("@graph")
        if isinstance(graph, (list, dict)):
            yield from iter_job_postings(graph)


def first_text(*values: object) -> str:
    for value in values:
        text = clean_html(value)
        if text:
            return text
    return ""


def extract_address(location: object) -> tuple[str, str | None]:
    if isinstance(location, list):
        location = location[0] if location else {}
    if not isinstance(location, dict):
        return clean_html(location), None

    address = location.get("address", location)
    if isinstance(address, str):
        return clean_html(address), None
    if not isinstance(address, dict):
        return "", None

    city = first_text(address.get("addressLocality")) or None
    parts = [
        city or "",
        first_text(address.get("addressRegion")),
        first_text(address.get("addressCountry")),
    ]
    return ", ".join(p for p in parts if p), city


def looks_like_job_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return bool(
        re.search(r"/(?:jobs?|job)/\d+(?:/|$)", path)
        or re.search(r"/job/[^/]+", path)
    )
