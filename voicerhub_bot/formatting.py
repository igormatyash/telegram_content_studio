from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse


ALLOWED_PREVIEW_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "br",
    "code",
    "pre",
    "a",
    "blockquote",
}
BLOCKED_WITH_CONTENT = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "svg",
}


def _safe_preview_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https", "mailto"}


class _PreviewSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in BLOCKED_WITH_CONTENT:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in ALLOWED_PREVIEW_TAGS:
            return
        if tag == "br":
            self.parts.append("<br>")
            return
        if tag == "a":
            href = next((value for key, value in attrs if key == "href"), "")
            if not href or not _safe_preview_url(href):
                return
            self.parts.append(
                f'<a href="{html.escape(href, quote=True)}" '
                'target="_blank" rel="noopener noreferrer">'
            )
        else:
            self.parts.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in BLOCKED_WITH_CONTENT and self.blocked_depth:
            self.blocked_depth -= 1
            return
        if self.blocked_depth or tag not in self.stack:
            return
        while self.stack:
            opened = self.stack.pop()
            self.parts.append(f"</{opened}>")
            if opened == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(html.escape(data))

    def result(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def sanitize_preview_html(value: str) -> str:
    parser = _PreviewSanitizer()
    parser.feed(html.unescape(value or ""))
    return parser.result()


def strip_formatting(value: str) -> str:
    sanitized = sanitize_preview_html(value)
    collector = _TextCollector()
    collector.feed(sanitized)
    return " ".join("".join(collector.parts).split())


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")
