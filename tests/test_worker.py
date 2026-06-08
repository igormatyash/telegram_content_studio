import asyncio
from types import SimpleNamespace

from voicerhub_bot.config import Settings
from voicerhub_bot.worker import GenerationWorker


def test_tick_processes_completed_image_batch_without_new_text(tmp_path) -> None:
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"image")
    job = SimpleNamespace(id=7, draft_id=11, chat_id=0)

    class Repository:
        def __init__(self):
            self.status = "image_batch"
            self.saved_image = None

        def due_scheduled_drafts(self):
            return []

        def jobs_with_status(self, status):
            return [job] if status == "image_batch" and self.status == status else []

        def get(self, draft_id):
            assert draft_id == 11
            return SimpleNamespace(id=11, title="Готове зображення")

        def set_draft_image(self, draft_id, path):
            assert draft_id == 11
            self.saved_image = path

        def update_job(self, job_id, **values):
            assert job_id == 7
            self.status = values["status"]

        def get_job(self, job_id):
            assert job_id == 7
            return job

    class Batches:
        async def poll_image(self, current_job, title):
            assert current_job is job
            assert title == "Готове зображення"
            return image_path

    repository = Repository()
    settings = Settings(
        telegram_bot_token="telegram",
        openai_api_key="openai",
        database_path=tmp_path / "worker.sqlite3",
        generated_dir=tmp_path / "generated",
        reference_dir=tmp_path / "references",
        organizations_dir=tmp_path / "organizations",
    )
    worker = GenerationWorker(settings, repository, SimpleNamespace())
    worker.batches = Batches()

    asyncio.run(worker.tick())

    assert repository.status == "ready"
    assert repository.saved_image == str(image_path)
