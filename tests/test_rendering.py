import pytest

from voicerhub_bot.models import GeneratedPost, Product
from voicerhub_bot.rendering import (
    MAX_CAPTION_LENGTH,
    canonicalize_draft_caption,
    enforce_link,
    normalize_hashtag,
    plain_text,
    render_caption,
)


def make_post(**overrides) -> GeneratedPost:
    values = {
        "product": Product.TONY,
        "title": "Як TONY бачить повну картину діалогу",
        "lead": "Текст розмови показує зміст, але голос додає важливий контекст.",
        "body": ["TONY аналізує дзвінки, чати та відео в єдиній системі."],
        "bullets": ["Перевірка за чек-листами", "Аналіз інтонації та емоцій"],
        "cta": "Дізнайтеся більше на сторінці продукту.",
        "hashtags": ["VoicerHub", "#TONY", "Voice AI"],
        "image_prompt": "A premium analytics interface connected to a human voice waveform.",
        "title_options": [
            "Як TONY бачить повну картину діалогу",
            "Що додає голос до аналітики",
            "Комунікація без сліпих зон",
        ],
        "cta_options": [
            "Дізнайтеся більше на сторінці продукту.",
            "Подивіться, як працює TONY.",
            "Обговорімо ваш сценарій контролю якості.",
        ],
    }
    values.update(overrides)
    return GeneratedPost(**values)


def test_render_caption_escapes_html_and_normalizes_hashtags() -> None:
    caption = render_caption(make_post(title="TONY < AI"))

    assert "<b>TONY &lt; AI</b>" in caption
    assert "#Voice_AI" in caption
    assert len(caption) <= MAX_CAPTION_LENGTH


def test_render_caption_shortens_oversized_post() -> None:
    caption = render_caption(make_post(body=["а" * 900]))

    assert len(caption) <= MAX_CAPTION_LENGTH
    assert "а" * 900 not in caption


def test_normalize_hashtag_removes_punctuation() -> None:
    assert normalize_hashtag("#AI-аналітика!") == "#AIаналітика"


def test_render_caption_keeps_supported_telegram_html_and_link() -> None:
    caption = render_caption(
        make_post(
            lead="<i>Важливий контекст</i> і <tg-spoiler>деталь</tg-spoiler>.",
            body=["<blockquote>Практичний висновок</blockquote>"],
        ),
        "https://voicerhub.com/ua/products/tony",
    )

    assert "<i>Важливий контекст</i>" in caption
    assert "<tg-spoiler>деталь</tg-spoiler>" in caption
    assert "<blockquote>Практичний висновок</blockquote>" in caption
    assert '<a href="https://voicerhub.com/ua/products/tony">' in caption


def test_render_caption_removes_model_link_and_uses_exact_user_url() -> None:
    caption = render_caption(
        make_post(
            title="<b>TONY без сліпих зон</b>",
            cta=(
                '<a href="https://VoicerHub.com/ua/products/TONY">'
                "Переглянути продукт</a>"
            ),
        ),
        "https://voicerhub.com/ua/products/tony",
    )

    assert "<b>&lt;b&gt;" not in caption
    assert "https://VoicerHub.com/ua/products/TONY" not in caption
    assert (
        '<a href="https://voicerhub.com/ua/products/tony">'
        "Переглянути продукт</a>"
    ) in caption


def test_plain_text_decodes_escaped_formatting() -> None:
    assert plain_text("&lt;b&gt;Сильний заголовок&lt;/b&gt;") == "Сильний заголовок"


def test_enforce_link_repairs_existing_href_without_changing_case() -> None:
    result = enforce_link(
        '&lt;b&gt;Текст&lt;/b&gt;\n\n'
        '<a href="https://VoicerHub.com/ua/products/TONY">Детальніше</a>',
        "https://voicerhub.com/ua/products/tony",
    )

    assert "<b>Текст</b>" in result
    assert 'href="https://voicerhub.com/ua/products/tony"' in result


def test_enforce_link_collapses_duplicate_formatting_tags() -> None:
    result = enforce_link(
        "<b><b>Сильний заголовок</b></b>",
        "",
    )

    assert result == "<b>Сильний заголовок</b>"


def test_canonicalize_draft_caption_repairs_legacy_title_markup() -> None:
    result = canonicalize_draft_caption(
        "<b><b>Сильний заголовок</b> 🛒</b>\n\nОсновний текст",
        "Сильний заголовок 🛒",
        "https://voicerhub.com/ua/products/tony",
    )

    assert result.startswith("<b>Сильний заголовок 🛒</b>\n\nОсновний текст")
    assert "</b> 🛒</b>" not in result
    assert 'href="https://voicerhub.com/ua/products/tony"' in result


def test_wave_caption_is_short_and_omits_product_post_sections() -> None:
    caption = render_caption(
        make_post(
            product=Product.WAVE,
            title="ШІ вчиться бачити запахи 👃",
            lead="Моделі вже можуть розпізнавати склад повітря за сигналами електронних сенсорів.",
            body=["Це допомагає знаходити витоки та контролювати якість продуктів."],
            bullets=["Цей список не має потрапити в допис"],
            cta="Можливо, скоро смартфон матиме цифровий нюх. 🤖",
            hashtags=["VoicerHub", "AI", "Wave"],
        )
    )

    assert "ШІ вчиться бачити запахи 👃" in caption
    assert "цифровий нюх. 🤖" in caption
    assert "Цей список" not in caption
    assert "#VoicerHub" not in caption
    assert len(caption) <= 600
