import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from voicerhub_bot.models import GeneratedPost, Product


MAX_CAPTION_LENGTH = 950
_HASHTAG_RE = re.compile(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ_]")


def normalize_hashtag(value: str) -> str:
    cleaned = _HASHTAG_RE.sub("", value.lstrip("#").replace(" ", "_"))
    return f"#{cleaned}" if cleaned else ""


def render_caption(post: GeneratedPost, link_url: str = "") -> str:
    if post.product == Product.WAVE:
        return render_wave_caption(post)

    parts = [
        f"<b>{html.escape(plain_text(post.title))}</b>",
        sanitize_telegram_html(post.lead.strip()),
    ]
    parts.extend(
        sanitize_telegram_html(paragraph.strip())
        for paragraph in post.body
        if paragraph.strip()
    )

    if post.bullets:
        parts.append(
            "\n".join(
                f"• {sanitize_telegram_html(item.strip())}"
                for item in post.bullets
                if item.strip()
            )
        )

    cta = strip_links(sanitize_telegram_html(post.cta.strip()))
    if link_url and _safe_url(link_url):
        cta = f'<a href="{html.escape(link_url, quote=True)}">{cta}</a>'
    parts.append(cta)
    hashtags = " ".join(filter(None, (normalize_hashtag(tag) for tag in post.hashtags)))
    parts.append(hashtags)

    caption = "\n\n".join(part for part in parts if part)
    if len(caption) > MAX_CAPTION_LENGTH:
        caption = _compact_caption(parts, MAX_CAPTION_LENGTH)
    return caption


def render_wave_caption(post: GeneratedPost) -> str:
    sentences = [post.lead.strip()]
    sentences.extend(paragraph.strip() for paragraph in post.body if paragraph.strip())
    if post.cta.strip():
        sentences.append(post.cta.strip())
    body = " ".join(sentences[:4])
    caption = f"<b>{html.escape(plain_text(post.title))}</b>\n\n{html.escape(body)}"
    if len(caption) > 600:
        raise ValueError(
            f"Generated Voicer Wave caption is {len(caption)} characters; maximum is 600."
        )
    return caption


ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ins",
    "s",
    "strike",
    "del",
    "code",
    "pre",
    "blockquote",
    "tg-spoiler",
    "a",
}


class _TelegramHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = next((value for key, value in attrs if key == "href"), None)
            if not href or not _safe_url(href):
                return
            self.parts.append(f'<a href="{html.escape(href, quote=True)}">')
        else:
            self.parts.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            while self.stack:
                opened = self.stack.pop()
                self.parts.append(f"</{opened}>")
                if opened == tag:
                    break

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data))

    def result(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def sanitize_telegram_html(value: str) -> str:
    value = decode_html_markup(value)
    parser = _TelegramHTMLSanitizer()
    parser.feed(value)
    result = parser.result()
    for tag in ALLOWED_TAGS - {"a"}:
        result = re.sub(
            rf"<{tag}><{tag}>",
            f"<{tag}>",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            rf"</{tag}></{tag}>",
            f"</{tag}>",
            result,
            flags=re.IGNORECASE,
        )
    return result


def decode_html_markup(value: str) -> str:
    result = value
    for _ in range(3):
        decoded = html.unescape(result)
        if decoded == result:
            break
        result = decoded
    return result


def plain_text(value: str) -> str:
    decoded = decode_html_markup(value)
    decoded = re.sub(r"</?[A-Za-z][^>]*>", "", decoded)
    return html.unescape(decoded).strip()


def strip_links(value: str) -> str:
    return re.sub(r"</?a(?:\s+[^>]*)?>", "", value, flags=re.IGNORECASE)


def enforce_link(caption_html: str, link_url: str) -> str:
    caption = sanitize_telegram_html(caption_html.strip())
    if not link_url or not _safe_url(link_url):
        return caption
    escaped_url = html.escape(link_url, quote=True)
    if re.search(r"<a\s", caption, flags=re.IGNORECASE):
        return re.sub(
            r'(<a\s+href=")[^"]*(">)',
            lambda match: f"{match.group(1)}{escaped_url}{match.group(2)}",
            caption,
            flags=re.IGNORECASE,
        )
    return caption + f'\n\n<a href="{escaped_url}">Детальніше про продукт</a>'


def _safe_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _compact_caption(parts: list[str], limit: int) -> str:
    compact = [part for part in parts if part]
    while len(compact) > 4 and len("\n\n".join(compact)) > limit:
        compact.pop(2)
    caption = "\n\n".join(compact)
    if len(caption) <= limit:
        return caption
    if len(compact) >= 4:
        essential = "\n\n".join([compact[0], compact[1], compact[-2], compact[-1]])
        if len(essential) <= limit:
            return essential
    plain = re.sub(r"<[^>]+>", "", html.unescape(caption))
    shortened = plain[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:!? ")
    return html.escape(shortened) + "…"


def plain_text_length(caption_html: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html.unescape(caption_html)))
