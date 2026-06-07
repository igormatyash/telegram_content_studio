from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Product(StrEnum):
    VOICER = "voicer"
    TONY = "tony"
    WAVE = "wave"
    GENERAL = "general"


class Tone(StrEnum):
    EXPERT = "expert"
    SALES = "sales"
    LIGHT = "light"
    NEWS = "news"


class GeneratedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    title: str = Field(min_length=8, max_length=90)
    lead: str = Field(min_length=20, max_length=260)
    body: list[str] = Field(min_length=1, max_length=3)
    bullets: list[str] = Field(max_length=4)
    cta: str = Field(min_length=10, max_length=180)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    image_prompt: str = Field(min_length=30, max_length=900)
    title_options: list[str] = Field(min_length=3, max_length=3)
    cta_options: list[str] = Field(min_length=3, max_length=3)


class ContentIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Product
    title: str = Field(min_length=8, max_length=120)
    angle: str = Field(min_length=20, max_length=300)
    planned_for: str = ""
    tone: Tone = Tone.EXPERT
    series_title: str = ""
    series_part: int = Field(default=0, ge=0, le=5)


class IdeaSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ideas: list[ContentIdea] = Field(min_length=1, max_length=12)


class ContentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ideas: list[ContentIdea] = Field(min_length=1, max_length=31)


@dataclass(slots=True)
class Draft:
    id: int
    topic: str
    product: str
    title: str
    caption_html: str
    image_prompt: str
    image_path: str
    status: str
    link_url: str


@dataclass(slots=True)
class GenerationJob:
    id: int
    topic: str
    product: str
    chat_id: int
    status: str
    text_batch_id: str | None
    image_batch_id: str | None
    draft_id: int | None
    error: str | None
    text_model: str
    image_model: str
    reference_ids: str
    template_id: str
    logo_reference_id: int | None
    company_logo_reference_id: int | None
    link_url: str
    tone: str


@dataclass(slots=True)
class BatchRecord:
    id: str
    kind: str
    status: str
    total: int
    completed: int
    failed: int
    input_tokens: int
    output_tokens: int
    estimated_cost: float
