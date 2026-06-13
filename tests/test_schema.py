import json
from types import SimpleNamespace

from voicerhub_bot.batches import BatchOrchestrator
from voicerhub_bot.models import GeneratedPost, SocialPost


def test_generated_post_schema_is_strict_batch_compatible() -> None:
    schema = GeneratedPost.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "product",
        "title",
        "visual_title",
        "lead",
        "body",
        "bullets",
        "cta",
        "hashtags",
        "image_prompt",
        "title_options",
        "cta_options",
    }


def test_legacy_ai_responses_get_emoji_free_visual_title() -> None:
    post = GeneratedPost.model_validate(
        {
            "product": "tony",
            "title": "Як працює аналітика 🔥",
            "lead": "Достатньо довгий вступ для перевірки старої відповіді моделі.",
            "body": ["Основний текст матеріалу для перевірки сумісності."],
            "bullets": [],
            "cta": "Дізнайтеся більше про можливості рішення.",
            "hashtags": ["one", "two", "three"],
            "image_prompt": "A sufficiently detailed premium analytics illustration.",
            "title_options": [
                "Перший варіант заголовка",
                "Другий варіант заголовка",
                "Третій варіант заголовка",
            ],
            "cta_options": [
                "Дізнайтеся більше про рішення.",
                "Перегляньте можливості продукту.",
                "Обговорімо ваш робочий сценарій.",
            ],
        }
    )
    social = SocialPost.model_validate(
        {
            "title": "Кейс команди 🚀",
            "visual_title": "Кейс команди 🔥",
            "text": "Достатньо довгий текст для соціальної мережі.",
            "hashtags": [],
            "image_prompt": "A professional team discussing analytics results.",
        }
    )

    assert post.visual_title == "Як працює аналітика"
    assert social.visual_title == "Кейс команди"


def test_legacy_batch_json_is_finalized_with_visual_title() -> None:
    payload = {
        "product": "tony",
        "title": "Результат Batch 🚀",
        "lead": "Достатньо довгий вступ для сумісності зі старим Batch.",
        "body": ["Основний текст старої пакетної відповіді."],
        "bullets": [],
        "cta": "Перегляньте можливості рішення для вашої команди.",
        "hashtags": ["one", "two", "three"],
        "image_prompt": "A sufficiently detailed professional analytics scene.",
        "title_options": [
            "Перший варіант заголовка",
            "Другий варіант заголовка",
            "Третій варіант заголовка",
        ],
        "cta_options": [
            "Дізнайтеся більше про рішення.",
            "Перегляньте можливості продукту.",
            "Обговорімо ваш робочий сценарій.",
        ],
    }

    class Repository:
        def has_usage(self, *_):
            return True

    orchestrator = BatchOrchestrator.__new__(BatchOrchestrator)
    orchestrator.repository = Repository()
    post = orchestrator._finalize_text(
        SimpleNamespace(
            id=1,
            product="tony",
            tone="expert",
            text_model="gpt-5.4-mini",
            link_url="",
        ),
        json.dumps(payload, ensure_ascii=False),
        100,
        50,
        batch=True,
    )

    assert post.title == "Результат Batch 🚀"
    assert post.visual_title == "Результат Batch"
