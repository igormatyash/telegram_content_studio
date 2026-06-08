import asyncio
import html
import ipaddress
import re
import socket
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from openai import AsyncOpenAI

from voicerhub_bot.config import Settings
from voicerhub_bot.models import SocialPost
from voicerhub_bot.rendering import MAX_CAPTION_LENGTH, sanitize_telegram_html


TONE_GUIDANCE = {
    "expert": "Експертний: точний, структурований, спокійний, з практичним висновком.",
    "sales": "Продаючий: фокус на бізнес-користі та м'якому заклику до дії без тиску.",
    "light": "Легкий: прості речення, жива аналогія, теплий тон без фамільярності.",
    "news": "Новинний: головний факт на початку, контекст і значення для бізнесу.",
}

SOCIAL_PLATFORM_RULES = {
    "instagram": {
        "label": "Instagram",
        "text": "Живий текст до 1800 символів, сильний перший рядок, короткі абзаци, доречні emoji, до 10 хештегів. Не використовуй HTML.",
        "api_size": "1024x1536",
        "output_size": (1080, 1350),
    },
    "linkedin": {
        "label": "LinkedIn",
        "text": "Професійний текст до 2200 символів: теза, практичний контекст, висновок і м'який CTA. До 5 хештегів. Не використовуй HTML.",
        "api_size": "1536x1024",
        "output_size": (1200, 627),
    },
    "facebook": {
        "label": "Facebook",
        "text": "Зрозумілий текст до 2000 символів, розмовний вступ, користь, короткий CTA, до 5 хештегів. Не використовуй HTML.",
        "api_size": "1536x1024",
        "output_size": (1200, 630),
    },
    "x": {
        "label": "X",
        "text": "Один самодостатній допис до 260 символів разом із хештегами. Один чіткий факт або висновок. Не використовуй HTML.",
        "api_size": "1536x1024",
        "output_size": (1600, 900),
    },
}


def normalize_terminology(value: str) -> str:
    replacements = {
        r"\bTony\b": "TONY",
        r"\bТоні\b": "TONY",
        r"\bVoicerhub\b": "VoicerHub",
        r"\bVoiceHub\b": "VoicerHub",
        r"\bВойсерхаб\b": "VoicerHub",
        r"\bPowerBi\b": "Power BI",
        r"\bGoogle maps\b": "Google Maps",
    }
    chunks = re.split(r"(https?://[^\s\"'<>]+)", value)
    for index in range(0, len(chunks), 2):
        for pattern, replacement in replacements.items():
            chunks[index] = re.sub(
                pattern,
                replacement,
                chunks[index],
                flags=re.IGNORECASE,
            )
    return "".join(chunks)


def visible_length(value: str) -> int:
    return len(re.sub(r"<[^>]+>", "", html.unescape(value)))


def shorten_caption(value: str, limit: int = MAX_CAPTION_LENGTH) -> str:
    value = sanitize_telegram_html(normalize_terminology(value)).strip()
    if visible_length(value) <= limit:
        return value
    blocks = [block.strip() for block in value.split("\n\n") if block.strip()]
    while len(blocks) > 3 and visible_length("\n\n".join(blocks)) > limit:
        blocks.pop(-2)
    value = "\n\n".join(blocks)
    if visible_length(value) <= limit:
        return value
    plain = re.sub(r"<[^>]+>", "", value)
    shortened = plain[: max(80, limit - 1)].rsplit(" ", 1)[0].rstrip(".,;:!? ")
    return html.escape(shortened) + "…"


def similarity_score(left: str, right: str) -> float:
    left_norm = _normalize(left)
    right_norm = _normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    containment = (
        len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    fuzzy_matches = sum(
        1
        for token in left_tokens
        if any(SequenceMatcher(None, token, other).ratio() >= 0.72 for other in right_tokens)
    )
    fuzzy_containment = (
        fuzzy_matches / min(len(left_tokens), len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    return round(
        max(sequence * 0.75, jaccard, containment * 0.85, fuzzy_containment * 0.9),
        3,
    )


def closest_duplicate(title: str, angle: str, existing: list[dict]) -> tuple[float, int | None]:
    candidate = f"{title} {angle}"
    best = (0.0, None)
    for item in existing:
        score = similarity_score(
            candidate,
            f"{item.get('title', '')} {item.get('angle', '')}",
        )
        if score > best[0]:
            best = (score, item.get("id"))
    return best


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.capture_json = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            content = attributes.get("content", "")
            if len(content) > 20:
                self.parts.append(content)
            return
        if tag == "script" and (
            "json" in attributes.get("type", "")
            or attributes.get("id") in {"__NEXT_DATA__", "__NUXT_DATA__"}
        ):
            self.capture_json += 1
        elif tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.capture_json:
            self.capture_json -= 1
        elif tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_json:
            decoded = re.sub(r"\\u[0-9a-fA-F]{4}", " ", data)
            text = " ".join(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9][^\"{}\[\]]{3,}", decoded))
            if text:
                self.parts.append(text)
        elif not self.skip:
            text = " ".join(data.split())
            if len(text) > 2:
                self.parts.append(text)


async def fetch_page_text(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=False,
        headers={"User-Agent": "VoicerHubContentStudio/1.0"},
    ) as client:
        current_url = url
        for _ in range(4):
            parsed = urlparse(current_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Вкажіть повне посилання http:// або https://")
            await _ensure_public_host(parsed.hostname)
            response = await client.get(current_url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(current_url, location)
                continue
            break
        else:
            raise ValueError("Сторінка має забагато перенаправлень")
        response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            raise ValueError("Посилання має вести на HTML-сторінку")
    parser = _PageTextParser()
    parser.feed(response.text[:2_000_000])
    text = "\n".join(parser.parts)
    if len(text) < 100:
        raise ValueError("На сторінці недостатньо тексту для створення допису")
    return text[:18_000]


class EditorialTools:
    def __init__(self, settings: Settings) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.settings = settings

    async def proofread(
        self,
        caption_html: str,
        model: str,
    ) -> tuple[str, int, int]:
        response = await self.client.responses.create(
            model=model,
            input=(
                "Відредагуй український Telegram-допис. Виправ орфографію, "
                "пунктуацію, русизми й термінологію. Збережи зміст, посилання, "
                "emoji та дозволені Telegram HTML-теги. Не додавай фактів. "
                f"Результат має бути коротшим за {MAX_CAPTION_LENGTH} видимих символів. "
                "Поверни лише готовий HTML без пояснень.\n\n"
                f"{caption_html}"
            ),
        )
        text = normalize_terminology(response.output_text)
        usage = response.usage
        return (
            shorten_caption(text),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )

    async def adapt_for_social(
        self,
        *,
        title: str,
        telegram_text: str,
        platform: str,
        rubric: dict,
        link_url: str,
        model: str,
    ) -> tuple[SocialPost, int, int]:
        rules = SOCIAL_PLATFORM_RULES[platform]
        response = await self.client.responses.parse(
            model=model,
            input=f"""
Адаптуй матеріал українською для {rules["label"]}.

Рубрика: {rubric["name"]}
Опис і дозволені факти: {rubric["description"]}
Редакційні правила: {rubric.get("instructions") or "Точно, корисно, без вигаданих фактів."}
Правила платформи: {rules["text"]}
Посилання: {link_url or "немає"}

Збережи зміст, але перепиши структуру під платформу. Текст має бути готовим
до ручного копіювання. Якщо є посилання, встав його природно як звичайний URL.
Поверни окремо заголовок, готовий текст без HTML, список хештегів та англомовний
image_prompt без написів, логотипів і водяних знаків.

Вихідний заголовок:
{title}

Вихідний Telegram-текст:
{telegram_text}
""".strip(),
            text_format=SocialPost,
        )
        if response.output_parsed is None:
            raise ValueError("Модель не повернула версію для соцмережі")
        usage = response.usage
        return (
            response.output_parsed,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )


def _normalize(value: str) -> str:
    words = re.findall(r"[0-9a-zа-яіїєґ]+", value.lower())
    stop = {
        "і", "й", "та", "у", "в", "на", "для", "про", "як", "що", "це",
        "з", "до", "від", "а", "але", "чи", "які", "який", "яка",
    }
    return " ".join(_stem(word) for word in words if word not in stop)


def _stem(word: str) -> str:
    endings = (
        "ування",
        "ювання",
        "ами",
        "ями",
        "ого",
        "ому",
        "ими",
        "ій",
        "ої",
        "ою",
        "ів",
        "ки",
        "ка",
        "ку",
        "ти",
        "є",
        "ий",
        "а",
        "у",
        "и",
        "і",
    )
    for ending in endings:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


async def _ensure_public_host(hostname: str) -> None:
    loopback_names = {"localhost", "localhost.localdomain"}
    if hostname.lower() in loopback_names:
        raise ValueError("Локальні адреси не підтримуються")
    infos = await asyncio.get_running_loop().run_in_executor(
        None,
        socket.getaddrinfo,
        hostname,
        None,
    )
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("Приватні та локальні адреси не підтримуються")
