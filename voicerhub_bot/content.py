from openai import AsyncOpenAI

from voicerhub_bot.knowledge import (
    COMPANY_CONTEXT,
    EDITORIAL_RULES,
    PRODUCT_FACTS,
    VISUAL_RULES,
    WAVE_EDITORIAL_RULES,
)
from voicerhub_bot.models import GeneratedPost, Product


class ContentGenerator:
    def __init__(self, api_key: str, text_model: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.text_model = text_model

    async def generate(
        self,
        topic: str,
        product: Product,
        recent_titles: list[str],
        feedback: str | None = None,
    ) -> GeneratedPost:
        if product == Product.WAVE:
            facts = "Evergreen, educational and verifiable facts about artificial intelligence."
            rules = WAVE_EDITORIAL_RULES
        else:
            facts = "\n\n".join(PRODUCT_FACTS.values()) if product == Product.GENERAL else PRODUCT_FACTS[product.value]
            rules = EDITORIAL_RULES
        recent = "\n".join(f"- {title}" for title in recent_titles) or "- none"
        revision = f"\nEditor feedback: {feedback}" if feedback else ""

        prompt = f"""
You are the Ukrainian-language editor of the VoicerHub Telegram channel.

Company:
{COMPANY_CONTEXT}

Approved product facts:
{facts}

Editorial rules:
{rules}

Visual direction:
{VISUAL_RULES}

Recent titles to avoid repeating:
{recent}

Requested topic:
{topic}
{revision}

        Keep the complete rendered Telegram caption below 850 characters. Every factual
        claim must be supported by the approved product facts above.
""".strip()

        response = await self.client.responses.parse(
            model=self.text_model,
            input=prompt,
            text_format=GeneratedPost,
        )
        post = response.output_parsed
        if post is None:
            raise ValueError("The model did not return a structured post.")
        if product != Product.GENERAL:
            post.product = product
        return post
