from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .config import MEDIA_TAG_ATTRS
from .models import Activity, Section
from .utils import (
    activity_type,
    clean_text,
    is_probably_file_url,
    is_same_lms,
    normalize_url,
)


def get_course_name(soup: BeautifulSoup) -> str:
    for selector in (".page-header-headings h1", "#page-header h1", "header h1", "h1"):
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            text = re.sub(r"^Khóa:\s*", "", text, flags=re.I)
            if text:
                return text

    if soup.title:
        text = clean_text(soup.title.get_text(" ", strip=True))
        text = re.sub(r"^Khóa:\s*", "", text, flags=re.I)
        text = re.sub(r"\s*\|\s*BK-LMS\s*$", "", text, flags=re.I)
        if text:
            return text
    return "BK-LMS Course"


def clean_section_title(text: str, index: int) -> str:
    text = clean_text(text)
    text = re.sub(r"\bThu gọn toàn bộ\b", "", text, flags=re.I)
    text = re.sub(r"\bMở rộng tất cả\b", "", text, flags=re.I)
    text = re.sub(r"\bSelect section\b", "", text, flags=re.I)
    text = clean_text(text)
    return text or ("Chung" if index == 0 else f"Section {index}")


def section_title(node, index: int) -> str:
    for selector in (
        "[data-for='section_title']", ".sectionname",
        ".course-section-header h2", ".course-section-header h3", "h2", "h3"
    ):
        item = node.select_one(selector)
        if not item:
            continue
        clone = BeautifulSoup(str(item), "html.parser")
        for hidden in clone.select(
            ".accesshide, .sr-only, [aria-hidden='true'], button, .section_action_menu"
        ):
            hidden.decompose()
        text = clean_section_title(clone.get_text(" ", strip=True), index)
        if text:
            return text
    return "Chung" if index == 0 else f"Section {index}"


def activity_name(anchor) -> str:
    item = anchor.select_one(".instancename") or anchor
    clone = BeautifulSoup(str(item), "html.parser")
    for hidden in clone.select(".accesshide, .sr-only, [aria-hidden='true']"):
        hidden.decompose()
    return clean_text(clone.get_text(" ", strip=True)) or "Tài liệu"


def find_section_nodes(soup: BeautifulSoup):
    nodes = []
    seen_keys = set()
    for selector in (
        "li.course-section", "section.course-section", "div.course-section", "li.section.main"
    ):
        for node in soup.select(selector):
            key = (node.get("id"), node.get("data-sectionid"), str(node.get("class")))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            nodes.append(node)
    if not nodes:
        nodes = [soup.select_one("main") or soup]
    return nodes


def parse_sections(html: str, base_url: str) -> tuple[str, list[Section]]:
    soup = BeautifulSoup(html, "html.parser")
    course_name = get_course_name(soup)
    sections: list[Section] = []

    for seq, node in enumerate(find_section_nodes(soup)):
        title = section_title(node, seq)
        activities: list[Activity] = []
        known = set()

        activity_anchors = node.select(
            ".activity a[href], li.activity a[href], [data-for='cmitem'] a[href]"
        )
        if not activity_anchors:
            activity_anchors = node.select("a[href]")

        for a in activity_anchors:
            href = a.get("href")
            if not href:
                continue
            url = normalize_url(urljoin(base_url, href))
            mod = activity_type(url)
            if mod == "other" or url in known:
                continue
            known.add(url)
            activities.append(Activity(len(activities) + 1, activity_name(a), url, mod))

        sections.append(Section(seq, title, str(node), activities))
    return course_name, sections


def choose_content_root(soup: BeautifulSoup):
    for selector in (
        ".box.generalbox", "[data-region='content']", "#region-main .course-content",
        "#region-main", "main[role='main']", "main", "[role='main']",
    ):
        node = soup.select_one(selector)
        if node:
            return node
    return soup.body or soup


def sanitize_content_html(node, base_url: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    clone = BeautifulSoup(str(node), "html.parser")
    for x in clone.select(
        "script, style, noscript, nav, header, footer, aside, form, button, input, "
        "textarea, select, svg, .breadcrumb, [class*='breadcrumb'], .drawer, "
        ".secondary-navigation, .activity-navigation, .action-menu, .dropdown-menu"
    ):
        x.decompose()

    media_links: list[tuple[str, str]] = []
    media_seen = set()
    content_links: list[str] = []
    link_seen = set()

    for a in clone.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        abs_url = normalize_url(urljoin(base_url, href))
        a["href"] = abs_url
        label = clean_text(a.get_text(" ", strip=True)) or "Tài liệu"
        if is_probably_file_url(abs_url):
            if abs_url not in media_seen:
                media_seen.add(abs_url)
                media_links.append((label, abs_url))
        elif abs_url not in link_seen:
            link_seen.add(abs_url)
            content_links.append(abs_url)

    for tag_name, attr in MEDIA_TAG_ATTRS.items():
        for tag in clone.select(f"{tag_name}[{attr}]"):
            src = tag.get(attr)
            if not src or src.startswith("data:"):
                continue
            abs_url = normalize_url(urljoin(base_url, src))
            tag[attr] = abs_url
            label = (
                tag.get("alt") or tag.get("title")
                or Path(unquote(urlparse(abs_url).path)).name or tag_name
            )
            if abs_url not in media_seen:
                media_seen.add(abs_url)
                media_links.append((clean_text(label), abs_url))

    body_html = str(clone)
    html_doc = f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: Arial, sans-serif; line-height: 1.55; max-width: 1100px; margin: 32px auto; padding: 0 20px; }}
img, video {{ max-width: 100%; height: auto; }}
pre, code {{ white-space: pre-wrap; }}
table {{ border-collapse: collapse; max-width: 100%; }}
td, th {{ border: 1px solid #bbb; padding: 6px; }}
</style>
</head>
<body>
<p><small>Nguồn: <a href="{base_url}">{base_url}</a></small></p>
{body_html}
</body>
</html>
"""
    return html_doc, media_links, content_links


def extract_section_content(
    node_html: str, base_url: str
) -> tuple[Optional[str], list[tuple[str, str]], list[str]]:
    soup = BeautifulSoup(node_html, "html.parser")
    for x in soup.select(".activity, li.activity, [data-for='cmitem']"):
        x.decompose()
    for x in soup.select(
        ".course-section-header, .sectionname, [data-for='section_title'], "
        ".section_action_menu, button, nav"
    ):
        x.decompose()

    text = clean_text(soup.get_text(" ", strip=True))
    has_media = bool(soup.select("img[src], video[src], audio[src], source[src], a[href]"))
    if not text and not has_media:
        return None, [], []
    return sanitize_content_html(soup, base_url)
