from pathlib import Path

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
    )

    assert job.text_model == "gpt-5.5"
    assert job.image_model == "gpt-image-2"
    assert job.reference_ids == f"[{reference['id']}]"
    assert job.template_id == "clean-light"
    assert job.logo_reference_id == reference["id"]
    assert repository.references_by_ids([reference["id"]])[0]["name"] == "Tony logo"
