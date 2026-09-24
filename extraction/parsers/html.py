"""Extract readable article content from HTML using a readability-style heuristic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, Tag

_BOILERPLATE_SELECTORS = [
    "script", "style", "noscript", "template",
    "nav", "aside", "footer", "header",
    "form", "iframe", "svg",
]

_ARTICLE_HINTS = ["article", "main", "content", "post", "story", "entry", "body"]


@dataclass
class ParsedArticle:
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    text: str = ""
    canonical_url: Optional[str] = None
    language: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


def _meta(soup: BeautifulSoup, *, name: Optional[str] = None, prop: Optional[str] = None) -> Optional[str]:
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _node_score(node: Tag) -> float:
    text = node.get_text(" ", strip=True)
    length = len(text)
    if length == 0:
        return 0.0
    # Weight by paragraph density and length, penalize links.
    paragraphs = node.find_all("p")
    link_text_len = sum(len(a.get_text(strip=True)) for a in node.find_all("a"))
    link_ratio = link_text_len / max(length, 1)
    return (length * (1.0 + len(paragraphs) * 0.1)) * (1.0 - min(link_ratio, 0.9))


def _best_container(soup: BeautifulSoup) -> Tag:
    # Prefer semantic containers when reasonable.
    for selector in ("article", "main", "[role=main]"):
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 400:
            return node

    # Score a pool of candidate containers.
    candidates: List[Tag] = []
    for tag in soup.find_all(["article", "section", "div"]):
        classes = " ".join(tag.get("class") or []).lower()
        ident = (tag.get("id") or "").lower()
        if any(h in classes or h in ident for h in _ARTICLE_HINTS):
            candidates.append(tag)
    if not candidates:
        candidates = soup.find_all("div") or [soup.body or soup]

    best = max(candidates, key=_node_score)
    return best


def parse_html(html: str, *, url: Optional[str] = None) -> ParsedArticle:
    soup = BeautifulSoup(html, "lxml")

    for selector in _BOILERPLATE_SELECTORS:
        for node in soup.find_all(selector):
            node.decompose()

    title = (
        _meta(soup, prop="og:title")
        or _meta(soup, name="twitter:title")
        or (soup.title.get_text(strip=True) if soup.title else None)
    )
    author = (
        _meta(soup, name="author")
        or _meta(soup, prop="article:author")
    )
    published_at = (
        _meta(soup, prop="article:published_time")
        or _meta(soup, name="pubdate")
        or _meta(soup, name="publishdate")
        or _meta(soup, name="date")
    )
    language = soup.html.get("lang") if soup.html else None
    canonical_url = None
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if canonical_tag and canonical_tag.get("href"):
        canonical_url = canonical_tag["href"].strip()

    container = _best_container(soup)
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    text = "\n\n".join(paragraphs)

    if not text:
        # Fallback: raw text from container.
        text = container.get_text("\n", strip=True)

    return ParsedArticle(
        title=title,
        author=author,
        published_at=published_at,
        text=text,
        canonical_url=canonical_url,
        language=language,
    )