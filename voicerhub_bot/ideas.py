from openai import AsyncOpenAI

from voicerhub_bot.config import Settings
from voicerhub_bot.knowledge import (
    COMPANY_CONTEXT,
    EDITORIAL_RULES,
    PRODUCT_FACTS,
    WAVE_EDITORIAL_RULES,
)
from voicerhub_bot.content_tools import TONE_GUIDANCE
from voicerhub_bot.models import ContentPlan, IdeaSet


class IdeaGenerator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate(
        self,
        product: str,
        count: int,
        focus: str,
        recent_titles: list[str],
        model: str | None = None,
        rubrics: list[dict] | None = None,
    ) -> tuple[IdeaSet, int, int]:
        available = rubrics or []
        facts, rules = self._context(product, available)
        allowed = ", ".join(item["slug"] for item in available)
        recent = "\n".join(f"- {title}" for title in recent_titles) or "- none"
        prompt = f"""
You are planning a Ukrainian social media content calendar.

Company:
Use only the company and rubric information supplied below.

Approved facts:
{facts}

Editorial rules:
{rules}

Recent titles that must not be repeated:
{recent}

Optional editorial focus:
{focus or "No additional focus"}

Suggest exactly {count} distinct post ideas. Each idea needs a concise Ukrainian
title and a concrete Ukrainian angle explaining what useful point the post will
make. For Voicer Wave, suggest surprising evergreen AI facts rather than company
products or current news. Do not invent product claims, clients, metrics,
launches or integrations.

Rubric slug rules:
- allowed rubric slugs: {allowed};
- requested rubric: {product};
- when requested rubric is "all", distribute ideas among allowed rubrics;
- otherwise every idea must use the exact requested rubric slug.
""".strip()
        response = await self.client.responses.parse(
            model=model or self.settings.openai_text_model,
            input=prompt,
            text_format=IdeaSet,
        )
        if response.output_parsed is None:
            raise ValueError("The model did not return content ideas.")
        usage = response.usage
        return (
            response.output_parsed,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )

    async def generate_plan(
        self,
        *,
        product: str,
        days: int,
        posts: int,
        focus: str,
        start_date: str,
        recent_titles: list[str],
        model: str,
        rubrics: list[dict] | None = None,
    ) -> tuple[ContentPlan, int, int]:
        available = rubrics or []
        facts, rules = self._context(product, available)
        allowed = ", ".join(item["slug"] for item in available)
        response = await self.client.responses.parse(
            model=model,
            input=f"""
Create a {days}-day Ukrainian social media content plan starting
{start_date}. Return exactly {posts} ideas distributed across the period.

Company:
Use only the supplied rubric information.

Approved facts:
{facts}

Rules:
{rules}

Available tones:
{chr(10).join(f"- {key}: {value}" for key, value in TONE_GUIDANCE.items())}

Recent titles to avoid:
{chr(10).join(f"- {title}" for title in recent_titles) or "- none"}

Focus:
{focus or "Balanced product education, practical value and audience engagement."}

For each idea set planned_for to YYYY-MM-DD, choose a useful tone, and leave
series_title empty and series_part 0. Do not invent product facts.
Allowed rubric slugs: {allowed}.
When requested rubric is "all", balance the available rubrics.
Otherwise use rubric slug "{product}" for every idea.
""".strip(),
            text_format=ContentPlan,
        )
        return self._parsed(response)

    async def generate_series(
        self,
        *,
        product: str,
        parts: int,
        topic: str,
        tone: str,
        recent_titles: list[str],
        model: str,
        rubrics: list[dict] | None = None,
    ) -> tuple[IdeaSet, int, int]:
        facts, rules = self._context(product, rubrics or [])
        response = await self.client.responses.parse(
            model=model,
            input=f"""
Plan one connected Ukrainian Telegram series of exactly {parts} posts.

Series topic: {topic}
Tone: {TONE_GUIDANCE[tone]}
Approved facts: {facts}
Rules: {rules}
Recent titles to avoid:
{chr(10).join(f"- {title}" for title in recent_titles) or "- none"}

Each post must work independently while advancing one logical story. Give all
ideas the same concise series_title and series_part from 1 to {parts}.
Leave planned_for empty. Do not repeat angles or invent claims.
Use rubric slug "{product}" for every idea.
""".strip(),
            text_format=IdeaSet,
        )
        return self._parsed(response)

    async def from_material(
        self,
        *,
        material: str,
        source_url: str,
        product: str,
        count: int,
        tone: str,
        model: str,
        rubrics: list[dict] | None = None,
    ) -> tuple[IdeaSet, int, int]:
        available = rubrics or []
        facts, rules = self._context(product, available)
        allowed = ", ".join(item["slug"] for item in available)
        response = await self.client.responses.parse(
            model=model,
            input=f"""
Turn the supplied website material into exactly {count} distinct Ukrainian
social media post ideas.

Source URL: {source_url}
Requested tone: {TONE_GUIDANCE[tone]}
Approved product facts: {facts}
Editorial rules: {rules}

Use only information present in the material or approved facts. Do not copy
long passages. Each idea must have a useful original angle. Leave planned_for
and series_title empty, and series_part 0.
Allowed rubric slugs: {allowed}. When requested rubric is "all", distribute
ideas among them. Otherwise use the exact requested rubric slug "{product}".

Website material:
{material}
""".strip(),
            text_format=IdeaSet,
        )
        return self._parsed(response)

    def _context(self, product: str, rubrics: list[dict]) -> tuple[str, str]:
        selected = rubrics if product == "all" else [
            item for item in rubrics if item["slug"] == product
        ]
        if not selected:
            raise ValueError("Оберіть активну рубрику")
        facts = "\n\n".join(
            f"{item['name']} ({item['slug']}): {item['description']}"
            for item in selected
        )
        rules = "\n\n".join(
            item.get("instructions") or EDITORIAL_RULES for item in selected
        )
        return facts, rules

    @staticmethod
    def _parsed(response) -> tuple[ContentPlan | IdeaSet, int, int]:
        if response.output_parsed is None:
            raise ValueError("The model did not return content ideas.")
        usage = response.usage
        return (
            response.output_parsed,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
