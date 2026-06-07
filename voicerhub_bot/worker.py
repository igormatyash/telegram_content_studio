import asyncio
import json
import logging
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode

from voicerhub_bot.batches import BatchOrchestrator, _image_price
from voicerhub_bot.config import Settings
from voicerhub_bot.models import GeneratedPost
from voicerhub_bot.rendering import render_caption
from voicerhub_bot.storage import DraftRepository


logger = logging.getLogger(__name__)
WAVE_COVER_PATH = Path(__file__).parent / "assets" / "VoicerWave.jpg"


class GenerationWorker:
    def __init__(self, settings: Settings, repository: DraftRepository, bot: Bot) -> None:
        self.settings = settings
        self.repository = repository
        self.bot = bot
        self.batches = BatchOrchestrator(settings, repository)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Worker tick failed")
            await asyncio.sleep(30)

    async def tick(self) -> None:
        for draft in self.repository.due_scheduled_drafts():
            try:
                await self._publish_draft(draft)
            except Exception:
                logger.exception("Scheduled draft %s publication failed", draft["id"])

        for job in self.repository.jobs_with_status("queued_text"):
            try:
                await self.batches.submit_text(job)
            except Exception as exc:
                self._fail(job.id, exc)

        for job in self.repository.jobs_with_status("text_batch"):
            try:
                post = await self.batches.poll_text(job)
                if post is None:
                    continue
                draft = self.repository.create(
                    topic=job.topic,
                    product=post.product.value,
                    title=post.title,
                    caption_html=render_caption(post, job.link_url),
                    image_prompt=json.dumps(post.model_dump(), ensure_ascii=False),
                    image_path=str(WAVE_COVER_PATH) if post.product.value == "wave" else "",
                    link_url=job.link_url,
                    title_options=post.title_options,
                    cta_options=post.cta_options,
                    tone=job.tone,
                )
                if post.product.value == "wave":
                    if not WAVE_COVER_PATH.is_file():
                        raise FileNotFoundError("Voicer Wave cover image is missing.")
                    self.repository.update_job(job.id, status="ready", draft_id=draft.id)
                    await self._notify_ready(job.id)
                else:
                    self.repository.update_job(
                        job.id,
                        status="queued_image",
                        draft_id=draft.id,
                    )
            except Exception as exc:
                self._fail(job.id, exc)

        for job in self.repository.jobs_with_status("queued_image"):
            try:
                draft = self.repository.get(job.draft_id)
                post = GeneratedPost.model_validate_json(draft.image_prompt)
                reference_ids = json.loads(job.reference_ids)
                references = self.repository.references_by_ids(reference_ids)
                logo = (
                    self.repository.get_reference(job.logo_reference_id)
                    if job.logo_reference_id
                    else None
                )
                company_logo = (
                    self.repository.get_reference(job.company_logo_reference_id)
                    if job.company_logo_reference_id
                    else None
                )
                try:
                    template = self.repository.get_custom_template(job.template_id)
                except KeyError:
                    template = None
                if self.settings.use_image_batch and not references:
                    await self.batches.submit_image(job, post)
                else:
                    image_path, response = await self.batches.branding.generate(
                        post.title,
                        post.image_prompt,
                        model=job.image_model,
                        reference_paths=[Path(item["path"]) for item in references],
                        template_id=job.template_id,
                        logo_path=Path(logo["path"]) if logo else None,
                        company_logo_path=(
                            Path(company_logo["path"]) if company_logo else None
                        ),
                        template=template,
                    )
                    self.repository.set_draft_image(draft.id, str(image_path))
                    usage = getattr(response, "usage", None)
                    self.repository.add_usage(
                        job_id=job.id,
                        kind="image",
                        model=job.image_model,
                        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                        units=1,
                        cost=_image_price(job.image_model, batch=False),
                    )
                    self.repository.update_job(job.id, status="ready")
                    await self._notify_ready(job.id)
            except Exception as exc:
                self._fail(job.id, exc)

        for job in self.repository.jobs_with_status("image_batch"):
            try:
                draft = self.repository.get(job.draft_id)
                image_path = await self.batches.poll_image(job, draft.title)
                if image_path is None:
                    continue
                self.repository.set_draft_image(draft.id, str(image_path))
                self.repository.update_job(job.id, status="ready")
                await self._notify_ready(job.id)
            except Exception as exc:
                self._fail(job.id, exc)

    async def _notify_ready(self, job_id: int) -> None:
        job = self.repository.get_job(job_id)
        if job.chat_id <= 0:
            return
        await self.bot.send_message(
            chat_id=job.chat_id,
            text=(
                f"Чернетка #{job.draft_id} готова. "
                f"Використайте /preview {job.draft_id}, щоб переглянути та опублікувати."
            ),
        )

    async def _publish_draft(self, draft: dict) -> None:
        with open(draft["image_path"], "rb") as image:
            message = await self.bot.send_photo(
                chat_id=self.settings.telegram_channel,
                photo=image,
                caption=draft["caption_html"],
                parse_mode=ParseMode.HTML,
            )
        self.repository.mark_published(draft["id"])
        self.repository.set_telegram_message_id(draft["id"], message.message_id)

    def _fail(self, job_id: int, error: Exception) -> None:
        logger.exception("Generation job %s failed", job_id, exc_info=error)
        self.repository.update_job(job_id, status="failed", error=str(error)[:1000])
