import base64
import io
import json
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from voicerhub_bot.config import Settings
from voicerhub_bot.content_tools import TONE_GUIDANCE, normalize_terminology
from voicerhub_bot.images import ImageGenerator
from voicerhub_bot.knowledge import (
    COMPANY_CONTEXT,
    EDITORIAL_RULES,
    PRODUCT_FACTS,
    WAVE_EDITORIAL_RULES,
)
from voicerhub_bot.models import BatchRecord, GeneratedPost, GenerationJob
from voicerhub_bot.rendering import plain_text, render_caption
from voicerhub_bot.storage import DraftRepository
from voicerhub_bot.text_utils import strip_emoji
from voicerhub_bot.visual_templates import get_visual_template


TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}


class BatchOrchestrator:
    def __init__(self, settings: Settings, repository: DraftRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.branding = ImageGenerator(
            settings.openai_api_key,
            settings.openai_image_model,
            settings.generated_dir,
            settings.brand_logo_path,
        )

    async def submit_text(self, job: GenerationJob) -> str:
        request = {
            "custom_id": f"text-job-{job.id}",
            "method": "POST",
            "url": "/v1/responses",
            "body": self._text_request_body(job),
        }
        batch = await self._create_batch(request, "/v1/responses", job.id, "text")
        self.repository.update_job(job.id, status="text_batch", text_batch_id=batch.id)
        return batch.id

    async def generate_text_direct(self, job: GenerationJob) -> GeneratedPost:
        body = self._text_request_body(job)
        response = await self.client.responses.create(**body)
        usage = response.usage
        return self._finalize_text(
            job,
            response.output_text,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
            batch=False,
        )

    def _text_request_body(self, job: GenerationJob) -> dict[str, Any]:
        rubric = self.repository.get_rubric(job.product)
        fixed_cover = bool(rubric.get("fixed_cover_path"))
        facts = rubric["description"]
        rules = rubric.get("instructions") or EDITORIAL_RULES
        if fixed_cover:
            output_rules = """
This rubric uses a fixed cover. Put the first sentence in
lead, one or two short sentences in body, and the final sentence or thoughtful
question in cta. Include 3 placeholder hashtags only to satisfy the schema;
they will not be rendered. Use a short generic image_prompt because a fixed
cover will be used instead of image generation.
""".strip()
        else:
            output_rules = """
Keep the rendered caption under 850 characters. The image_prompt must be in
English and must request no text or logos.
""".strip()
        recent = "\n".join(f"- {title}" for title in self.repository.recent_titles()) or "- none"
        favorites = self.repository.favorite_posts()
        examples = "\n\n".join(
            f"Example {index + 1} ({item['product']}, {item['tone']}):\n"
            f"{item['caption_html']}"
            for index, item in enumerate(favorites)
        ) or "No approved examples yet."
        prompt = f"""
You are a Ukrainian-language social media editor.

Rubric name: {rubric["name"]}
Rubric slug: {rubric["slug"]}
Approved rubric facts:
{facts}

Rules:
{rules}

Recent titles to avoid:
{recent}

Approved successful posts. Learn their clarity and structure, but never copy:
{examples}

Topic:
{job.topic}

Requested tone:
{TONE_GUIDANCE.get(job.tone, TONE_GUIDANCE["expert"])}

Optional destination link:
{job.link_url or "No link requested"}

Return a compact Ukrainian post as JSON matching the supplied schema. Keep the
rendered caption concise.

Output details:
{output_rules}

The lead, body and bullets may contain valid Telegram HTML tags. The title,
visual_title, title_options, CTA and CTA options must be plain text without HTML or escaped
HTML entities. Never reproduce, rewrite, capitalize or return the destination
URL; the application inserts the exact user-supplied URL after generation.
The title is the post headline and may use emoji. visual_title is a short,
emoji-free headline for rendering on the image.
Generate 3 genuinely different title_options and 3 CTA options. The main title
and CTA must be the strongest options. Generate 3 to 5 relevant hashtags
automatically. Check Ukrainian spelling and always use the terminology supplied
in the rubric facts.
""".strip()
        schema = GeneratedPost.model_json_schema()
        return {
            "model": job.text_model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "voicerhub_post",
                    "strict": True,
                    "schema": schema,
                }
            },
        }

    async def submit_image(self, job: GenerationJob, post: GeneratedPost) -> str:
        template = self._template(job.template_id)
        request = {
            "custom_id": f"image-job-{job.id}",
            "method": "POST",
            "url": "/v1/images/generations",
            "body": {
                "model": job.image_model,
                "prompt": (
                    "Create a premium 3:2 B2B technology editorial image. "
                    "Do not render text, logos or watermarks.\n\n"
                    f"Visual direction: {template['prompt']}\n\n"
                    f"Subject: {post.image_prompt}"
                ),
                "size": "1536x1024",
                "quality": "medium",
                "output_format": "png",
            },
        }
        batch = await self._create_batch(
            request,
            "/v1/images/generations",
            job.id,
            "image",
        )
        self.repository.update_job(job.id, status="image_batch", image_batch_id=batch.id)
        return batch.id

    async def poll_text(self, job: GenerationJob) -> GeneratedPost | None:
        batch = await self.client.batches.retrieve(job.text_batch_id)
        self._save_batch(batch, "text", job.text_model)
        if batch.status not in TERMINAL_BATCH_STATUSES:
            return None
        if batch.status != "completed" or not batch.output_file_id:
            raise RuntimeError(await self._batch_failure_message(batch, "Text"))

        output = await self._read_batch_output(batch.output_file_id)
        body = self._successful_body(output, f"text-job-{job.id}")
        text = _response_output_text(body)
        usage = body.get("usage") or {}
        return self._finalize_text(
            job,
            text,
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            batch=True,
        )

    def _finalize_text(
        self,
        job: GenerationJob,
        text: str,
        input_tokens: int,
        output_tokens: int,
        *,
        batch: bool,
    ) -> GeneratedPost:
        post = GeneratedPost.model_validate_json(text)
        # Rubrics are tenant configuration selected before generation. A model
        # may return the display name instead of the stable slug, so bind the
        # generated content back to the original job.
        post.product = job.product
        post.title = plain_text(normalize_terminology(post.title))
        post.visual_title = (
            strip_emoji(plain_text(normalize_terminology(post.visual_title)))
            or strip_emoji(post.title)
            or "Заголовок"
        )
        post.lead = normalize_terminology(post.lead)
        post.body = [normalize_terminology(item) for item in post.body]
        post.bullets = [normalize_terminology(item) for item in post.bullets]
        post.cta = plain_text(normalize_terminology(post.cta))
        post.title_options = [
            plain_text(normalize_terminology(item)) for item in post.title_options
        ]
        post.cta_options = [
            plain_text(normalize_terminology(item)) for item in post.cta_options
        ]
        render_caption(post, job.link_url)
        input_price, output_price = _text_prices(job.text_model)
        if not batch:
            input_price *= 2
            output_price *= 2
        cost = (
            input_tokens * input_price
            + output_tokens * output_price
        ) / 1_000_000
        if not self.repository.has_usage(job.id, "text"):
            self.repository.add_usage(
                job_id=job.id,
                kind="text",
                model=job.text_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
            )
        return post

    async def poll_image(self, job: GenerationJob, visual_title: str) -> Path | None:
        batch = await self.client.batches.retrieve(job.image_batch_id)
        self._save_batch(batch, "image", job.image_model)
        if batch.status not in TERMINAL_BATCH_STATUSES:
            return None
        if batch.status != "completed" or not batch.output_file_id:
            raise RuntimeError(await self._batch_failure_message(batch, "Image"))

        output = await self._read_batch_output(batch.output_file_id)
        body = self._successful_body(output, f"image-job-{job.id}")
        encoded = body["data"][0]["b64_json"]
        image_path = self.settings.generated_dir / f"job-{job.id}.png"
        image_path.write_bytes(base64.b64decode(encoded))
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
        self.branding._apply_branding(
            image_path,
            strip_emoji(visual_title) or "Заголовок",
            template_id=job.template_id,
            logo_path=Path(logo["path"]) if logo else None,
            company_logo_path=Path(company_logo["path"]) if company_logo else None,
            template=self._template(job.template_id),
        )
        self.repository.add_usage(
            job_id=job.id,
            kind="image",
            model=job.image_model,
            units=1,
            cost=_image_price(job.image_model, batch=True),
        )
        return image_path

    def _template(self, template_id: str) -> dict:
        try:
            return self.repository.get_custom_template(template_id)
        except KeyError:
            return get_visual_template(template_id)

    async def _create_batch(
        self,
        request: dict[str, Any],
        endpoint: str,
        job_id: int,
        kind: str,
    ):
        payload = (json.dumps(request, ensure_ascii=False) + "\n").encode()
        uploaded = await self.client.files.create(
            file=("batch.jsonl", io.BytesIO(payload), "application/jsonl"),
            purpose="batch",
        )
        batch = await self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint=endpoint,
            completion_window="24h",
            metadata={"job_id": str(job_id), "kind": kind},
        )
        model = self.repository.get_job(job_id)
        selected_model = model.text_model if kind == "text" else model.image_model
        self._save_batch(batch, kind, selected_model)
        return batch

    async def _read_batch_output(self, file_id: str) -> list[dict[str, Any]]:
        response = await self.client.files.content(file_id)
        content = await response.aread()
        return [json.loads(line) for line in content.decode().splitlines() if line.strip()]

    async def _batch_failure_message(self, batch: Any, label: str) -> str:
        if batch.error_file_id:
            lines = await self._read_batch_output(batch.error_file_id)
            messages = []
            for line in lines:
                response_error = ((line.get("response") or {}).get("body") or {}).get("error")
                if response_error and response_error.get("message"):
                    messages.append(response_error["message"])
                elif line.get("error"):
                    messages.append(str(line["error"]))
            if messages:
                return f"{label} batch request failed: {'; '.join(messages)}"
        return f"{label} batch ended with status {batch.status}"

    @staticmethod
    def _successful_body(
        lines: list[dict[str, Any]],
        custom_id: str,
    ) -> dict[str, Any]:
        item = next((line for line in lines if line.get("custom_id") == custom_id), None)
        if not item:
            raise RuntimeError(f"Batch output {custom_id} not found")
        if item.get("error"):
            raise RuntimeError(str(item["error"]))
        response = item.get("response") or {}
        if response.get("status_code") != 200:
            raise RuntimeError(f"Batch request failed: {response}")
        return response["body"]

    def _save_batch(self, batch: Any, kind: str, model: str) -> None:
        counts = batch.request_counts
        usage = getattr(batch, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        estimated_cost = 0.0
        if kind == "text":
            input_price, output_price = _text_prices(model)
            estimated_cost = (
                input_tokens * input_price
                + output_tokens * output_price
            ) / 1_000_000
        elif batch.status == "completed":
            estimated_cost = _image_price(model, batch=True)
        self.repository.upsert_batch(
            BatchRecord(
                id=batch.id,
                kind=kind,
                status=batch.status,
                total=int(getattr(counts, "total", 0) or 0),
                completed=int(getattr(counts, "completed", 0) or 0),
                failed=int(getattr(counts, "failed", 0) or 0),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=estimated_cost,
            )
        )


def _response_output_text(body: dict[str, Any]) -> str:
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content["text"]
    raise RuntimeError("Text batch returned no output_text")


def _text_prices(model: str) -> tuple[float, float]:
    return {
        "gpt-5-mini": (0.25, 2.00),
        "gpt-5.4-mini": (0.75, 4.50),
        "gpt-5.4": (2.50, 15.00),
        "gpt-5.5": (5.00, 30.00),
    }.get(model, (0.75, 4.50))


def _image_price(model: str, *, batch: bool) -> float:
    standard = {
        "gpt-image-1-mini": 0.015,
        "gpt-image-1.5": 0.050,
        "gpt-image-2": 0.041,
    }.get(model, 0.050)
    return standard / 2 if batch else standard
