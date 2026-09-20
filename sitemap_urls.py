from __future__ import annotations

import gzip
from typing import Iterable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests


DEFAULT_TIMEOUT = 30
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def find_urls_from_sitemap(base_url: str) -> list[str]:
    """Return all page URLs found in a website's sitemap."""
    sitemap_urls = _discover_sitemaps(base_url)
    found_urls: list[str] = []
    seen_sitemaps: set[str] = set()
    seen_pages: set[str] = set()

    for sitemap_url in sitemap_urls:
        _collect_urls_from_sitemap(
            sitemap_url=sitemap_url,
            seen_sitemaps=seen_sitemaps,
            seen_pages=seen_pages,
            found_urls=found_urls,
        )

    return found_urls


def _discover_sitemaps(base_url: str) -> list[str]:
    normalized_base_url = _normalize_base_url(base_url)
    candidates = [_robots_url(normalized_base_url), urljoin(normalized_base_url, "/sitemap.xml")]
    sitemap_urls: list[str] = []
    seen: set[str] = set()

    for sitemap_url in _read_sitemaps_from_robots(candidates[0]):
        if sitemap_url not in seen:
            sitemap_urls.append(sitemap_url)
            seen.add(sitemap_url)

    for sitemap_url in candidates[1:]:
        if sitemap_url not in seen:
            sitemap_urls.append(sitemap_url)
            seen.add(sitemap_url)

    return sitemap_urls


def _collect_urls_from_sitemap(
    sitemap_url: str,
    seen_sitemaps: set[str],
    seen_pages: set[str],
    found_urls: list[str],
) -> None:
    if sitemap_url in seen_sitemaps:
        return

    seen_sitemaps.add(sitemap_url)
    xml_text = _download_sitemap(sitemap_url)
    if not xml_text:
        return

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return

    root_name = _local_name(root.tag)
    urls = _loc_values(root)

    if root_name == "sitemapindex":
        for child_sitemap_url in urls:
            _collect_urls_from_sitemap(
                sitemap_url=child_sitemap_url,
                seen_sitemaps=seen_sitemaps,
                seen_pages=seen_pages,
                found_urls=found_urls,
            )
        return

    for page_url in urls:
        if page_url not in seen_pages:
            found_urls.append(page_url)
            seen_pages.add(page_url)


def _read_sitemaps_from_robots(robots_url: str) -> list[str]:
    try:
        response = requests.get(robots_url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return []

    sitemap_urls: list[str] = []
    for line in response.text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap":
            sitemap_url = value.strip()
            if sitemap_url:
                sitemap_urls.append(sitemap_url)

    return sitemap_urls


def _download_sitemap(sitemap_url: str) -> str | None:
    try:
        response = requests.get(sitemap_url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return None

    content = response.content
    if sitemap_url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except OSError:
            return None

    return content.decode(response.encoding or "utf-8", errors="replace")


def _loc_values(root: ElementTree.Element) -> Iterable[str]:
    for element in root.iter():
        if _local_name(element.tag) == "loc" and element.text:
            loc = element.text.strip()
            if loc:
                yield loc


def _normalize_base_url(base_url: str) -> str:
    parsed_url = urlparse(base_url)
    if not parsed_url.scheme:
        base_url = f"https://{base_url}"
        parsed_url = urlparse(base_url)

    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def _robots_url(base_url: str) -> str:
    return urljoin(base_url, "/robots.txt")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


