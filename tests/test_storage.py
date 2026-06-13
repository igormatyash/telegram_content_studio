from pathlib import Path
import sqlite3

from PIL import Image
import pytest

from voicerhub_bot.images import ImageGenerator
from voicerhub_bot.storage import DraftRepository


def test_draft_lifecycle(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "drafts.sqlite3")
    draft = repository.create(
        topic="Аналітика голосу",
        product="tony",
        title="Що приховує інтонація",
        caption_html="<b>Що приховує інтонація</b>",
        image_prompt="Voice waveform and analytics dashboard",
        image_path="/tmp/example.png",
    )

    assert repository.get(draft.id).status == "draft"
    assert repository.recent_titles() == ["Що приховує інтонація"]

    repository.mark_published(draft.id)

    assert repository.get(draft.id).status == "published"


def test_visual_title_backfill_is_idempotent_for_legacy_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-visual-title.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE drafts (
                id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL,
                product TEXT NOT NULL,
                title TEXT NOT NULL,
                caption_html TEXT NOT NULL,
                image_prompt TEXT NOT NULL,
                image_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                published_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO drafts (
                topic, product, title, caption_html, image_prompt, image_path
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Legacy",
                "general",
                "Український заголовок 🚀",
                "<b>Текст</b>",
                "A detailed legacy image prompt.",
                "",
            ),
        )

    DraftRepository(database)
    repository = DraftRepository(database)

    assert repository.draft_record(1)["visual_title"] == "Український заголовок"


def test_ideas_editing_and_schedule(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "studio.sqlite3")
    idea = repository.add_ideas(
        [{"product": "tony", "title": "Голос і контекст", "angle": "Пояснити роль інтонації."}]
    )[0]
    job = repository.select_idea(idea["id"])
    assert job.status == "queued_text"
    assert job.text_model == "gpt-5.4-mini"
    assert job.image_model == "gpt-image-2"

    draft = repository.create(
        topic="Голос і контекст",
        product="tony",
        title="Початковий заголовок",
        caption_html="<b>Початковий заголовок</b>\n\nТекст допису",
        image_prompt="{}",
        image_path="/tmp/post.png",
    )
    repository.update_draft(
        draft.id,
        title="Новий заголовок",
        caption_html="<b>Новий заголовок</b>\n\nОновлений текст",
        link_url="https://voicerhub.com/ua/products/tony",
    )
    repository.schedule_draft(draft.id, "2030-01-01T10:00:00Z")

    record = repository.draft_record(draft.id)
    assert record["title"] == "Новий заголовок"
    assert record["status"] == "scheduled"
    assert record["scheduled_at"] == "2030-01-01T10:00:00Z"
    assert record["link_url"] == "https://voicerhub.com/ua/products/tony"


def test_content_status_transitions_and_plans_are_persisted(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "workflow.sqlite3", organization_id=4)
    draft = repository.create(
        topic="Workflow",
        product="general",
        title="Чернетка для команди",
        caption_html="<b>Чернетка</b>\n\nТекст для перевірки редактором.",
        image_prompt="A detailed editorial workflow illustration.",
        image_path="/tmp/post.png",
    )

    assert repository.transition_draft(draft.id, "review")["status"] == "review"
    assert repository.transition_draft(draft.id, "needs_changes")["status"] == "needs_changes"
    assert repository.transition_draft(draft.id, "draft")["status"] == "draft"
    assert repository.transition_draft(draft.id, "ready")["status"] == "ready"
    with pytest.raises(ValueError, match="Invalid content transition"):
        repository.transition_draft(draft.id, "published")

    plan = repository.create_content_plan(
        plan_id="plan-test",
        period="week",
        start_date="2030-01-01",
        posts=5,
        objective="Запуск нового продукту",
        create_as="ideas",
        rubric_slugs=["general"],
        channel_ids=["@example"],
        created_by_user_id=12,
    )
    assert plan["organization_id"] == 4
    assert repository.list_content_plans()[0]["id"] == "plan-test"
    series = repository.create_content_series(
        series_id="series-test",
        title="П’ять кроків",
        parts=5,
        rubric_slug="general",
        created_by_user_id=12,
    )
    assert series["organization_id"] == 4
    assert series["parts"] == 5


def test_idea_status_follows_active_job_before_draft(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "statuses.sqlite3")
    idea = repository.add_ideas(
        [{"product": "tony", "title": "Контроль сервісу", "angle": "Показати процес."}]
    )[0]
    job = repository.select_idea(idea["id"])
    draft = repository.create(
        topic="Контроль сервісу",
        product="tony",
        title="Контроль сервісу у всіх каналах",
        caption_html="<b>Контроль сервісу</b>\n\nОсновний текст публікації.",
        image_prompt="A premium analytics interface for customer service.",
        image_path="",
    )
    repository.update_job(job.id, status="queued_image", draft_id=draft.id)

    dashboard_idea = repository.dashboard()["ideas"][0]
    assert dashboard_idea["status"] == "queued_image"

    repository.update_job(job.id, status="ready")
    dashboard_idea = repository.dashboard()["ideas"][0]
    assert dashboard_idea["status"] == "draft"


def test_existing_jobs_are_backfilled_to_their_ideas(tmp_path: Path) -> None:
    database_path = tmp_path / "backfill.sqlite3"
    repository = DraftRepository(database_path)
    idea = repository.add_ideas(
        [
            {
                "product": "tony",
                "title": "Старий матеріал",
                "angle": "Пояснити користь аналізу для команди підтримки.",
            }
        ]
    )[0]
    repository.create_job(
        f"{idea['title']}. {idea['angle']}",
        "tony",
        0,
    )

    repository = DraftRepository(database_path)

    assert repository.dashboard()["ideas"][0]["status"] == "queued_text"


def test_job_keeps_models_and_reference_assets(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "models.sqlite3")
    reference = repository.add_reference(
        name="Tony logo",
        filename="tony.png",
        path=str(tmp_path / "tony.png"),
        media_type="image/png",
    )
    job = repository.create_job(
        "Голосова аналітика",
        "tony",
        0,
        text_model="gpt-5.5",
        image_model="gpt-image-2",
        reference_ids=[reference["id"]],
        template_id="clean-light",
        logo_reference_id=reference["id"],
        generation_mode="fast",
    )

    assert job.text_model == "gpt-5.5"
    assert job.image_model == "gpt-image-2"
    assert job.reference_ids == f"[{reference['id']}]"
    assert job.template_id == "clean-light"
    assert job.logo_reference_id == reference["id"]
    assert job.generation_mode == "fast"
    assert repository.references_by_ids([reference["id"]])[0]["name"] == "Tony logo"


def test_usage_inherits_user_from_generation_job(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "usage.sqlite3")
    job = repository.create_job(
        "Аналітика комунікацій",
        "tony",
        0,
        created_by_user_id=42,
    )

    repository.add_usage(
        job_id=job.id,
        kind="text",
        model="gpt-5.4-mini",
        input_tokens=120,
        output_tokens=80,
        cost=0.01,
    )

    report = repository.usage_summary()
    assert report["totals"]["input_tokens"] == 120
    assert report["totals"]["output_tokens"] == 80
    assert report["users"][0]["user_id"] == 42
    assert report["users"][0]["text_generations"] == 1


def test_usage_can_be_checked_before_retrying_completed_batch(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "usage-retry.sqlite3")

    assert repository.has_usage(42, "text") is False
    repository.add_usage(
        job_id=42,
        kind="text",
        model="gpt-5.4-mini",
        input_tokens=100,
        output_tokens=50,
        cost=0.01,
    )

    assert repository.has_usage(42, "text") is True
    assert repository.has_usage(42, "image") is False


def test_repair_draft_markup_cleans_titles_and_restores_exact_link(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "repair.sqlite3")
    draft = repository.create(
        topic="Тема",
        product="tony",
        title="<b>Сильний заголовок</b>",
        caption_html=(
            "&lt;b&gt;Сильний заголовок&lt;/b&gt;\n\n"
            '<a href="https://VoicerHub.com/ua/products/TONY">Детальніше</a>'
        ),
        image_prompt="A premium technology scene with a contact center dashboard.",
        image_path="",
        link_url="https://voicerhub.com/ua/products/tony",
        title_options=["<b>Варіант</b>"],
        cta_options=['<a href="https://example.com">CTA</a>'],
    )

    assert repository.repair_draft_markup() == 1
    repaired = repository.draft_record(draft.id)
    assert repaired["title"] == "Сильний заголовок"
    assert "<b>Сильний заголовок</b>" in repaired["caption_html"]
    assert 'href="https://voicerhub.com/ua/products/tony"' in repaired["caption_html"]
    assert repaired["title_options"] == '["Варіант"]'
    assert repaired["cta_options"] == '["CTA"]'


def test_custom_rubrics_and_social_variants_are_stored_per_tenant(tmp_path: Path) -> None:
    repository = DraftRepository(tmp_path / "company.sqlite3")
    rubric = repository.add_rubric(
        slug="customer-cases",
        name="Кейси клієнтів",
        description="Практичні історії про задачі клієнтів, рішення та отриману користь.",
        instructions="Не вигадувати назви клієнтів або метрики.",
        default_link="https://example.com/cases",
    )
    draft = repository.create(
        topic="Автоматизація підтримки",
        product=rubric["slug"],
        title="Як команда скоротила ручну роботу 🚀",
        caption_html="<b>Кейс</b>\n\nКорисний приклад.",
        image_prompt="A customer support automation case study.",
        image_path="/tmp/telegram.png",
    )

    variant = repository.save_social_variant(
        draft_id=draft.id,
        platform="linkedin",
        title="Практичний кейс автоматизації 🔥",
        text_content="Готовий професійний текст для LinkedIn.",
        hashtags=["automation", "cx"],
        image_prompt="A professional customer experience team.",
        image_path="/tmp/linkedin.png",
        text_model="gpt-5.4-mini",
        image_model="gpt-image-2",
        created_by_user_id=7,
    )

    assert repository.get_rubric("customer-cases")["name"] == "Кейси клієнтів"
    assert variant["hashtags"] == ["automation", "cx"]
    assert variant["visual_title"] == "Практичний кейс автоматизації"
    assert repository.draft_record(draft.id)["visual_title"] == (
        "Як команда скоротила ручну роботу"
    )
    assert repository.draft_record(draft.id)["image_path"] == "/tmp/telegram.png"


def test_social_image_is_cropped_to_exact_platform_size(tmp_path: Path) -> None:
    source = tmp_path / "social.png"
    Image.new("RGB", (1024, 1536), "navy").save(source)

    ImageGenerator._fit_output(source, (1080, 1350))

    assert Image.open(source).size == (1080, 1350)
