from io import BytesIO
from datetime import date, datetime, timedelta, timezone
import base64
import hashlib
import hmac
import html
import json
from pathlib import Path
import shutil
from uuid import uuid4
import re
from urllib.parse import urlencode

import httpx
import uvicorn
from openai import AsyncOpenAI
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from telegram import Bot
from telegram.constants import ParseMode

from voicerhub_bot.auth import AuthRepository, SESSION_DAYS
from voicerhub_bot.billing import BillingService, public_plans
from voicerhub_bot.config import Settings, get_settings
from voicerhub_bot.content_tools import (
    EditorialTools,
    SOCIAL_PLATFORM_RULES,
    TONE_GUIDANCE,
    closest_duplicate,
    fetch_page_text,
)
from voicerhub_bot.ideas import IdeaGenerator
from voicerhub_bot.images import ImageGenerator
from voicerhub_bot.formatting import sanitize_preview_html, strip_formatting
from voicerhub_bot.instagram import (
    InstagramApiError,
    InstagramSetupError,
    MetaInstagramClient,
    instagram_configured,
    instagram_connect_url,
    instagram_redirect_uri,
    verify_media_signature,
)
from voicerhub_bot.permissions import (
    ROLE_LABELS,
    WORKSPACE_ROLES,
    has_permission,
    permissions_for,
    role_catalog,
)
from voicerhub_bot.rendering import (
    MAX_CAPTION_LENGTH,
    canonicalize_draft_caption,
    enforce_link,
    plain_text,
    sanitize_telegram_html,
)
from voicerhub_bot.referrals import ReferralRepository
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.slugs import generate_slug
from voicerhub_bot.social_publishing import InstagramPublisher
from voicerhub_bot.storage import DraftRepository, TenantRepository
from voicerhub_bot.visual_templates import DEFAULT_TEMPLATE_ID, VISUAL_TEMPLATES


class IdeaRequest(BaseModel):
    product: str = "all"
    count: int = Field(default=6, ge=1, le=12)
    focus: str = Field(default="", max_length=500)
    text_model: str = "gpt-5.4-mini"
    tone: str = "expert"


class ManualIdeaRequest(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    angle: str = Field(default="", max_length=1000)
    product: str
    planned_for: date | None = None


class IdeaPlanRequest(BaseModel):
    planned_for: date


class ManualDraftRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    visual_title: str = Field(default="", max_length=120)
    caption_html: str = Field(min_length=20, max_length=MAX_CAPTION_LENGTH)
    product: str
    link_url: str = Field(default="", max_length=500)


class ContentPlanRequest(BaseModel):
    product: str = "all"
    period: str = Field(default="week", pattern=r"^(week|month)$")
    posts: int = Field(default=5, ge=1, le=31)
    start_date: date
    focus: str = Field(default="", max_length=500)
    text_model: str = "gpt-5.4-mini"
    create_as: str = Field(default="ideas", pattern=r"^(ideas|drafts)$")
    rubric_slugs: list[str] = Field(default_factory=list, max_length=20)
    channel_ids: list[str] = Field(default_factory=list, max_length=5)


class SeriesRequest(BaseModel):
    product: str
    parts: int = Field(default=3, ge=3, le=5)
    topic: str = Field(min_length=10, max_length=500)
    tone: str = "expert"
    text_model: str = "gpt-5.4-mini"


class MaterialRequest(BaseModel):
    url: str = Field(default="", max_length=1000)
    text: str = Field(default="", max_length=18000)
    product: str = "all"
    count: int = Field(default=3, ge=1, le=8)
    tone: str = "expert"
    text_model: str = "gpt-5.4-mini"


class GenerationRequest(BaseModel):
    text_model: str = "gpt-5.4-mini"
    image_model: str = "gpt-image-2"
    reference_ids: list[int] = Field(default_factory=list, max_length=16)
    template_id: str = DEFAULT_TEMPLATE_ID
    logo_reference_id: int | None = None
    company_logo_reference_id: int | None = None
    link_url: str = Field(default="", max_length=500)
    tone: str = "expert"
    generation_mode: str = Field(default="fast", pattern=r"^(fast|batch)$")


class RubricCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(default="", max_length=60)
    description: str = Field(min_length=20, max_length=3000)
    instructions: str = Field(default="", max_length=3000)
    default_link: str = Field(default="", max_length=500)
    goal: str = Field(default="", max_length=1000)
    tone: str = Field(default="", max_length=500)
    example_topic: str = Field(default="", max_length=500)
    active: bool = True


class RubricUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=20, max_length=3000)
    instructions: str = Field(default="", max_length=3000)
    default_link: str = Field(default="", max_length=500)
    goal: str = Field(default="", max_length=1000)
    tone: str = Field(default="", max_length=500)
    example_topic: str = Field(default="", max_length=500)
    active: bool = True


class SocialVariantRequest(BaseModel):
    platform: str
    text_model: str = "gpt-5.4-mini"
    image_model: str = "gpt-image-2"
    reference_ids: list[int] = Field(default_factory=list, max_length=16)
    template_id: str = DEFAULT_TEMPLATE_ID
    logo_reference_id: int | None = None
    company_logo_reference_id: int | None = None


class SocialVariantUpdateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    visual_title: str = Field(default="", max_length=160)
    text_content: str = Field(min_length=20, max_length=3000)


TEXT_MODELS = {"gpt-5-mini", "gpt-5.4-mini", "gpt-5.4", "gpt-5.5"}
IMAGE_MODELS = {"gpt-image-1-mini", "gpt-image-1.5", "gpt-image-2"}


def _validate_models(text_model: str, image_model: str | None = None) -> None:
    if text_model not in TEXT_MODELS:
        raise HTTPException(status_code=422, detail="Обрана модель тексту не підтримується")
    if image_model is not None and image_model not in IMAGE_MODELS:
        raise HTTPException(status_code=422, detail="Обрана модель зображень не підтримується")


def _validate_tone(tone: str) -> None:
    if tone not in TONE_GUIDANCE:
        raise HTTPException(status_code=422, detail="Невідомий тон допису")


def _validate_generation(payload: GenerationRequest, repository: DraftRepository) -> None:
    _validate_models(payload.text_model, payload.image_model)
    _validate_tone(payload.tone)
    template_ids = {item["id"] for item in VISUAL_TEMPLATES}
    template_ids.update(item["id"] for item in repository.list_custom_templates())
    if payload.template_id not in template_ids:
        raise HTTPException(status_code=422, detail="Невідомий візуальний шаблон")
    repository.references_by_ids(payload.reference_ids)
    if payload.logo_reference_id is not None:
        repository.get_reference(payload.logo_reference_id)
    if payload.company_logo_reference_id is not None:
        repository.get_reference(payload.company_logo_reference_id)
    if payload.link_url and not payload.link_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="Посилання має починатися з http:// або https://",
        )


class DraftEditRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    visual_title: str = Field(default="", max_length=120)
    caption_html: str = Field(min_length=20, max_length=MAX_CAPTION_LENGTH)
    link_url: str = Field(default="", max_length=500)


class FavoriteRequest(BaseModel):
    favorite: bool


class CustomTemplateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=5, max_length=180)
    prompt: str = Field(min_length=30, max_length=1600)
    layout: str = Field(
        default="top_left",
        pattern=r"^(top_left|left_panel|bottom_left|top_band)$",
    )
    accent: str = Field(default="#18ecd6", pattern=r"^#[0-9A-Fa-f]{6}$")
    mood: str = Field(default="", max_length=500)
    use_rules: str = Field(default="", max_length=1500)
    avoid_rules: str = Field(default="", max_length=1500)
    prompt_examples: str = Field(default="", max_length=2000)
    active: bool = True


class CustomTemplateUpdateRequest(CustomTemplateRequest):
    pass


class BrandMaterialLinkRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    material_type: str = Field(default="link", max_length=40)
    source_url: str = Field(min_length=5, max_length=1000)
    description: str = Field(default="", max_length=2000)
    active: bool = True


class BrandMaterialUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    material_type: str = Field(default="other", max_length=40)
    source_url: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=2000)
    active: bool = True


class WorkspaceAppearanceRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(default="", max_length=60)
    short_description: str = Field(default="", max_length=300)
    primary_color: str = Field(default="#6366f1", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str = Field(default="#a855f7", pattern=r"^#[0-9A-Fa-f]{6}$")
    avatar_asset_id: int | None = None
    logo_asset_id: int | None = None
    favicon_asset_id: int | None = None


class BulkActionRequest(BaseModel):
    ids: list[int | str] = Field(min_length=1, max_length=100)
    action: str = Field(min_length=2, max_length=40)
    value: str = Field(default="", max_length=120)


class ServiceUpdateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(default="", max_length=3000)
    title_uk: str = Field(default="", max_length=160)
    body_uk: str = Field(default="", max_length=3000)
    title_en: str = Field(default="", max_length=160)
    body_en: str = Field(default="", max_length=3000)
    category: str = Field(
        default="release",
        pattern=r"^(release|fix|maintenance|announcement)$",
    )
    importance: str = Field(
        default="info",
        pattern=r"^(info|success|warning|maintenance)$",
    )
    status: str = Field(default="published", pattern=r"^(draft|published|archived)$")
    pinned: bool = False
    visible_from: str = Field(default="", max_length=32)
    visible_until: str = Field(default="", max_length=32)


class ScheduleRequest(BaseModel):
    scheduled_at: datetime


class InstagramScheduleRequest(BaseModel):
    scheduled_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=10, max_length=200)
    is_admin: bool = False
    role: str | None = Field(
        default=None,
        pattern=r"^(owner|admin|content_manager|editor|publisher|viewer)$",
    )
    email: str | None = Field(default=None, max_length=254)


class UserUpdateRequest(BaseModel):
    is_admin: bool | None = None
    active: bool | None = None
    role: str | None = Field(
        default=None,
        pattern=r"^(owner|admin|content_manager|editor|publisher|viewer)$",
    )


class PasswordRequest(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class PasswordResetLinkRequest(BaseModel):
    user_id: int = Field(ge=1)


class PasswordResetCompleteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=200)


class InvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(
        default="editor",
        pattern=r"^(admin|content_manager|editor|publisher|viewer)$",
    )


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=100)


class TrialWorkspaceRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(default="", max_length=60)
    company_id: int | None = Field(default=None, ge=1)


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=10, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=2, max_length=100)
    workspace_name: str = Field(min_length=2, max_length=100)
    workspace_slug: str = Field(default="", max_length=60)
    referral_code: str = Field(default="", max_length=40)


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(default="", max_length=60)
    workspace_name: str = Field(default="", max_length=100)
    workspace_slug: str = Field(default="", max_length=60)
    owner_username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    owner_password: str = Field(min_length=10, max_length=200)
    owner_email: str | None = Field(default=None, max_length=254)
    owner_display_name: str = Field(default="", max_length=100)
    max_users: int = Field(default=50, ge=1, le=50)
    max_channels: int = Field(default=1, ge=1, le=1)
    monthly_publications: int = Field(default=90, ge=1, le=10000)
    monthly_ai_budget: float = Field(default=50, ge=0, le=100000)
    monthly_text_generations: int = Field(default=60, ge=0, le=100000)
    monthly_image_generations: int = Field(default=30, ge=0, le=100000)
    max_workspaces: int = Field(default=10, ge=1, le=100)


class TelegramConnectionRequest(BaseModel):
    bot_token: str = Field(min_length=20, max_length=200)
    channel_id: str = Field(min_length=2, max_length=200)


class TelegramValidationResponse(BaseModel):
    ok: bool
    bot_username: str
    channel_id: str
    membership_status: str


class CheckoutRequest(BaseModel):
    plan_code: str = Field(pattern=r"^(start|growth|scale)$")


class WorkspaceSelectRequest(BaseModel):
    organization_id: int = Field(ge=1)


class WorkspaceDeleteRequest(BaseModel):
    confirmation_name: str = Field(min_length=2, max_length=100)


class WorkspaceModeRequest(BaseModel):
    workspace_mode: str = Field(pattern=r"^(pipeline|kanban)$")


class OnboardingCompanyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(default="", max_length=60)
    primary_language: str = Field(default="uk", pattern=r"^[a-z]{2}$")
    brand_primary_color: str = Field(
        default="",
        pattern=r"^(|#[0-9A-Fa-f]{6})$",
    )
    brand_logo_asset_id: int | None = None


class OnboardingBrandRequest(BaseModel):
    company_description: str = Field(default="", max_length=5000)
    tone_of_voice: str = Field(default="", max_length=3000)
    key_services: str = Field(default="", max_length=3000)
    forbidden_phrases: str = Field(default="", max_length=3000)
    website_url: str = Field(default="", max_length=500)


class OnboardingRubricItem(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10, max_length=3000)


class OnboardingRubricsRequest(BaseModel):
    rubrics: list[OnboardingRubricItem] = Field(min_length=1, max_length=10)


class ContentStatusRequest(BaseModel):
    status: str = Field(
        pattern=r"^(draft|review|needs_changes|ready|scheduled|published)$"
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare_directories()
    privacy_hash_salt = (
        settings.privacy_hash_salt
        or settings.app_encryption_key
        or settings.admin_password
        or settings.product_name
    )
    repository = TenantRepository(settings.database_path, settings.organizations_dir)
    auth = AuthRepository(settings.database_path, privacy_hash_salt)
    auth.ensure_bootstrap_admin(settings.admin_username, settings.admin_password)
    saas = SaasRepository(
        settings.database_path,
        settings.app_encryption_key,
        privacy_hash_salt,
    )
    saas.ensure_legacy_organization(channel_id=settings.telegram_channel)
    referrals = ReferralRepository(
        settings.database_path,
        privacy_hash_salt,
    )
    repository.for_organization(1).ensure_legacy_rubrics(
        str(Path(__file__).parent / "assets" / "VoicerWave.jpg")
    )
    for existing_organization_id in saas.organization_ids():
        tenant_repository = repository.for_organization(existing_organization_id)
        tenant_repository.repair_draft_markup()
        tenant_repository.repair_non_primary_legacy_rubrics()
    idea_generator = IdeaGenerator(settings)
    editorial_tools = EditorialTools(settings)
    billing = BillingService(saas, settings.telegram_bot_token)
    app = FastAPI(title=settings.product_name, docs_url=None, redoc_url=None)
    frontend_dir = Path(__file__).parent / "frontend"
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    def frontend_html(name: str) -> str:
        markup = (frontend_dir / name).read_text(encoding="utf-8")
        return markup.replace("__BASE_PATH__", settings.admin_base_path.rstrip("/")).replace(
            "__GOOGLE_ENABLED__",
            str(bool(settings.google_client_id and settings.google_client_secret)).lower(),
        )

    def public_url(path: str = "") -> str:
        base = settings.public_app_url.rstrip("/")
        if not base:
            base = settings.admin_base_path.rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def instagram_setup_status() -> dict:
        configured = instagram_configured(settings)
        missing = []
        if not settings.instagram_enabled:
            missing.append("INSTAGRAM_ENABLED")
        if not settings.meta_app_id:
            missing.append("META_APP_ID")
        if not settings.meta_app_secret:
            missing.append("META_APP_SECRET")
        if not settings.public_app_url and not settings.meta_redirect_uri:
            missing.append("PUBLIC_APP_URL або META_REDIRECT_URI")
        return {
            "enabled": bool(settings.instagram_enabled),
            "configured": configured,
            "setup_required": not configured,
            "missing": missing,
            "scopes": [
                item.strip()
                for item in settings.meta_instagram_scopes.split(",")
                if item.strip()
            ],
            "graph_version": settings.meta_graph_version,
            "supports": {
                "feed_image": configured,
                "reels": False,
                "carousel": False,
            },
        }

    def oauth_secret() -> bytes:
        return (
            settings.app_encryption_key
            or settings.privacy_hash_salt
            or settings.admin_password
            or settings.product_name
        ).encode()

    def sign_instagram_state(user: dict) -> str:
        payload = {
            "nonce": uuid4().hex,
            "user_id": int(user["id"]),
            "organization_id": organization_id(user),
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }
        raw = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        signature = hmac.new(oauth_secret(), raw.encode(), hashlib.sha256).hexdigest()
        return f"{raw}.{signature}"

    def verify_instagram_state(state: str, cookie_state: str, user: dict | None = None) -> dict:
        if not state or not cookie_state or state != cookie_state or "." not in state:
            raise HTTPException(status_code=400, detail="Instagram OAuth state недійсний")
        raw, signature = state.rsplit(".", 1)
        expected = hmac.new(oauth_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Instagram OAuth state недійсний")
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Instagram OAuth state пошкоджено") from exc
        if int(datetime.now(timezone.utc).timestamp()) - int(payload.get("ts") or 0) > 15 * 60:
            raise HTTPException(status_code=400, detail="Instagram OAuth state застарів")
        if user and int(payload.get("user_id") or 0) != int(user["id"]):
            raise HTTPException(status_code=403, detail="Instagram OAuth належить іншому користувачу")
        return payload

    instagram_publisher = InstagramPublisher(
        settings=settings,
        saas=saas,
        tenants=repository,
    )

    def request_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return request.client.host if request.client else ""

    def record_referral_visit(code: str, request: Request) -> dict:
        query = request.query_params
        click = referrals.record_click(
            code,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            utm_source=query.get("utm_source", ""),
            utm_medium=query.get("utm_medium", ""),
            utm_campaign=query.get("utm_campaign", ""),
            landing_url=str(request.url),
        )
        referral = referrals.code(code)
        if referral:
            saas.audit(
                referral.get("owner_organization_id"),
                referral.get("owner_user_id"),
                "referral_link_opened",
                code,
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        return click

    def set_referral_cookies(response: Response, code: str, click_id: int) -> None:
        cookie_options = {
            "max_age": 30 * 24 * 60 * 60,
            "httponly": True,
            "samesite": "lax",
            "secure": settings.session_cookie_secure,
        }
        response.set_cookie("voicerhub_referral", code, **cookie_options)
        response.set_cookie(
            "voicerhub_referral_click",
            str(click_id),
            **cookie_options,
        )

    def organization_dirs(organization_id: int) -> tuple[Path, Path]:
        if organization_id == 1:
            return settings.generated_dir, settings.reference_dir
        root = settings.organizations_dir / str(organization_id)
        generated = root / "generated"
        references = root / "references"
        generated.mkdir(parents=True, exist_ok=True)
        references.mkdir(parents=True, exist_ok=True)
        return generated, references

    def image_generator_for(organization_id: int) -> ImageGenerator:
        generated, _ = organization_dirs(organization_id)
        return ImageGenerator(
            settings.openai_api_key,
            settings.openai_image_model,
            generated,
            settings.brand_logo_path if organization_id == 1 else None,
        )

    def telegram_credentials(organization_id: int) -> tuple[str, str]:
        try:
            connection = saas.telegram_connection(
                organization_id,
                include_token=True,
            )
        except KeyError:
            connection = {}
        token = connection.get("bot_token")
        channel = connection.get("channel_id")
        if organization_id == 1:
            token = token or settings.telegram_bot_token
            channel = channel or settings.telegram_channel
        if not token or not channel:
            raise HTTPException(
                status_code=409,
                detail="Спочатку підключіть Telegram-бота та канал компанії",
            )
        return token, channel

    async def validate_telegram_connection(
        payload: TelegramConnectionRequest,
    ) -> dict:
        try:
            bot = Bot(payload.bot_token.strip())
            profile = await bot.get_me()
            member = await bot.get_chat_member(payload.channel_id.strip(), profile.id)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Не вдалося знайти бота або канал. Перевірте token, "
                    "@username каналу та додайте бота в канал."
                ),
            ) from exc
        if member.status not in {"administrator", "creator"}:
            raise HTTPException(
                status_code=422,
                detail="Бот знайдений, але він не є адміністратором каналу",
            )
        return {
            "ok": True,
            "bot_username": profile.username or "",
            "channel_id": payload.channel_id.strip(),
            "membership_status": member.status,
        }

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
        messages = []
        for error in exc.errors():
            field = ".".join(str(item) for item in error.get("loc", [])[1:])
            message = error.get("msg", "Некоректне значення")
            messages.append(f"{field}: {message}" if field else message)
        return JSONResponse(
            status_code=422,
            content={"detail": "Перевірте введені дані: " + "; ".join(messages)},
        )

    async def authorize(
        voicerhub_session: str | None = Cookie(default=None),
    ) -> dict:
        user = auth.session_user(voicerhub_session)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if user.get("organization_id") is None:
            raise HTTPException(
                status_code=409,
                detail="Оберіть або створіть workspace",
            )
        organization_id = int(user["organization_id"])
        repository.use(organization_id)
        user["permissions"] = sorted(
            permissions_for(
                user.get("role") or "viewer",
                platform_admin=bool(user.get("is_super_admin")),
            )
        )
        return user

    async def authorize_write(
        user: dict = Depends(authorize),
        x_requested_with: str | None = Header(default=None),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        if user.get("role") == "viewer":
            raise HTTPException(status_code=403, detail="Недостатньо прав для змін")
        return user

    async def authorize_admin(user: dict = Depends(authorize_write)) -> dict:
        if user.get("role") not in {"platform_admin", "owner", "admin"}:
            raise HTTPException(status_code=403, detail="Administrator access required")
        return user

    async def authorize_super_admin(user: dict = Depends(authorize_write)) -> dict:
        if not user.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Platform administrator required")
        return user

    def require_permission(permission: str):
        async def dependency(
            user: dict = Depends(authorize),
            x_requested_with: str | None = Header(default=None),
        ) -> dict:
            if x_requested_with != "VoicerHubAdmin":
                raise HTTPException(status_code=403, detail="Missing request guard")
            if not has_permission(
                user.get("role") or "viewer",
                permission,
                platform_admin=bool(user.get("is_super_admin")),
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Недостатньо прав для цієї дії",
                )
            return user

        return dependency

    def paginate_rows(
        rows: list[dict],
        *,
        page: int,
        per_page: int,
    ) -> dict:
        page = max(1, page)
        per_page = min(100, max(1, per_page))
        total = len(rows)
        start = (page - 1) * per_page
        return {
            "items": rows[start : start + per_page],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }

    def organization_id(user: dict) -> int:
        return int(user.get("organization_id") or 1)

    def ensure_organization_user(current: dict, target_user_id: int) -> None:
        if target_user_id not in saas.member_ids(organization_id(current)):
            raise HTTPException(status_code=404, detail="Користувача не знайдено")

    def quota_error(detail: str, reason: str) -> HTTPException:
        return HTTPException(
            status_code=402,
            detail={
                "detail": detail,
                "reason": reason,
                "billing_section": "/content-admin/settings?tab=plans",
            },
        )

    def ensure_active_subscription(company: dict) -> None:
        status = company.get("subscription_status") or company.get("plan_code") or "custom"
        is_trial = status == "trial" or company.get("plan_code") == "trial"
        expires_at = company.get("trial_ends_at") if is_trial else company.get("plan_expires_at")
        if not expires_at:
            return
        expiration = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)
        if expiration <= datetime.now(timezone.utc):
            reason = "trial_expired" if is_trial else "subscription_expired"
            raise quota_error(
                "Термін дії trial або тарифу завершився. Оновіть підписку в розділі «Тарифи».",
                reason,
            )

    def ensure_generation_quota(kind: str, required: int = 1) -> None:
        company = saas.get_organization(repository.organization_id)
        ensure_active_subscription(company)
        column = (
            "monthly_text_generations"
            if kind == "text"
            else "monthly_image_generations"
        )
        limit = int(company.get(column) or 0)
        if limit <= 0:
            return
        used = repository.current_month_usage_units(kind)
        if used + max(1, required) > limit:
            label = "текстових генерацій" if kind == "text" else "генерацій зображень"
            reason = "text_quota_exceeded" if kind == "text" else "image_quota_exceeded"
            raise quota_error(
                f"Місячний ліміт {label} вичерпано. Оновіть тариф, щоб продовжити.",
                reason,
            )

    def ensure_text_generation_quota(required: int = 1) -> None:
        ensure_generation_quota("text", required)

    def ensure_image_generation_quota(required: int = 1) -> None:
        ensure_generation_quota("image", required)

    def ensure_publication_quota() -> None:
        company = saas.get_organization(repository.organization_id)
        ensure_active_subscription(company)
        if (
            repository.current_month_publications()
            >= company["monthly_publications"]
        ):
            raise quota_error(
                "Місячний ліміт публікацій вичерпано. Оновіть тариф, щоб продовжити.",
                "publication_quota_exceeded",
            )

    def ensure_subscription(company: dict) -> None:
        ensure_active_subscription(company)

    def active_rubrics() -> list[dict]:
        return repository.list_rubrics()

    def validate_rubric(slug: str, *, allow_all: bool = False) -> None:
        if allow_all and slug == "all":
            if not active_rubrics():
                raise HTTPException(
                    status_code=409,
                    detail="Спочатку створіть хоча б одну рубрику",
                )
            return
        try:
            repository.get_rubric(slug)
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail="Оберіть активну рубрику компанії",
            ) from exc

    def application_shell(voicerhub_session: str | None) -> str:
        user = auth.session_user(voicerhub_session)
        if user:
            repository.use(int(user.get("organization_id") or 1))
        return frontend_html("app.html") if user else frontend_html("login.html")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    @app.get("/ideas", response_class=HTMLResponse)
    @app.get("/content-plan", response_class=HTMLResponse)
    @app.get("/drafts", response_class=HTMLResponse)
    @app.get("/calendar", response_class=HTMLResponse)
    @app.get("/brand", response_class=HTMLResponse)
    @app.get("/expenses", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    def dashboard(voicerhub_session: str | None = Cookie(default=None)) -> str:
        return application_shell(voicerhub_session)

    @app.get("/platform", response_class=HTMLResponse)
    @app.get("/platform/{platform_path:path}", response_class=HTMLResponse)
    def platform_dashboard(
        platform_path: str = "",
        voicerhub_session: str | None = Cookie(default=None),
    ) -> str:
        del platform_path
        user = auth.session_user(voicerhub_session)
        if user is None:
            return frontend_html("login.html")
        if not user.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Platform administrator required")
        repository.use(int(user.get("organization_id") or 1))
        return frontend_html("app.html")

    @app.get("/invite", response_class=HTMLResponse)
    def invitation_page() -> str:
        return frontend_html("action.html").replace("__ACTION__", "invite")

    @app.get("/reset-password", response_class=HTMLResponse)
    def password_reset_page() -> str:
        return frontend_html("action.html").replace("__ACTION__", "reset")

    @app.get("/register", response_class=HTMLResponse)
    def registration_page(
        request: Request,
        ref: str = "",
        voicerhub_referral: str | None = Cookie(default=None),
        voicerhub_referral_click: str | None = Cookie(default=None),
    ) -> HTMLResponse:
        candidate = (ref or voicerhub_referral or "").strip()
        referral = referrals.code(candidate, active_only=True) if candidate else None
        response = HTMLResponse(
            frontend_html("register.html")
            .replace("__REFERRAL_CODE__", referral["code"] if referral else "")
            .replace("__REFERRAL_VALID__", "true" if referral else "false")
        )
        if referral and not (
            voicerhub_referral == referral["code"] and voicerhub_referral_click
        ):
            click = record_referral_visit(referral["code"], request)
            set_referral_cookies(response, referral["code"], click["id"])
        return response

    @app.get("/r/{code}")
    def open_referral_link(code: str, request: Request) -> RedirectResponse:
        try:
            click = record_referral_visit(code, request)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Реферальне посилання не знайдено або вимкнено",
            ) from exc
        query = {"ref": click["referral_code"]}
        for key in ("utm_source", "utm_medium", "utm_campaign"):
            value = request.query_params.get(key)
            if value:
                query[key] = value
        response = RedirectResponse(
            public_url(f"register?{urlencode(query)}"),
            status_code=303,
        )
        set_referral_cookies(
            response,
            click["referral_code"],
            click["id"],
        )
        return response

    @app.get(
        "/workspace/{org_slug}/drafts/{draft_id}",
        response_class=HTMLResponse,
    )
    @app.get("/drafts/{draft_id}", response_class=HTMLResponse)
    def draft_editor_page(
        draft_id: int,
        org_slug: str = "",
        voicerhub_session: str | None = Cookie(default=None),
    ) -> str:
        user = auth.session_user(voicerhub_session)
        if user is None:
            return frontend_html("login.html")
        if org_slug and user.get("organization_slug") != org_slug:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено")
        repository.for_organization(organization_id(user)).draft_record(draft_id)
        return frontend_html("app.html")

    @app.post("/api/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> dict:
        user = auth.authenticate(payload.username, payload.password)
        if user is None and "@" in payload.username:
            email_user = auth.find_by_email(payload.username)
            if email_user:
                user = auth.authenticate(email_user["username"], payload.password)
        if user is None:
            failed_user_id = auth.auth_user_id(payload.username)
            failed_membership = (
                saas.membership_for_user(failed_user_id)
                if failed_user_id is not None
                else None
            )
            auth.record_login(
                user_id=failed_user_id,
                organization_id=(
                    int(failed_membership["organization_id"])
                    if failed_membership
                    else None
                ),
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
                success=False,
                failure_reason="invalid_credentials",
            )
            raise HTTPException(status_code=401, detail="Невірний логін або пароль")
        token = auth.create_session(user["id"])
        membership = saas.membership_for_user(user["id"])
        login_organization_id = (
            int(membership["organization_id"]) if membership else None
        )
        auth.record_login(
            user_id=user["id"],
            organization_id=login_organization_id,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            success=True,
        )
        saas.audit(
            login_organization_id,
            user["id"],
            "user_logged_in",
            "",
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        response.set_cookie(
            "voicerhub_session",
            token,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        return {"user": user}

    @app.post("/api/register")
    def register(
        payload: RegistrationRequest,
        request: Request,
        response: Response,
        voicerhub_session: str | None = Cookie(default=None),
        voicerhub_referral: str | None = Cookie(default=None),
        voicerhub_referral_click: str | None = Cookie(default=None),
    ) -> dict:
        referral_code = (payload.referral_code or voicerhub_referral or "").strip()
        referral = (
            referrals.code(referral_code, active_only=True)
            if referral_code
            else None
        )
        current_user = auth.session_user(voicerhub_session)
        if (
            referral
            and current_user
            and int(referral["owner_user_id"]) == int(current_user["id"])
        ):
            raise HTTPException(
                status_code=409,
                detail="Не можна реєструватися за власним реферальним посиланням",
            )
        if auth.find_by_email(payload.email):
            raise HTTPException(
                status_code=409,
                detail="Користувач із таким email уже зареєстрований",
            )
        user = None
        company = None
        try:
            user = auth.create_user(
                payload.username,
                payload.password,
                is_admin=True,
                email=payload.email,
                display_name=payload.display_name,
            )
            company = saas.create_company(
                name=payload.workspace_name,
                slug=payload.workspace_slug or generate_slug(payload.workspace_name),
                max_workspaces=3,
            )
            organization = saas.create_trial_organization(
                name=payload.workspace_name,
                slug=payload.workspace_slug or generate_slug(payload.workspace_name),
                company_id=company["id"],
            )
            saas.add_member(organization["id"], user["id"], "owner")
            repository.for_organization(organization["id"])
        except Exception as exc:
            if user is not None:
                auth.delete_user(user["id"])
            if company is not None:
                saas.delete_empty_company(int(company["id"]))
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="Такий логін або slug уже використовується",
                ) from exc
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise
        saas.audit(
            organization["id"],
            user["id"],
            "user_registered",
            payload.email,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        saas.audit(
            organization["id"],
            user["id"],
            "company_created",
            company["slug"],
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        saas.audit(
            organization["id"],
            user["id"],
            "workspace_created",
            organization["slug"],
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        saas.audit(
            organization["id"],
            user["id"],
            "organization_created",
            organization["slug"],
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        if referral:
            try:
                referrals.complete_signup(
                    referral["code"],
                    new_user_id=user["id"],
                    new_organization_id=organization["id"],
                    click_id=(
                        int(voicerhub_referral_click)
                        if voicerhub_referral_click
                        and voicerhub_referral_click.isdigit()
                        else None
                    ),
                )
                saas.audit(
                    organization["id"],
                    user["id"],
                    "referral_signup_completed",
                    referral["code"],
                )
            except (KeyError, ValueError):
                pass
        session = auth.create_session(user["id"])
        auth.select_session_organization(session, organization["id"])
        auth.record_login(
            user_id=user["id"],
            organization_id=organization["id"],
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            success=True,
        )
        saas.audit(
            organization["id"],
            user["id"],
            "user_logged_in",
            "registration",
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        response.set_cookie(
            "voicerhub_session",
            session,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        response.delete_cookie("voicerhub_referral")
        response.delete_cookie("voicerhub_referral_click")
        return {
            "user": auth.session_user(session),
            "company": company,
            "organization": organization,
            "workspace": organization,
            "referred": bool(referral),
        }

    @app.get("/api/auth/google/start")
    def google_login_start(invite: str | None = None) -> RedirectResponse:
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(status_code=404, detail="Google login is not configured")
        state = auth.create_oauth_state(invite)
        redirect_uri = settings.google_redirect_uri or public_url("api/auth/google/callback")
        query = urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")

    @app.get("/api/auth/google/callback")
    async def google_login_callback(
        code: str,
        state: str,
        request: Request,
        response: Response,
        voicerhub_referral: str | None = Cookie(default=None),
        voicerhub_referral_click: str | None = Cookie(default=None),
    ) -> RedirectResponse:
        try:
            oauth_state = auth.consume_oauth_state(state)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        redirect_uri = settings.google_redirect_uri or public_url(
            "api/auth/google/callback"
        )
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_response.status_code >= 400:
                raise HTTPException(status_code=401, detail="Google authorization failed")
            access_token = token_response.json().get("access_token")
            profile_response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if profile_response.status_code >= 400:
                raise HTTPException(status_code=401, detail="Google profile failed")
        profile = profile_response.json()
        if not profile.get("email_verified"):
            raise HTTPException(status_code=403, detail="Google email is not verified")
        workspace_slug_base = re.sub(
            r"[^a-z0-9-]+",
            "-",
            profile["email"].split("@", 1)[0].lower(),
        ).strip("-") or "workspace"
        user = auth.find_by_google_subject(profile["sub"])
        if user is None:
            user = auth.find_by_email(profile["email"])
        created_new_user = user is None
        if user is None:
            username_base = re.sub(
                r"[^A-Za-z0-9._-]+",
                ".",
                profile["email"].split("@", 1)[0],
            ).strip(".") or "google.user"
            username = username_base
            suffix = 1
            while True:
                try:
                    user = auth.create_user(
                        username,
                        uuid4().hex + uuid4().hex,
                        is_admin=False,
                        email=profile["email"],
                        google_subject=profile["sub"],
                        display_name=profile.get("name", ""),
                        avatar_url=profile.get("picture", ""),
                    )
                    break
                except Exception as exc:
                    if "UNIQUE constraint failed: users.username" not in str(exc):
                        raise
                    suffix += 1
                    username = f"{username_base}.{suffix}"
        else:
            user = auth.link_google_identity(
                user["id"],
                subject=profile["sub"],
                email=profile["email"],
                display_name=profile.get("name", ""),
                avatar_url=profile.get("picture", ""),
            )
        auth.mark_email_verified(user["id"])
        if oauth_state.get("invite_token_hash"):
            try:
                invitation = auth.action_token_hash(
                    oauth_state["invite_token_hash"],
                    "workspace_invite",
                )
                if invitation is None:
                    raise KeyError("Invitation not found")
                if invitation.get("email", "").lower() != profile["email"].lower():
                    raise HTTPException(
                        status_code=403,
                        detail="Google email does not match invitation",
                    )
                saas.upsert_member(
                    int(invitation["organization_id"]),
                    user["id"],
                    invitation["role"],
                )
                auth.consume_action_token_hash(
                    oauth_state["invite_token_hash"],
                    "workspace_invite",
                )
            except KeyError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Invitation is invalid or expired",
                ) from exc
        membership = saas.membership_for_user(user["id"])
        created_organization = None
        if membership is None:
            workspace_name = (
                profile.get("name", "").strip()
                or profile["email"].split("@", 1)[0]
            )
            company = saas.create_company(
                name=workspace_name,
                slug=f"{workspace_slug_base[:32]}-{uuid4().hex[:8]}",
                max_workspaces=3,
            )
            organization = saas.create_trial_organization(
                name=f"{workspace_name} Workspace",
                slug=f"{workspace_slug_base[:32]}-{uuid4().hex[:8]}-workspace",
                company_id=company["id"],
            )
            saas.add_member(organization["id"], user["id"], "owner")
            repository.for_organization(organization["id"])
            created_organization = organization
            membership = saas.membership_for_user(user["id"])
        session = auth.create_session(user["id"])
        if oauth_state.get("invite_token_hash"):
            auth.select_session_organization(
                session,
                int(invitation["organization_id"]),
            )
        elif membership:
            auth.select_session_organization(
                session,
                int(membership["organization_id"]),
            )
        selected_organization_id = (
            int(invitation["organization_id"])
            if oauth_state.get("invite_token_hash")
            else int(membership["organization_id"]) if membership else None
        )
        if created_new_user:
            saas.audit(
                selected_organization_id,
                user["id"],
                "user_registered",
                profile["email"],
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        if created_organization:
            saas.audit(
                created_organization["id"],
                user["id"],
                "company_created",
                str(created_organization["company_id"]),
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            saas.audit(
                created_organization["id"],
                user["id"],
                "workspace_created",
                created_organization["slug"],
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            saas.audit(
                created_organization["id"],
                user["id"],
                "organization_created",
                created_organization["slug"],
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        saas.audit(
            selected_organization_id,
            user["id"],
            "email_verified",
            "google",
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        auth.record_login(
            user_id=user["id"],
            organization_id=selected_organization_id,
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            success=True,
        )
        saas.audit(
            selected_organization_id,
            user["id"],
            "user_logged_in",
            "google",
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        if created_new_user and voicerhub_referral and membership:
            try:
                referrals.complete_signup(
                    voicerhub_referral,
                    new_user_id=user["id"],
                    new_organization_id=int(membership["organization_id"]),
                    click_id=(
                        int(voicerhub_referral_click)
                        if voicerhub_referral_click
                        and voicerhub_referral_click.isdigit()
                        else None
                    ),
                )
                saas.audit(
                    int(membership["organization_id"]),
                    user["id"],
                    "referral_signup_completed",
                    voicerhub_referral,
                )
            except (KeyError, ValueError):
                pass
        redirect = RedirectResponse(public_url(), status_code=303)
        redirect.set_cookie(
            "voicerhub_session",
            session,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        if created_new_user:
            redirect.delete_cookie("voicerhub_referral")
            redirect.delete_cookie("voicerhub_referral_click")
        return redirect

    @app.get("/api/auth/config")
    def auth_config() -> dict:
        return {
            "google_enabled": bool(
                settings.google_client_id and settings.google_client_secret
            )
        }

    @app.post("/api/password-reset/complete")
    def complete_password_reset(payload: PasswordResetCompleteRequest) -> dict:
        try:
            token = auth.consume_action_token(payload.token, "password_reset")
        except KeyError as exc:
            raise HTTPException(status_code=400, detail="Посилання недійсне") from exc
        auth.set_password(int(token["user_id"]), payload.password)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(
        response: Response,
        voicerhub_session: str | None = Cookie(default=None),
        _: dict = Depends(authorize_write),
    ) -> dict:
        auth.delete_session(voicerhub_session)
        response.delete_cookie("voicerhub_session")
        return {"ok": True}

    @app.get("/api/me")
    def current_user(user: dict = Depends(authorize)) -> dict:
        return {
            **user,
            "companies": saas.companies_for_user(
                user["id"],
                platform_admin=bool(user.get("is_super_admin")),
            ),
            "workspaces": saas.organizations_for_user(
                user["id"],
                platform_admin=bool(user.get("is_super_admin")),
            ),
        }

    def referral_payload(user: dict) -> dict:
        summary = referrals.owner_summary(
            user["id"],
            organization_id(user),
        )
        return {
            **summary,
            "url": public_url(f"register?ref={summary['code']}"),
            "short_url": public_url(f"r/{summary['code']}"),
        }

    @app.get("/api/referrals/me")
    def my_referral(user: dict = Depends(authorize)) -> dict:
        return referral_payload(user)

    @app.post("/api/referrals/me/rotate")
    def rotate_my_referral(
        x_requested_with: str | None = Header(default=None),
        user: dict = Depends(authorize),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        referrals.rotate(user["id"], organization_id(user))
        return referral_payload(user)

    @app.post("/api/referrals/me/disable")
    def disable_my_referral(
        x_requested_with: str | None = Header(default=None),
        user: dict = Depends(authorize),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        try:
            referral = referrals.disable(user["id"], organization_id(user))
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Реферальне посилання не знайдено",
            ) from exc
        return {
            **referrals.owner_summary(user["id"], organization_id(user)),
            **referral,
            "url": public_url(f"register?ref={referral['code']}"),
            "short_url": public_url(f"r/{referral['code']}"),
        }

    @app.post("/api/account/trial-workspace")
    def create_trial_workspace(
        payload: TrialWorkspaceRequest,
        voicerhub_session: str | None = Cookie(default=None),
        user: dict = Depends(authorize_write),
    ) -> dict:
        try:
            current_company = saas.company_for_organization(organization_id(user))
            company_id = payload.company_id or int(current_company["id"])
            company_role = saas.company_role_for_user(company_id, user["id"])
            if not user.get("is_super_admin") and company_role not in {
                "owner",
                "admin",
            }:
                raise HTTPException(
                    status_code=403,
                    detail="Лише власник або адміністратор компанії може створювати workspace",
                )
            organization = saas.create_trial_organization(
                name=payload.name,
                slug=payload.slug or generate_slug(payload.name),
                company_id=company_id,
            )
            saas.add_member(organization["id"], user["id"], "owner")
            repository.for_organization(organization["id"])
            auth.select_session_organization(
                voicerhub_session,
                organization["id"],
            )
            saas.audit(
                organization["id"],
                user["id"],
                "workspace_created",
                organization["slug"],
            )
            saas.audit(
                organization["id"],
                user["id"],
                "organization_created",
                organization["slug"],
            )
        except HTTPException:
            raise
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="Workspace з таким slug вже існує",
                ) from exc
            if isinstance(exc, (ValueError, KeyError)):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise
        return organization

    @app.post("/api/invitations/accept")
    def accept_invitation(
        payload: InvitationAcceptRequest,
        request: Request,
        response: Response,
    ) -> dict:
        token = auth.action_token(payload.token, "workspace_invite")
        if token is None:
            raise HTTPException(status_code=400, detail="Запрошення недійсне")
        try:
            existing = auth.find_by_email(token["email"])
            if existing:
                user = existing
            else:
                user = auth.create_user(
                    payload.username,
                    payload.password,
                    is_admin=token["role"] == "admin",
                    email=token["email"],
                    display_name=payload.display_name,
                )
                saas.audit(
                    int(token["organization_id"]),
                    user["id"],
                    "user_registered",
                    token["email"],
                    ip_address=request_ip(request),
                    user_agent=request.headers.get("user-agent", ""),
                )
            saas.upsert_member(
                int(token["organization_id"]),
                user["id"],
                token["role"],
            )
            auth.consume_action_token(payload.token, "workspace_invite")
            session = auth.create_session(user["id"])
            auth.select_session_organization(session, int(token["organization_id"]))
            auth.record_login(
                user_id=user["id"],
                organization_id=int(token["organization_id"]),
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
                success=True,
            )
            saas.audit(
                int(token["organization_id"]),
                user["id"],
                "user_logged_in",
                "invitation",
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.set_cookie(
            "voicerhub_session",
            session,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        return {"user": auth.session_user(session)}

    @app.post("/api/workspace/select")
    def select_workspace(
        payload: WorkspaceSelectRequest,
        request: Request,
        voicerhub_session: str | None = Cookie(default=None),
        x_requested_with: str | None = Header(default=None),
        _: dict = Depends(authorize),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        try:
            auth.select_session_organization(
                voicerhub_session,
                payload.organization_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Workspace не знайдено",
            ) from exc
        user = auth.session_user(voicerhub_session)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        repository.use(organization_id(user))
        saas.audit(
            organization_id(user),
            user["id"],
            "workspace_selected",
            user.get("organization_slug", ""),
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
        )
        return user

    @app.delete("/api/workspaces/{workspace_id}")
    def delete_workspace(
        workspace_id: int,
        payload: WorkspaceDeleteRequest,
        voicerhub_session: str | None = Cookie(default=None),
        user: dict = Depends(authorize_write),
    ) -> dict:
        try:
            workspace = saas.get_organization(workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workspace не знайдено") from exc
        role = saas.role_for_user(workspace_id, user["id"])
        if not user.get("is_super_admin") and role != "owner":
            raise HTTPException(
                status_code=403,
                detail="Видалити workspace може лише його власник",
            )
        if payload.confirmation_name.strip() != str(workspace["name"]).strip():
            raise HTTPException(
                status_code=422,
                detail="Введіть точну назву workspace для підтвердження",
            )
        try:
            deleted = saas.delete_organization(workspace_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repository.forget(workspace_id)
        workspace_root = settings.organizations_dir / str(workspace_id)
        if workspace_root.is_dir():
            shutil.rmtree(workspace_root, ignore_errors=True)
        next_user = auth.session_user(voicerhub_session)
        if next_user is None or not next_user.get("organization_id"):
            available = saas.organizations_for_user(
                user["id"],
                platform_admin=bool(user.get("is_super_admin")),
            )
            if available:
                auth.select_session_organization(
                    voicerhub_session,
                    int(available[0]["id"]),
                )
                next_user = auth.session_user(voicerhub_session)
        return {
            "deleted": int(deleted["id"]),
            "next_workspace_id": (
                int(next_user["organization_id"])
                if next_user and next_user.get("organization_id")
                else None
            ),
        }

    @app.get("/api/onboarding")
    def onboarding_state(user: dict = Depends(authorize)) -> dict:
        return saas.organization_settings(organization_id(user))

    @app.put("/api/onboarding/company")
    def onboarding_company(
        payload: OnboardingCompanyRequest,
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        if payload.brand_logo_asset_id is not None:
            repository.get_reference(payload.brand_logo_asset_id)
        try:
            company = saas.update_organization(
                organization_id(user),
                name=payload.name,
                slug=payload.slug or generate_slug(payload.name),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="Такий slug уже використовується",
                ) from exc
            raise
        settings_row = saas.update_organization_settings(
            organization_id(user),
            onboarding_status="in_progress",
            onboarding_step=2,
            primary_language=payload.primary_language,
            brand_primary_color=payload.brand_primary_color,
            brand_logo_asset_id=payload.brand_logo_asset_id,
        )
        saas.audit(
            organization_id(user),
            user["id"],
            "organization_updated",
            company["slug"],
        )
        return {"company": company, "settings": settings_row}

    @app.put("/api/onboarding/brand")
    def onboarding_brand(
        payload: OnboardingBrandRequest,
        user: dict = Depends(require_permission("brand.edit")),
    ) -> dict:
        if payload.website_url and not payload.website_url.startswith(
            ("http://", "https://")
        ):
            raise HTTPException(
                status_code=422,
                detail="Посилання має починатися з http:// або https://",
            )
        return saas.update_organization_settings(
            organization_id(user),
            onboarding_status="in_progress",
            onboarding_step=3,
            **payload.model_dump(),
        )

    @app.post("/api/onboarding/rubrics")
    def onboarding_rubrics(
        payload: OnboardingRubricsRequest,
        user: dict = Depends(require_permission("rubrics.manage")),
    ) -> dict:
        created = []
        for item in payload.rubrics:
            slug = generate_slug(item.name)
            if not slug:
                slug = f"rubric-{uuid4().hex[:8]}"
            try:
                created.append(
                    repository.add_rubric(
                        slug=slug,
                        name=item.name.strip(),
                        description=item.description.strip(),
                    )
                )
            except Exception as exc:
                if "UNIQUE constraint failed" not in str(exc):
                    raise
        saas.update_organization_settings(
            organization_id(user),
            onboarding_status="in_progress",
            onboarding_step=5,
            initial_rubrics_created=1,
        )
        return {"rubrics": created}

    @app.post("/api/onboarding/skip")
    def skip_onboarding(
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        return saas.update_organization_settings(
            organization_id(user),
            onboarding_status="skipped",
        )

    @app.post("/api/onboarding/restart")
    def restart_onboarding(
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        return saas.update_organization_settings(
            organization_id(user),
            onboarding_status="not_started",
            onboarding_step=0,
        )

    @app.post("/api/onboarding/complete")
    def complete_onboarding(
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        return saas.update_organization_settings(
            organization_id(user),
            onboarding_status="completed",
            onboarding_step=5,
        )

    @app.put("/api/workspace/mode")
    def update_workspace_mode(
        payload: WorkspaceModeRequest,
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        return saas.update_organization_settings(
            organization_id(user),
            workspace_mode=payload.workspace_mode,
        )

    @app.get("/api/users")
    def users(
        page: int | None = None,
        per_page: int = 25,
        search: str = "",
        role: str = "",
        sort: str = "display_name",
        direction: str = "asc",
        user: dict = Depends(require_permission("users.view")),
    ) -> list[dict] | dict:
        rows = auth.list_users(int(user.get("organization_id") or 1))
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle
                in f"{row['username']} {row.get('display_name', '')} {row.get('email') or ''}".lower()
            ]
        if role:
            rows = [row for row in rows if row.get("role") == role]
        sort_key = {
            "display_name": lambda row: (row.get("display_name") or row.get("username") or "").lower(),
            "role": lambda row: row.get("role") or "",
            "created_at": lambda row: row.get("created_at") or "",
            "status": lambda row: row.get("active", 0),
        }.get(sort, lambda row: (row.get("display_name") or row.get("username") or "").lower())
        rows.sort(key=sort_key, reverse=direction.lower() == "desc")
        if page is None:
            return rows
        return paginate_rows(rows, page=page, per_page=per_page)

    @app.get("/api/roles")
    def workspace_roles(
        user: dict = Depends(authorize),
    ) -> dict:
        counts = saas.role_counts(organization_id(user))
        return {
            "items": [
                {
                    **item,
                    "user_count": counts.get(item["id"], 0),
                }
                for item in role_catalog()
            ],
            "current_role": user.get("role"),
            "permissions": user.get("permissions", []),
        }

    @app.post("/api/users")
    def create_user(
        payload: UserCreateRequest,
        current: dict = Depends(require_permission("users.invite")),
    ) -> dict:
        company = saas.get_organization(organization_id(current))
        if len(saas.member_ids(organization_id(current))) >= company["max_users"]:
            raise HTTPException(
                status_code=409,
                detail="Досягнуто ліміт користувачів компанії",
            )
        try:
            role = payload.role or ("admin" if payload.is_admin else "editor")
            return auth.create_user(
                payload.username,
                payload.password,
                is_admin=role == "admin",
                organization_id=organization_id(current),
                role=role,
                email=payload.email,
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="Такий логін вже існує") from exc
            raise

    @app.post("/api/invitations")
    def create_invitation(
        payload: InvitationRequest,
        current: dict = Depends(require_permission("users.invite")),
    ) -> dict:
        company = saas.get_organization(organization_id(current))
        if len(saas.member_ids(organization_id(current))) >= company["max_users"]:
            raise HTTPException(
                status_code=409,
                detail="Досягнуто ліміт користувачів компанії",
            )
        token = auth.create_action_token(
            "workspace_invite",
            organization_id=organization_id(current),
            email=payload.email,
            role=payload.role,
            created_by_user_id=current["id"],
            lifetime_hours=72,
        )
        saas.audit(
            organization_id(current),
            current["id"],
            "workspace.invitation_created",
            payload.email,
        )
        return {
            "email": payload.email.lower(),
            "role": payload.role,
            "expires_in_hours": 72,
            "url": public_url(f"invite?token={token}"),
        }

    @app.post("/api/password-reset/link")
    def create_password_reset_link(
        payload: PasswordResetLinkRequest,
        current: dict = Depends(require_permission("users.invite")),
    ) -> dict:
        ensure_organization_user(current, payload.user_id)
        auth.get_user(payload.user_id)
        token = auth.create_action_token(
            "password_reset",
            user_id=payload.user_id,
            organization_id=organization_id(current),
            created_by_user_id=current["id"],
            lifetime_hours=2,
        )
        return {
            "expires_in_hours": 2,
            "url": public_url(f"reset-password?token={token}"),
        }

    @app.get("/api/organizations")
    def organizations(_: dict = Depends(authorize_super_admin)) -> list[dict]:
        return saas.list_organizations()

    @app.get("/api/companies")
    def companies(_: dict = Depends(authorize_super_admin)) -> list[dict]:
        return saas.list_companies()

    def normalize_update_time(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Некоректна дата показу оновлення",
            ) from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    def localized_update_payload(payload: ServiceUpdateRequest) -> dict:
        title = payload.title.strip()
        body = payload.body.strip()
        legacy_text = f"{title} {body}"
        legacy_is_english = bool(re.search(r"[A-Za-z]", legacy_text)) and not bool(
            re.search(r"[А-Яа-яІіЇїЄєҐґ]", legacy_text)
        )
        title_uk = payload.title_uk.strip()
        body_uk = payload.body_uk.strip()
        title_en = payload.title_en.strip()
        body_en = payload.body_en.strip()
        if not any((title_uk, body_uk, title_en, body_en)):
            if legacy_is_english:
                title_en, body_en = title, body
            else:
                title_uk, body_uk = title, body
        canonical_title = title_uk or title_en or title
        canonical_body = body_uk or body_en or body
        return {
            "title": canonical_title,
            "body": canonical_body,
            "title_uk": title_uk,
            "body_uk": body_uk,
            "title_en": title_en,
            "body_en": body_en,
        }

    @app.get("/api/service-updates")
    def service_updates(
        _: dict = Depends(authorize),
        limit: int = 30,
        locale: str = "uk",
    ) -> dict:
        items = saas.list_service_updates(limit=limit, locale=locale)
        return {
            "items": items,
            "latest_id": max((int(item["id"]) for item in items), default=0),
        }

    @app.get("/api/platform/service-updates")
    def platform_service_updates(
        _: dict = Depends(authorize_super_admin),
        limit: int = 100,
    ) -> dict:
        items = saas.list_service_updates(limit=limit, include_drafts=True)
        return {
            "items": items,
            "latest_id": max((int(item["id"]) for item in items), default=0),
        }

    @app.post("/api/platform/service-updates")
    def create_service_update(
        payload: ServiceUpdateRequest,
        user: dict = Depends(authorize_super_admin),
    ) -> dict:
        localized = localized_update_payload(payload)
        item = saas.create_service_update(
            **localized,
            category=payload.category,
            importance=payload.importance,
            status=payload.status,
            pinned=payload.pinned,
            visible_from=normalize_update_time(payload.visible_from),
            visible_until=normalize_update_time(payload.visible_until),
            created_by_user_id=user["id"],
        )
        saas.audit(
            organization_id(user),
            user["id"],
            "service_update_created",
            f"{item['id']}:{item['title']}",
        )
        return item

    @app.put("/api/platform/service-updates/{update_id}")
    def update_service_update(
        update_id: int,
        payload: ServiceUpdateRequest,
        user: dict = Depends(authorize_super_admin),
    ) -> dict:
        try:
            localized = localized_update_payload(payload)
            item = saas.update_service_update(
                update_id,
                **localized,
                category=payload.category,
                importance=payload.importance,
                status=payload.status,
                pinned=payload.pinned,
                visible_from=normalize_update_time(payload.visible_from),
                visible_until=normalize_update_time(payload.visible_until),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Оновлення не знайдено") from exc
        saas.audit(
            organization_id(user),
            user["id"],
            "service_update_updated",
            f"{item['id']}:{item['status']}:{item['title']}",
        )
        return item

    @app.get("/api/platform/referrals")
    def platform_referrals(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        report = referrals.platform_summary()
        codes = report["codes"]
        if search.strip():
            needle = search.strip().lower()
            codes = [
                row
                for row in codes
                if needle
                in f"{row['code']} {row.get('owner_username', '')} {row.get('owner_organization_name', '')}".lower()
            ]
        sort_key = {
            "code": lambda row: row.get("code") or "",
            "owner_username": lambda row: row.get("owner_username") or "",
            "clicks": lambda row: int(row.get("clicks") or 0),
            "signups": lambda row: int(row.get("signups") or 0),
            "status": lambda row: row.get("status") or "",
        }.get(sort, lambda row: int(row.get("signups") or 0))
        codes.sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(codes, page=page, per_page=per_page)
        return {
            **report,
            **page_data,
            "codes": page_data["items"],
        }

    def platform_usage_data(period: str) -> dict:
        now = datetime.now(timezone.utc)
        if period == "today":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "7d":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "all":
            since = None
        else:
            raise HTTPException(status_code=422, detail="Невідомий період звіту")

        users_by_id = {user["id"]: user for user in auth.list_users()}
        workspace_rows = []
        company_totals: dict[int, dict] = {}
        user_rows = []
        model_rows = []
        totals = {
            "operations": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "text_generations": 0,
            "image_generations": 0,
            "cost": 0.0,
        }
        since_value = since.strftime("%Y-%m-%d %H:%M:%S") if since else None
        for workspace in saas.list_organizations():
            report = repository.for_organization(workspace["id"]).usage_summary(
                since=since_value
            )
            workspace_totals = report["totals"]
            workspace_rows.append(
                {
                    "organization_id": workspace["id"],
                    "organization_name": workspace["name"],
                    "workspace_name": workspace["name"],
                    "company_id": workspace["company_id"],
                    "company_name": workspace["company_name"],
                    **workspace_totals,
                }
            )
            aggregate = company_totals.setdefault(
                int(workspace["company_id"]),
                {
                    "company_id": workspace["company_id"],
                    "company_name": workspace["company_name"],
                    "organization_name": workspace["company_name"],
                    "workspace_count": 0,
                    **{key: 0 for key in totals},
                },
            )
            aggregate["workspace_count"] += 1
            for key in totals:
                totals[key] += workspace_totals[key]
                aggregate[key] += workspace_totals[key]
            for row in report["users"]:
                report_user = users_by_id.get(row["user_id"])
                user_rows.append(
                    {
                        "organization_id": workspace["id"],
                        "organization_name": workspace["name"],
                        "workspace_name": workspace["name"],
                        "company_id": workspace["company_id"],
                        "company_name": workspace["company_name"],
                        "user_id": row["user_id"],
                        "username": (
                            report_user["username"]
                            if report_user
                            else "Система / не визначено"
                        ),
                        **{
                            key: value
                            for key, value in row.items()
                            if key != "user_id"
                        },
                    }
                )
            for row in report["models"]:
                model_rows.append(
                    {
                        "organization_id": workspace["id"],
                        "organization_name": workspace["name"],
                        "workspace_name": workspace["name"],
                        "company_id": workspace["company_id"],
                        "company_name": workspace["company_name"],
                        **row,
                    }
                )
        totals["cost"] = round(float(totals["cost"]), 6)
        for aggregate in company_totals.values():
            aggregate["cost"] = round(float(aggregate["cost"]), 6)
        return {
            "period": period,
            "since": since.isoformat() if since else None,
            "totals": totals,
            "companies": sorted(
                company_totals.values(),
                key=lambda row: (-float(row["cost"]), row["company_name"]),
            ),
            "workspaces": sorted(
                workspace_rows,
                key=lambda row: (-float(row["cost"]), row["workspace_name"]),
            ),
            "users": sorted(
                user_rows,
                key=lambda row: (-float(row["cost"]), row["organization_name"]),
            ),
            "models": sorted(
                model_rows,
                key=lambda row: (-float(row["cost"]), row["organization_name"]),
            ),
        }

    def platform_organization_rows() -> list[dict]:
        users_by_id = {user["id"]: user for user in auth.list_users()}
        memberships = saas.all_memberships()
        members_by_organization: dict[int, list[dict]] = {}
        for membership in memberships:
            members_by_organization.setdefault(
                int(membership["organization_id"]),
                [],
            ).append(membership)
        activity = saas.last_activity_by_organization()
        rows = []
        for company in saas.list_organizations():
            tenant = repository.for_organization(company["id"])
            drafts = tenant.list_drafts(limit=10000)
            ideas = tenant.list_ideas(limit=10000)
            usage = tenant.usage_summary()["totals"]
            company_members = members_by_organization.get(company["id"], [])
            owner_membership = next(
                (item for item in company_members if item["role"] == "owner"),
                company_members[0] if company_members else None,
            )
            owner = (
                users_by_id.get(owner_membership["user_id"])
                if owner_membership
                else None
            )
            settings_row = saas.organization_settings(company["id"])
            rows.append(
                {
                    **company,
                    "owner_id": owner["id"] if owner else None,
                    "owner_name": (
                        (owner["display_name"] or owner["username"]) if owner else ""
                    ),
                    "owner_email": owner["email"] if owner else "",
                    "idea_count": len(ideas),
                    "draft_count": len(drafts),
                    "scheduled_count": sum(
                        item["status"] == "scheduled" for item in drafts
                    ),
                    "published_count": sum(
                        item["status"] == "published" for item in drafts
                    ),
                    "ai_cost": round(float(usage["cost"]), 6),
                    "onboarding_status": settings_row["onboarding_status"],
                    "last_activity_at": activity.get(company["id"]),
                }
            )
        return rows

    def platform_company_rows() -> list[dict]:
        workspace_rows = platform_organization_rows()
        workspaces_by_company: dict[int, list[dict]] = {}
        for workspace in workspace_rows:
            workspaces_by_company.setdefault(
                int(workspace["company_id"]),
                [],
            ).append(workspace)
        company_memberships = saas.all_company_memberships()
        users_by_id = {user["id"]: user for user in auth.list_users()}
        memberships_by_company: dict[int, list[dict]] = {}
        for membership in company_memberships:
            memberships_by_company.setdefault(
                int(membership["company_id"]),
                [],
            ).append(membership)
        rows = []
        for company in saas.list_companies():
            company_id = int(company["id"])
            workspaces = workspaces_by_company.get(company_id, [])
            members = memberships_by_company.get(company_id, [])
            owner_membership = next(
                (item for item in members if item["role"] == "owner"),
                members[0] if members else None,
            )
            owner = (
                users_by_id.get(int(owner_membership["user_id"]))
                if owner_membership
                else None
            )
            role_counts: dict[str, int] = {}
            for member in members:
                role = str(member["role"])
                role_counts[role] = role_counts.get(role, 0) + 1
            last_activity = max(
                (
                    str(item["last_activity_at"])
                    for item in workspaces
                    if item.get("last_activity_at")
                ),
                default=None,
            )
            rows.append(
                {
                    **company,
                    "workspace_count": len(workspaces),
                    "active_workspace_count": sum(
                        bool(item["active"]) for item in workspaces
                    ),
                    "user_count": len({int(item["user_id"]) for item in members}),
                    "owner_id": owner["id"] if owner else None,
                    "owner_name": (
                        (owner["display_name"] or owner["username"])
                        if owner else ""
                    ),
                    "owner_email": owner["email"] if owner else "",
                    "role_counts": role_counts,
                    "idea_count": sum(int(item["idea_count"]) for item in workspaces),
                    "draft_count": sum(int(item["draft_count"]) for item in workspaces),
                    "scheduled_count": sum(
                        int(item["scheduled_count"]) for item in workspaces
                    ),
                    "published_count": sum(
                        int(item["published_count"]) for item in workspaces
                    ),
                    "ai_cost": round(
                        sum(float(item["ai_cost"]) for item in workspaces),
                        6,
                    ),
                    "last_activity_at": last_activity,
                }
            )
        return rows

    def platform_client_rows() -> list[dict]:
        users = auth.list_users()
        memberships = saas.all_memberships()
        company_memberships = saas.all_company_memberships()
        memberships_by_user: dict[int, list[dict]] = {}
        for membership in memberships:
            memberships_by_user.setdefault(int(membership["user_id"]), []).append(
                membership
            )
        companies_by_user: dict[int, list[dict]] = {}
        for membership in company_memberships:
            companies_by_user.setdefault(int(membership["user_id"]), []).append(
                membership
            )
        referral_report = referrals.platform_summary()
        signup_by_user = {
            int(item["new_user_id"]): item for item in referral_report["signups"]
        }
        usage_by_user: dict[int, dict] = {}
        for row in platform_usage_data("all")["users"]:
            if row["user_id"] is None:
                continue
            current = usage_by_user.setdefault(
                int(row["user_id"]),
                {"operations": 0, "cost": 0.0},
            )
            current["operations"] += int(row["operations"])
            current["cost"] += float(row["cost"])
        rows = []
        for user in users:
            user_memberships = memberships_by_user.get(user["id"], [])
            user_companies = companies_by_user.get(user["id"], [])
            primary = user_memberships[0] if user_memberships else None
            primary_company = user_companies[0] if user_companies else None
            signup = signup_by_user.get(user["id"])
            usage = usage_by_user.get(user["id"], {"operations": 0, "cost": 0.0})
            rows.append(
                {
                    **user,
                    "organization_count": len(user_memberships),
                    "workspace_count": len(user_memberships),
                    "company_count": len(user_companies),
                    "primary_company_id": (
                        primary_company["company_id"] if primary_company else None
                    ),
                    "primary_company_name": (
                        primary_company["company_name"] if primary_company else ""
                    ),
                    "company_role": (
                        primary_company["role"] if primary_company else ""
                    ),
                    "primary_organization_id": (
                        primary["organization_id"] if primary else None
                    ),
                    "primary_organization_name": (
                        primary["organization_name"] if primary else ""
                    ),
                    "role": (
                        "platform_admin"
                        if user["is_super_admin"]
                        else primary["role"] if primary else ""
                    ),
                    "registration_source": "referral" if signup else "direct",
                    "referral_code": signup["referral_code"] if signup else "",
                    "referrer_username": (
                        signup["referrer_username"] if signup else ""
                    ),
                    "utm_source": signup["utm_source"] if signup else "",
                    "utm_campaign": signup["utm_campaign"] if signup else "",
                    "usage_operations": usage["operations"],
                    "ai_cost": round(float(usage["cost"]), 6),
                }
            )
        return rows

    @app.get("/api/platform/overview")
    def platform_overview(_: dict = Depends(authorize_super_admin)) -> dict:
        now = datetime.now(timezone.utc)
        users = platform_client_rows()
        workspaces = platform_organization_rows()
        companies = platform_company_rows()
        referrals_report = referrals.platform_summary()
        usage = platform_usage_data("month")
        today = now.date().isoformat()
        week_start = (now - timedelta(days=7)).date().isoformat()
        month_start = now.replace(day=1).date().isoformat()
        registrations_by_day: dict[str, int] = {}
        for user in users:
            day = str(user["created_at"])[:10]
            registrations_by_day[day] = registrations_by_day.get(day, 0) + 1
        return {
            "metrics": {
                "registrations_today": sum(
                    str(user["created_at"])[:10] == today for user in users
                ),
                "registrations_7d": sum(
                    str(user["created_at"])[:10] >= week_start for user in users
                ),
                "users_total": len(users),
                "organizations_total": len(companies),
                "companies_total": len(companies),
                "workspaces_total": len(workspaces),
                "active_organizations": sum(
                    bool(item["active"]) for item in companies
                ),
                "active_companies": sum(bool(item["active"]) for item in companies),
                "new_workspaces_month": sum(
                    str(item["created_at"])[:10] >= month_start
                    for item in workspaces
                ),
                "ai_cost_month": usage["totals"]["cost"],
                "publications_total": sum(
                    item["published_count"] for item in companies
                ),
                "referral_signups": len(referrals_report["signups"]),
            },
            "registrations_by_day": [
                {"day": day, "count": count}
                for day, count in sorted(registrations_by_day.items())[-30:]
            ],
            "top_organizations": sorted(
                companies,
                key=lambda item: -float(item["ai_cost"]),
            )[:10],
            "top_companies": sorted(
                companies,
                key=lambda item: -float(item["ai_cost"]),
            )[:10],
        }

    @app.get("/api/platform/clients")
    def platform_clients(
        source: str = "",
        period: str = "",
        active: str = "",
        workspace: str = "",
        search: str = "",
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        rows = platform_client_rows()
        if source in {"referral", "direct"}:
            rows = [row for row in rows if row["registration_source"] == source]
        if active in {"yes", "no"}:
            expected = active == "yes"
            rows = [row for row in rows if bool(row["active"]) == expected]
        if workspace in {"yes", "no"}:
            expected = workspace == "yes"
            rows = [
                row
                for row in rows
                if bool(row["organization_count"]) == expected
            ]
        if period in {"7d", "30d"}:
            since = (
                datetime.now(timezone.utc)
                - timedelta(days=7 if period == "7d" else 30)
            ).date().isoformat()
            rows = [row for row in rows if str(row["created_at"])[:10] >= since]
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle
                in " ".join(
                    [
                        row["username"],
                        row["display_name"],
                        row["email"] or "",
                        row["primary_organization_name"],
                    ]
                ).lower()
            ]
        sort_key = {
            "display_name": lambda row: (
                row.get("display_name") or row.get("username") or ""
            ).lower(),
            "created_at": lambda row: row.get("created_at") or "",
            "last_login_at": lambda row: row.get("last_login_at") or "",
            "company_count": lambda row: int(row.get("company_count") or 0),
            "workspace_count": lambda row: int(row.get("workspace_count") or 0),
            "ai_cost": lambda row: float(row.get("ai_cost") or 0),
        }.get(sort, lambda row: row.get("created_at") or "")
        rows.sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(rows, page=page, per_page=per_page)
        return {**page_data, "clients": page_data["items"]}

    @app.get("/api/platform/clients/{user_id}")
    def platform_client_detail(
        user_id: int,
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        client = next(
            (item for item in platform_client_rows() if item["id"] == user_id),
            None,
        )
        if client is None:
            raise HTTPException(status_code=404, detail="Клієнта не знайдено")
        memberships = saas.memberships_for_user(user_id)
        company_memberships = saas.company_memberships_for_user(user_id)
        organization_rows = {
            item["id"]: item for item in platform_organization_rows()
        }
        company_rows = {
            item["id"]: item for item in platform_company_rows()
        }
        return {
            "client": client,
            "companies": [
                {
                    **company_rows.get(item["company_id"], {}),
                    "role": item["role"],
                }
                for item in company_memberships
            ],
            "workspaces": [
                {
                    **organization_rows.get(item["organization_id"], {}),
                    "role": item["role"],
                }
                for item in memberships
            ],
            "organizations": [
                {
                    **organization_rows.get(item["organization_id"], {}),
                    "role": item["role"],
                }
                for item in memberships
            ],
            "content_totals": {
                "ideas": sum(
                    int(organization_rows.get(item["organization_id"], {}).get("idea_count", 0))
                    for item in memberships
                ),
                "drafts": sum(
                    int(organization_rows.get(item["organization_id"], {}).get("draft_count", 0))
                    for item in memberships
                ),
                "published": sum(
                    int(organization_rows.get(item["organization_id"], {}).get("published_count", 0))
                    for item in memberships
                ),
            },
            "activity": saas.list_audit_events(limit=200, user_id=user_id),
            "logins": auth.list_login_events(limit=200, user_id=user_id),
        }

    @app.get("/api/platform/organizations/details")
    def platform_organizations(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        rows = platform_organization_rows()
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle
                in f"{row['name']} {row['slug']} {row.get('owner_name', '')} {row.get('owner_email', '')}".lower()
            ]
        page_data = paginate_rows(rows, page=page, per_page=per_page)
        return {**page_data, "organizations": page_data["items"]}

    @app.get("/api/platform/companies")
    def platform_companies(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        rows = platform_company_rows()
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle
                in (
                    f"{row['name']} {row['slug']} "
                    f"{row.get('owner_name', '')} {row.get('owner_email', '')}"
                ).lower()
            ]
        sort_key = {
            "name": lambda row: row.get("name", "").lower(),
            "created_at": lambda row: row.get("created_at") or "",
            "workspace_count": lambda row: int(row.get("workspace_count") or 0),
            "user_count": lambda row: int(row.get("user_count") or 0),
            "ai_cost": lambda row: float(row.get("ai_cost") or 0),
        }.get(sort, lambda row: row.get("created_at") or "")
        rows.sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(rows, page=page, per_page=per_page)
        return {**page_data, "companies": page_data["items"]}

    @app.get("/api/platform/companies/{company_id}")
    def platform_company_detail(
        company_id: int,
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        company = next(
            (
                item
                for item in platform_company_rows()
                if int(item["id"]) == company_id
            ),
            None,
        )
        if company is None:
            raise HTTPException(status_code=404, detail="Компанію не знайдено")
        workspaces = [
            item
            for item in platform_organization_rows()
            if int(item["company_id"]) == company_id
        ]
        users = saas.company_users(company_id)
        activity = sorted(
            (
                event
                for workspace in workspaces
                for event in saas.list_audit_events(
                    limit=100,
                    organization_id=int(workspace["id"]),
                )
            ),
            key=lambda item: str(item["created_at"]),
            reverse=True,
        )[:200]
        return {
            "company": company,
            "workspaces": workspaces,
            "users": users,
            "activity": activity,
        }

    @app.get("/api/platform/organizations/{target_organization_id}")
    def platform_organization_detail(
        target_organization_id: int,
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        organization = next(
            (
                item
                for item in platform_organization_rows()
                if item["id"] == target_organization_id
            ),
            None,
        )
        if organization is None:
            raise HTTPException(status_code=404, detail="Компанію не знайдено")
        return {
            "organization": organization,
            "users": auth.list_users(target_organization_id),
            "activity": saas.list_audit_events(
                limit=200,
                organization_id=target_organization_id,
            ),
        }

    @app.get("/api/platform/users")
    def platform_users(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        rows = platform_client_rows()
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle
                in f"{row['username']} {row.get('display_name', '')} {row.get('email') or ''}".lower()
            ]
        sort_key = {
            "display_name": lambda row: (
                row.get("display_name") or row.get("username") or ""
            ).lower(),
            "created_at": lambda row: row.get("created_at") or "",
            "last_login_at": lambda row: row.get("last_login_at") or "",
            "company_count": lambda row: int(row.get("company_count") or 0),
            "workspace_count": lambda row: int(row.get("workspace_count") or 0),
        }.get(sort, lambda row: row.get("created_at") or "")
        rows.sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(rows, page=page, per_page=per_page)
        return {**page_data, "users": page_data["items"]}

    @app.get("/api/platform/activity")
    def platform_activity(
        limit: int = 300,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        events = saas.list_audit_events(limit=min(2000, max(limit, page * per_page)))
        if search.strip():
            needle = search.strip().lower()
            events = [
                row
                for row in events
                if needle
                in f"{row.get('action', '')} {row.get('details', '')} {row.get('username', '')} {row.get('organization_name', '')}".lower()
            ]
        sort_key = {
            "created_at": lambda row: row.get("created_at") or "",
            "action": lambda row: row.get("action") or "",
            "organization_name": lambda row: row.get("organization_name") or "",
        }.get(sort, lambda row: row.get("created_at") or "")
        events.sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(events, page=page, per_page=per_page)
        return {
            **page_data,
            "events": page_data["items"],
            "logins": auth.list_login_events(limit=per_page),
        }

    @app.get("/api/platform/usage")
    def platform_usage(
        period: str = "month",
        page: int = 1,
        per_page: int = 25,
        sort: str = "cost",
        direction: str = "desc",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        report = platform_usage_data(period)
        sort_key = {
            "company_name": lambda row: (
                row.get("company_name") or row.get("organization_name") or ""
            ).lower(),
            "workspace_count": lambda row: int(row.get("workspace_count") or 0),
            "operations": lambda row: int(row.get("operations") or 0),
            "text_generations": lambda row: int(row.get("text_generations") or 0),
            "image_generations": lambda row: int(row.get("image_generations") or 0),
            "cost": lambda row: float(row.get("cost") or 0),
        }.get(sort, lambda row: float(row.get("cost") or 0))
        report["companies"].sort(key=sort_key, reverse=direction.lower() != "asc")
        page_data = paginate_rows(
            report["companies"],
            page=page,
            per_page=per_page,
        )
        return {
            **report,
            **page_data,
            "companies": page_data["items"],
        }

    @app.post("/api/platform/bulk/{entity}")
    def platform_bulk_action(
        entity: str,
        payload: BulkActionRequest,
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
        ids = [int(item) for item in payload.ids]
        if payload.action not in {"activate", "deactivate"}:
            raise HTTPException(
                status_code=422,
                detail="Для platform списків доступна лише зміна статусу",
            )
        active = payload.action == "activate"
        if entity in {"clients", "users"}:
            changed = auth.set_users_active(ids, active)
        elif entity == "companies":
            changed = saas.set_companies_active(ids, active)
        elif entity == "organizations":
            changed = saas.set_organizations_active(ids, active)
        elif entity == "referrals":
            changed = referrals.set_codes_status(
                ids,
                "active" if active else "disabled",
            )
        else:
            raise HTTPException(status_code=404, detail="Список не знайдено")
        return {"changed": changed}

    @app.post("/api/companies")
    @app.post("/api/organizations")
    def create_organization(
        payload: OrganizationCreateRequest,
        current: dict = Depends(authorize_super_admin),
    ) -> dict:
        company = None
        owner = None
        try:
            company = saas.create_company(
                name=payload.name,
                slug=payload.slug or generate_slug(payload.name),
                max_workspaces=payload.max_workspaces,
            )
            workspace_name = payload.workspace_name.strip() or payload.name
            organization = saas.create_organization(
                name=workspace_name,
                slug=(
                    payload.workspace_slug
                    or generate_slug(workspace_name)
                ),
                max_users=payload.max_users,
                max_channels=payload.max_channels,
                monthly_publications=payload.monthly_publications,
                monthly_ai_budget=payload.monthly_ai_budget,
                monthly_text_generations=payload.monthly_text_generations,
                monthly_image_generations=payload.monthly_image_generations,
                company_id=company["id"],
            )
            owner = auth.create_user(
                payload.owner_username,
                payload.owner_password,
                is_admin=True,
                organization_id=organization["id"],
                role="owner",
                email=payload.owner_email,
                display_name=payload.owner_display_name,
            )
            repository.for_organization(organization["id"])
        except Exception as exc:
            if owner is not None:
                auth.delete_user(owner["id"])
            if company is not None:
                saas.delete_empty_company(int(company["id"]))
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="Компанія або логін уже існує",
                ) from exc
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise
        saas.audit(
            organization["id"],
            current["id"],
            "company_created",
            company["slug"],
        )
        saas.audit(
            organization["id"],
            current["id"],
            "workspace_created",
            organization["slug"],
        )
        saas.audit(
            organization["id"],
            current["id"],
            "organization_created",
            organization["slug"],
        )
        saas.audit(
            organization["id"],
            owner["id"],
            "user_registered",
            payload.owner_email or payload.owner_username,
        )
        return {
            **company,
            "company": company,
            "workspace": organization,
            "organization": organization,
            "owner": owner,
        }

    @app.get("/api/company")
    def current_company(user: dict = Depends(authorize)) -> dict:
        current_organization_id = organization_id(user)
        workspace = saas.get_organization(current_organization_id)
        company = saas.company_for_organization(current_organization_id)
        now = datetime.now(timezone.utc)
        subscription_status = workspace.get("subscription_status") or workspace.get("plan_code") or "custom"
        if subscription_status == "custom" and workspace.get("plan_code") == "trial":
            subscription_status = "trial"
        elif subscription_status == "custom" and workspace.get("plan_code") in {"start", "growth", "scale"}:
            subscription_status = "active"
        is_trial = subscription_status == "trial" or workspace.get("plan_code") == "trial"
        expires_value = workspace.get("trial_ends_at") if is_trial else workspace.get("plan_expires_at")
        expires_at = None
        days_left = None
        if expires_value:
            expires_at = datetime.fromisoformat(str(expires_value).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            seconds_left = (expires_at - now).total_seconds()
            days_left = max(0, int((seconds_left + 86399) // 86400))
        if expires_at and expires_at <= now:
            subscription_status = "expired"
        text_count = repository.current_month_usage_units("text")
        image_count = repository.current_month_usage_units("image")
        publication_count = repository.current_month_publications()
        text_limit = int(workspace.get("monthly_text_generations") or 0)
        image_limit = int(workspace.get("monthly_image_generations") or 0)
        publication_limit = int(workspace.get("monthly_publications") or 0)
        quota_state = {
            "subscription_status": subscription_status,
            "trial_ends_at": workspace.get("trial_ends_at"),
            "plan_expires_at": workspace.get("plan_expires_at"),
            "days_left": days_left,
            "text": {"used": text_count, "limit": text_limit},
            "image": {"used": image_count, "limit": image_limit},
            "publications": {"used": publication_count, "limit": publication_limit},
        }
        try:
            telegram_connection = saas.telegram_connection(
                current_organization_id,
                include_token=False,
            )
        except KeyError:
            telegram_connection = None
        if current_organization_id == 1 and settings.telegram_bot_token:
            telegram_connection = {
                **(telegram_connection or {}),
                "organization_id": 1,
                "channel_id": (
                    (telegram_connection or {}).get("channel_id")
                    or settings.telegram_channel
                ),
                "configured": True,
                "legacy": True,
            }
        return {
            **workspace,
            "company": {
                **company,
                "role": saas.company_role_for_user(company["id"], user["id"])
                or ("platform_admin" if user.get("is_super_admin") else "member"),
                "workspace_count": len(
                    saas.workspaces_for_company(int(company["id"]))
                ),
                "user_count": len(saas.company_users(int(company["id"]))),
            },
            "settings": saas.organization_settings(current_organization_id),
            "telegram": telegram_connection,
            "user_count": len(saas.member_ids(current_organization_id)),
            "ai_spend": repository.current_month_cost(),
            "publication_count": publication_count,
            "text_generation_count": text_count,
            "image_generation_count": image_count,
            "monthly_text_generations": text_limit,
            "monthly_image_generations": image_limit,
            "trial_ends_at": workspace.get("trial_ends_at"),
            "subscription_status": subscription_status,
            "quota_state": quota_state,
        }

    @app.get("/api/plans")
    def plans(user: dict = Depends(authorize)) -> dict:
        company = saas.get_organization(organization_id(user))
        return {
            "plans": public_plans(),
            "current_plan": company.get("plan_code") or "custom",
            "expires_at": company.get("plan_expires_at"),
            "payment_method": "Telegram Stars",
        }

    @app.post("/api/billing/checkout")
    async def create_checkout(
        payload: CheckoutRequest,
        user: dict = Depends(require_permission("billing.manage")),
    ) -> dict:
        try:
            return await billing.create_checkout(
                organization_id=organization_id(user),
                user_id=user["id"],
                plan_code=payload.plan_code,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Тариф не знайдено") from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Не вдалося створити рахунок Telegram Stars",
            ) from exc

    @app.get("/api/rubrics")
    def rubrics(
        page: int | None = None,
        per_page: int = 25,
        search: str = "",
        active: str = "",
        sort: str = "name",
        direction: str = "asc",
        _: dict = Depends(authorize),
    ) -> list[dict] | dict:
        if page is None:
            return repository.list_rubrics(include_inactive=True)
        return repository.list_rubrics_page(
            page=page,
            per_page=per_page,
            search=search,
            active=active,
            sort=sort,
            direction=direction,
        )

    @app.post("/api/rubrics")
    def create_rubric(
        payload: RubricCreateRequest,
        user: dict = Depends(require_permission("rubrics.manage")),
    ) -> dict:
        slug = generate_slug(payload.slug or payload.name)
        if not slug or slug in {"all", "general"}:
            raise HTTPException(status_code=422, detail="Вкажіть інший slug рубрики")
        if payload.default_link and not payload.default_link.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Посилання має починатися з http:// або https://")
        try:
            rubric = repository.add_rubric(
                slug=slug,
                name=payload.name.strip(),
                description=payload.description.strip(),
                instructions=payload.instructions.strip(),
                default_link=payload.default_link.strip(),
                goal=payload.goal.strip(),
                tone=payload.tone.strip(),
                example_topic=payload.example_topic.strip(),
                active=payload.active,
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="Такий slug уже існує") from exc
            raise
        saas.audit(organization_id(user), user["id"], "rubric_created", slug)
        return rubric

    @app.put("/api/rubrics/{rubric_id}")
    def update_rubric(
        rubric_id: int,
        payload: RubricUpdateRequest,
        user: dict = Depends(require_permission("rubrics.manage")),
    ) -> dict:
        if payload.default_link and not payload.default_link.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Посилання має починатися з http:// або https://")
        try:
            rubric = repository.update_rubric(
                rubric_id,
                name=payload.name.strip(),
                description=payload.description.strip(),
                instructions=payload.instructions.strip(),
                default_link=payload.default_link.strip(),
                active=payload.active,
                goal=payload.goal.strip(),
                tone=payload.tone.strip(),
                example_topic=payload.example_topic.strip(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Рубрику не знайдено") from exc
        saas.audit(organization_id(user), user["id"], "rubric.updated", rubric["slug"])
        return rubric

    @app.post("/api/rubrics/bulk")
    def bulk_rubrics(
        payload: BulkActionRequest,
        _: dict = Depends(require_permission("rubrics.manage")),
    ) -> dict:
        ids = [int(item) for item in payload.ids]
        if payload.action == "activate":
            changed = repository.set_rubrics_active(ids, True)
        elif payload.action == "deactivate":
            changed = repository.set_rubrics_active(ids, False)
        elif payload.action == "delete":
            changed = repository.delete_rubrics(ids)
        else:
            raise HTTPException(status_code=422, detail="Невідома масова дія")
        return {"changed": changed}

    @app.put("/api/workspace/appearance")
    def update_workspace_appearance(
        payload: WorkspaceAppearanceRequest,
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        for asset_id in {
            payload.avatar_asset_id,
            payload.logo_asset_id,
            payload.favicon_asset_id,
        } - {None}:
            repository.get_reference(int(asset_id))
        company = saas.update_organization(
            organization_id(user),
            name=payload.name,
            slug=payload.slug or generate_slug(payload.name),
        )
        appearance = saas.update_organization_settings(
            organization_id(user),
            workspace_short_description=payload.short_description.strip(),
            brand_primary_color=payload.primary_color.lower(),
            brand_secondary_color=payload.secondary_color.lower(),
            workspace_avatar_asset_id=payload.avatar_asset_id,
            brand_logo_asset_id=payload.logo_asset_id,
            favicon_asset_id=payload.favicon_asset_id,
        )
        company = {
            **company,
            "workspace_short_description": appearance.get("workspace_short_description"),
            "workspace_avatar_asset_id": appearance.get("workspace_avatar_asset_id"),
            "brand_logo_asset_id": appearance.get("brand_logo_asset_id"),
            "brand_primary_color": appearance.get("brand_primary_color"),
            "brand_secondary_color": appearance.get("brand_secondary_color"),
        }
        return {"company": company, "settings": appearance}

    @app.post("/api/workspace/appearance/assets")
    async def upload_workspace_appearance_asset(
        kind: str = Form(...),
        file: UploadFile = File(...),
        user: dict = Depends(require_permission("workspace.settings")),
    ) -> dict:
        if kind not in {"avatar", "logo"}:
            raise HTTPException(status_code=422, detail="Невідомий тип зображення")
        media_type = file.content_type or ""
        allowed_types = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }
        if media_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail="Підтримуються PNG, JPG або WebP",
            )
        content = await file.read()
        if not content or len(content) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=422,
                detail="Зображення має бути меншим за 5 MB",
            )
        try:
            image = Image.open(BytesIO(content))
            image.load()
            width, height = image.size
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="Пошкоджений файл зображення",
            ) from exc
        if width < 256 or height < 120 or width > 4096 or height > 4096:
            raise HTTPException(
                status_code=422,
                detail="Розмір зображення має бути від 256×120 до 4096×4096 px",
            )
        ratio = width / height
        if kind == "avatar" and not 0.8 <= ratio <= 1.25:
            raise HTTPException(
                status_code=422,
                detail="Для аватара потрібне квадратне зображення 1:1",
            )
        if kind == "logo" and not 0.5 <= ratio <= 8:
            raise HTTPException(
                status_code=422,
                detail="Для логотипа використайте пропорції від 1:2 до 8:1",
            )
        suffix = allowed_types[media_type]
        _, reference_dir = organization_dirs(repository.organization_id)
        path = reference_dir / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        reference = repository.add_reference(
            name=("Аватар workspace" if kind == "avatar" else "Логотип компанії"),
            filename=(file.filename or path.name)[:200],
            path=str(path),
            media_type=media_type,
            material_type=f"workspace_{kind}",
            description=f"Зображення оформлення {width}×{height}",
            created_by_user_id=user["id"],
        )
        return {
            **reference,
            "url": f"api/references/{reference['id']}/image",
            "width": width,
            "height": height,
        }

    @app.get("/api/workspaces/{workspace_id}/appearance/{kind}")
    def workspace_appearance_image(
        workspace_id: int,
        kind: str,
        user: dict = Depends(authorize),
    ) -> FileResponse:
        if kind not in {"avatar", "logo"}:
            raise HTTPException(status_code=404, detail="Зображення не знайдено")
        if not user.get("is_super_admin") and not saas.role_for_user(
            workspace_id,
            user["id"],
        ):
            raise HTTPException(status_code=404, detail="Workspace не знайдено")
        try:
            appearance = saas.organization_settings(workspace_id)
            asset_id = appearance[
                "workspace_avatar_asset_id"
                if kind == "avatar"
                else "brand_logo_asset_id"
            ]
            if not asset_id:
                raise KeyError("Appearance asset is not configured")
            reference = repository.for_organization(workspace_id).get_reference(
                int(asset_id)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail="Зображення не знайдено",
            ) from exc
        path = Path(reference["path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Файл зображення відсутній")
        return FileResponse(path, media_type=reference["media_type"])

    @app.put("/api/company/telegram")
    async def connect_telegram(
        payload: TelegramConnectionRequest,
        user: dict = Depends(require_permission("channels.manage")),
    ) -> dict:
        organization_id = int(user.get("organization_id") or 1)
        validation = await validate_telegram_connection(payload)
        try:
            connection = saas.save_telegram_connection(
                organization_id,
                channel_id=payload.channel_id,
                bot_token=payload.bot_token,
                bot_username=validation["bot_username"],
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Шифрування секретів ще не налаштовано",
            ) from exc
        saas.audit(
            organization_id,
            user["id"],
            "telegram_connected",
            payload.channel_id,
        )
        saas.update_organization_settings(
            organization_id,
            onboarding_status="in_progress",
            onboarding_step=4,
        )
        return connection

    @app.post(
        "/api/company/telegram/validate",
        response_model=TelegramValidationResponse,
    )
    async def validate_company_telegram(
        payload: TelegramConnectionRequest,
        _: dict = Depends(require_permission("channels.manage")),
    ) -> dict:
        return await validate_telegram_connection(payload)

    @app.get("/api/integrations/instagram/status")
    def instagram_status(user: dict = Depends(authorize)) -> dict:
        current_organization_id = organization_id(user)
        setup = instagram_setup_status()
        try:
            connection = saas.social_connection_by_platform(
                current_organization_id,
                "instagram",
                include_token=False,
            )
        except KeyError:
            connection = None
        return {
            **setup,
            "connected": bool(connection and connection.get("active")),
            "connection": connection,
            "soon": [
                {"platform": "facebook", "label": "Facebook", "status": "soon"},
                {"platform": "whatsapp", "label": "WhatsApp", "status": "soon"},
                {"platform": "linkedin", "label": "LinkedIn", "status": "soon"},
                {"platform": "tiktok", "label": "TikTok", "status": "soon"},
            ],
        }

    @app.post("/api/integrations/instagram/connect-url")
    def instagram_connect(
        response: Response,
        user: dict = Depends(require_permission("channels.manage")),
    ) -> dict:
        setup = instagram_setup_status()
        if setup["setup_required"]:
            return {
                **setup,
                "url": "",
                "message": "Meta App ще не налаштовано. Telegram працює без змін.",
            }
        try:
            state = sign_instagram_state(user)
            url = instagram_connect_url(settings, state)
        except InstagramSetupError as exc:
            return {**setup, "setup_required": True, "url": "", "message": str(exc)}
        response.set_cookie(
            "instagram_oauth_state",
            state,
            max_age=15 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        return {"url": url, "setup_required": False}

    @app.get("/oauth/instagram/callback")
    async def instagram_callback(
        request: Request,
        response: Response,
        code: str = "",
        state: str = "",
        error: str = "",
        instagram_oauth_state: str | None = Cookie(default=None),
        voicerhub_session: str | None = Cookie(default=None),
    ) -> RedirectResponse:
        redirect = RedirectResponse(
            f"{settings.admin_base_path.rstrip('/')}/settings?tab=integrations"
        )
        redirect.delete_cookie("instagram_oauth_state")
        if error:
            redirect.headers["location"] += "&instagram=error"
            return redirect
        user = auth.session_user(voicerhub_session)
        if user is None:
            redirect.headers["location"] = f"{settings.admin_base_path.rstrip('/')}/login"
            return redirect
        repository.use(organization_id(user))
        if not has_permission(
            user.get("role") or "viewer",
            "channels.manage",
            platform_admin=bool(user.get("is_super_admin")),
        ):
            raise HTTPException(status_code=403, detail="Недостатньо прав")
        payload = verify_instagram_state(state, instagram_oauth_state or "", user)
        setup = instagram_setup_status()
        if setup["setup_required"]:
            redirect.headers["location"] += "&instagram=setup"
            return redirect
        client = MetaInstagramClient(settings)
        try:
            token = await client.exchange_code(code, instagram_redirect_uri(settings))
            long_token = await client.long_lived_token(token["access_token"])
            account = await client.resolve_account(long_token.get("access_token") or token["access_token"])
            expires_at = ""
            if long_token.get("expires_in"):
                expires_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=int(long_token["expires_in"]))
                ).isoformat()
            connection = saas.save_social_connection(
                int(payload["organization_id"]),
                platform="instagram",
                external_account_id=account.instagram_id,
                username=account.username,
                display_name=account.display_name,
                account_type=account.account_type,
                page_id=account.page_id,
                page_name=account.page_name,
                access_token=account.access_token,
                token_expires_at=expires_at,
                permissions=account.permissions or [],
                metadata={"source": "facebook_login"},
            )
            saas.audit(
                int(payload["organization_id"]),
                user["id"],
                "instagram_connected",
                connection.get("username") or connection.get("external_account_id") or "",
                ip_address=request_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
            redirect.headers["location"] += "&instagram=connected"
            return redirect
        except Exception as exc:
            try:
                current = saas.social_connection_by_platform(
                    int(payload["organization_id"]),
                    "instagram",
                    include_token=False,
                )
                saas.set_social_connection_error(int(current["id"]), str(exc))
            except KeyError:
                pass
            redirect.headers["location"] += "&instagram=error"
            return redirect

    @app.delete("/api/integrations/instagram")
    def instagram_disconnect(
        user: dict = Depends(require_permission("channels.manage")),
    ) -> dict:
        try:
            connection = saas.disable_social_connection(organization_id(user), "instagram")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Instagram не підключено") from exc
        saas.audit(organization_id(user), user["id"], "instagram_disconnected")
        return connection

    @app.get("/media/instagram/{draft_id}")
    def instagram_media(
        draft_id: int,
        org: int,
        exp: int,
        sig: str,
        variant: str = "",
    ) -> FileResponse:
        if not verify_media_signature(
            settings,
            organization_id=org,
            draft_id=draft_id,
            variant=variant,
            expires_at=exp,
            signature=sig,
        ):
            raise HTTPException(status_code=403, detail="Media URL недійсний або застарів")
        repo = repository.for_organization(org)
        if variant == "instagram":
            try:
                media_path = Path(repo.get_social_variant(draft_id, "instagram")["image_path"])
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Зображення не знайдено") from exc
        else:
            try:
                media_path = Path(repo.draft_record(draft_id)["image_path"])
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc
        if not media_path.is_file():
            raise HTTPException(status_code=404, detail="Файл зображення відсутній")
        media_type = "image/jpeg" if media_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        return FileResponse(media_path, media_type=media_type)

    @app.patch("/api/users/{user_id}")
    def update_user(
        user_id: int,
        payload: UserUpdateRequest,
        current: dict = Depends(require_permission("roles.manage")),
    ) -> dict:
        ensure_organization_user(current, user_id)
        if user_id == current["id"] and payload.active is False:
            raise HTTPException(status_code=422, detail="Не можна заблокувати себе")
        if user_id == current["id"] and payload.is_admin is False:
            raise HTTPException(status_code=422, detail="Не можна забрати свою роль")
        try:
            return auth.update_user(
                user_id,
                is_admin=(
                    payload.role == "admin"
                    if payload.role is not None
                    else payload.is_admin
                ),
                active=payload.active,
                organization_id=organization_id(current),
                role=payload.role,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/users/{user_id}")
    def remove_workspace_user(
        user_id: int,
        current: dict = Depends(require_permission("users.remove")),
    ) -> dict:
        ensure_organization_user(current, user_id)
        if user_id == current["id"]:
            raise HTTPException(status_code=422, detail="Не можна видалити себе")
        try:
            saas.remove_member(organization_id(current), user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"removed": user_id}

    @app.post("/api/users/bulk")
    def bulk_users(
        payload: BulkActionRequest,
        current: dict = Depends(require_permission("roles.manage")),
    ) -> dict:
        ids = [int(item) for item in payload.ids if int(item) != current["id"]]
        changed = 0
        if payload.action == "role":
            if payload.value not in WORKSPACE_ROLES - {"owner"}:
                raise HTTPException(status_code=422, detail="Невідома роль")
            for user_id in ids:
                ensure_organization_user(current, user_id)
                auth.update_user(
                    user_id,
                    organization_id=organization_id(current),
                    role=payload.value,
                    is_admin=payload.value == "admin",
                )
                changed += 1
        elif payload.action == "deactivate":
            for user_id in ids:
                ensure_organization_user(current, user_id)
                auth.update_user(user_id, active=False)
                changed += 1
        elif payload.action == "remove":
            for user_id in ids:
                ensure_organization_user(current, user_id)
                try:
                    saas.remove_member(organization_id(current), user_id)
                    changed += 1
                except ValueError:
                    continue
        else:
            raise HTTPException(status_code=422, detail="Невідома масова дія")
        return {"changed": changed}

    @app.put("/api/users/{user_id}/password")
    def admin_set_password(
        user_id: int,
        payload: PasswordRequest,
        current: dict = Depends(require_permission("users.invite")),
    ) -> dict:
        ensure_organization_user(current, user_id)
        try:
            auth.get_user(user_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        auth.set_password(user_id, payload.password)
        return {"ok": True}

    @app.put("/api/account/password")
    def change_password(
        payload: PasswordRequest,
        response: Response,
        user: dict = Depends(authorize_write),
    ) -> dict:
        auth.set_password(user["id"], payload.password)
        response.delete_cookie("voicerhub_session")
        return {"ok": True}

    @app.get("/api/dashboard")
    def dashboard_data(_: dict = Depends(authorize)) -> dict:
        data = repository.dashboard()
        data["rubrics"] = repository.list_rubrics(include_inactive=True)
        data["social_publish_jobs"] = saas.list_social_publish_jobs(
            repository.organization_id,
            limit=100,
        )
        data["templates"] = [
            {**item, "custom": False, "has_preview": True}
            for item in VISUAL_TEMPLATES
        ] + [
            {**item, "custom": True, "has_preview": bool(item["preview_path"])}
            for item in repository.list_custom_templates()
        ]
        return data

    @app.get("/api/ideas")
    def list_ideas(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        rubric: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize),
    ) -> dict:
        result = repository.list_ideas_page(
            page=page,
            per_page=per_page,
            search=search,
            rubric=rubric,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            direction=direction,
        )
        result["items"] = [
            {
                **item,
                "title_plain": strip_formatting(item["title"]),
                "angle_preview": sanitize_preview_html(item.get("angle", "")),
            }
            for item in result["items"]
        ]
        return result

    @app.get("/api/content-plan/items")
    def content_plan_items(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        rubric: str = "",
        sort: str = "planned_for",
        direction: str = "asc",
        _: dict = Depends(authorize),
    ) -> dict:
        rows = [
            item
            for item in repository.dashboard()["ideas"]
            if item.get("plan_id")
        ]
        if search.strip():
            needle = search.strip().lower()
            rows = [
                item
                for item in rows
                if needle
                in f"{item.get('title', '')} {item.get('angle', '')}".lower()
            ]
        if rubric and rubric != "all":
            rows = [item for item in rows if item.get("product") == rubric]
        reverse = direction.lower() == "desc"
        sort_key = sort if sort in {"title", "status", "planned_for", "created_at"} else "planned_for"
        rows.sort(key=lambda item: str(item.get(sort_key) or ""), reverse=reverse)
        result = paginate_rows(rows, page=page, per_page=per_page)
        result["items"] = [
            {
                **item,
                "title_plain": strip_formatting(item.get("title", "")),
                "error_message": (
                    item.get("error")
                    or (
                        "Не вдалося створити чернетку через помилку генерації."
                        if item.get("status") == "failed"
                        else "Генерацію було скасовано."
                        if item.get("status") == "cancelled"
                        else ""
                    )
                ),
            }
            for item in result["items"]
        ]
        return result

    @app.get("/api/drafts")
    def list_drafts(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        status: str = "",
        rubric: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: str = "created_at",
        direction: str = "desc",
        _: dict = Depends(authorize),
    ) -> dict:
        result = repository.list_drafts_page(
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            rubric=rubric,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            direction=direction,
        )
        result["items"] = [
            {
                **item,
                "title_plain": strip_formatting(item["title"]),
                "caption_preview": sanitize_preview_html(item["caption_html"]),
                "caption_plain": strip_formatting(item["caption_html"]),
            }
            for item in result["items"]
        ]
        return result

    @app.get("/api/brand/visual-styles")
    def visual_styles(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        active: str = "",
        _: dict = Depends(authorize),
    ) -> dict:
        return repository.list_custom_templates_page(
            page=page,
            per_page=per_page,
            search=search,
            active=active,
        )

    @app.get("/api/brand/materials")
    def brand_materials(
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        material_type: str = "",
        active: str = "",
        _: dict = Depends(authorize),
    ) -> dict:
        return repository.list_references_page(
            page=page,
            per_page=per_page,
            search=search,
            material_type=material_type,
            active=active,
        )

    @app.get("/api/usage")
    def workspace_usage(
        period: str = "month",
        user: dict = Depends(authorize),
    ) -> dict:
        now = datetime.now(timezone.utc)
        if period == "7d":
            since = now - timedelta(days=7)
        elif period == "month":
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "all":
            since = None
        else:
            raise HTTPException(status_code=422, detail="Невідомий період")
        since_value = since.strftime("%Y-%m-%d %H:%M:%S") if since else None
        report = repository.usage_summary(since=since_value)
        names = {row["id"]: row for row in auth.list_users(organization_id(user))}
        return {
            **report,
            "users": [
                {
                    **row,
                    "username": names.get(row["user_id"], {}).get(
                        "username",
                        "system",
                    ),
                    "display_name": names.get(row["user_id"], {}).get(
                        "display_name",
                        "System",
                    ),
                }
                for row in report["users"]
            ],
            "rubrics": repository.usage_by_rubric(since=since_value),
        }

    def record_text_usage(
        model: str,
        input_tokens: int,
        output_tokens: int,
        user_id: int,
    ) -> None:
        cost = (
            input_tokens * settings.text_standard_input_price_per_1m
            + output_tokens * settings.text_standard_output_price_per_1m
        ) / 1_000_000
        repository.add_usage(
            job_id=0,
            kind="text",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            user_id=user_id,
        )

    def save_ideas(
        ideas,
        *,
        source_url: str = "",
        plan_id: str | None = None,
        series_id: str | None = None,
        forced_tone: str | None = None,
    ) -> list[dict]:
        existing = repository.all_idea_signatures()
        rows = []
        for idea in ideas:
            score, duplicate_of = closest_duplicate(idea.title, idea.angle, existing)
            row = {
                "product": idea.product,
                "title": idea.title,
                "angle": idea.angle,
                "planned_for": idea.planned_for,
                "tone": forced_tone or idea.tone.value,
                "series_id": series_id if idea.series_part else None,
                "series_title": idea.series_title,
                "series_part": idea.series_part,
                "source_url": source_url,
                "duplicate_score": score,
                "duplicate_of": duplicate_of if score >= 0.62 else None,
                "plan_id": plan_id,
            }
            rows.append(row)
            existing.append({"id": None, "title": idea.title, "angle": idea.angle})
        return repository.add_ideas(rows)

    @app.post("/api/ideas/generate")
    async def generate_ideas(
        payload: IdeaRequest,
        user: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        ensure_text_generation_quota()
        _validate_models(payload.text_model)
        _validate_tone(payload.tone)
        validate_rubric(payload.product, allow_all=True)
        ideas, input_tokens, output_tokens = await idea_generator.generate(
            payload.product,
            payload.count,
            payload.focus,
            repository.recent_titles(),
            payload.text_model,
            active_rubrics(),
        )
        record_text_usage(payload.text_model, input_tokens, output_tokens, user["id"])
        saved = save_ideas(ideas.ideas, forced_tone=payload.tone)
        saas.audit(
            organization_id(user),
            user["id"],
            "idea_created",
            f"generated:{len(saved)}",
        )
        return {"ideas": saved}

    @app.post("/api/ideas")
    def create_manual_idea(
        payload: ManualIdeaRequest,
        user: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        validate_rubric(payload.product)
        rows = repository.add_ideas(
            [
                {
                    "product": payload.product,
                    "title": payload.title.strip(),
                    "angle": payload.angle.strip(),
                    "planned_for": (
                        payload.planned_for.isoformat()
                        if payload.planned_for
                        else None
                    ),
                    "tone": "expert",
                    "created_by_user_id": user["id"],
                }
            ]
        )
        saas.audit(
            organization_id(user),
            user["id"],
            "idea_created",
            str(rows[0]["id"]),
        )
        return rows[0]

    @app.post("/api/content-plan/generate")
    async def generate_content_plan(
        payload: ContentPlanRequest,
        user: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        ensure_text_generation_quota()
        if payload.create_as == "drafts":
            ensure_text_generation_quota(payload.posts)
            ensure_image_generation_quota(payload.posts)
        _validate_models(payload.text_model)
        validate_rubric(payload.product, allow_all=True)
        days = 7 if payload.period == "week" else 30
        plan, input_tokens, output_tokens = await idea_generator.generate_plan(
            product=payload.product,
            days=days,
            posts=payload.posts,
            focus=payload.focus,
            start_date=payload.start_date.isoformat(),
            recent_titles=repository.recent_titles(100),
            model=payload.text_model,
            rubrics=active_rubrics(),
        )
        record_text_usage(payload.text_model, input_tokens, output_tokens, user["id"])
        plan_id = f"plan-{uuid4().hex[:10]}"
        saved = save_ideas(plan.ideas, plan_id=plan_id)
        repository.create_content_plan(
            plan_id=plan_id,
            period=payload.period,
            start_date=payload.start_date.isoformat(),
            posts=payload.posts,
            objective=payload.focus,
            create_as=payload.create_as,
            rubric_slugs=payload.rubric_slugs,
            channel_ids=payload.channel_ids,
            created_by_user_id=user["id"],
        )
        jobs = []
        if payload.create_as == "drafts":
            for idea in saved:
                jobs.append(
                    repository.select_idea(
                        idea["id"],
                        text_model=payload.text_model,
                        created_by_user_id=user["id"],
                        generation_mode="fast",
                    ).id
                )
        saas.update_organization_settings(
            organization_id(user),
            onboarding_status="in_progress",
            onboarding_step=5,
            first_content_plan_created=1,
        )
        return {"plan_id": plan_id, "ideas": saved, "job_ids": jobs}

    @app.post("/api/series/generate")
    async def generate_series(
        payload: SeriesRequest,
        user: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        ensure_text_generation_quota()
        _validate_models(payload.text_model)
        _validate_tone(payload.tone)
        validate_rubric(payload.product)
        ideas, input_tokens, output_tokens = await idea_generator.generate_series(
            product=payload.product,
            parts=payload.parts,
            topic=payload.topic,
            tone=payload.tone,
            recent_titles=repository.recent_titles(100),
            model=payload.text_model,
            rubrics=active_rubrics(),
        )
        record_text_usage(payload.text_model, input_tokens, output_tokens, user["id"])
        series_id = f"series-{uuid4().hex[:10]}"
        repository.create_content_series(
            series_id=series_id,
            title=payload.topic,
            parts=payload.parts,
            rubric_slug=payload.product,
            created_by_user_id=user["id"],
        )
        return {
            "series_id": series_id,
            "ideas": save_ideas(
                ideas.ideas,
                series_id=series_id,
                forced_tone=payload.tone,
            ),
        }

    @app.post("/api/materials/import")
    async def import_material(
        payload: MaterialRequest,
        user: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        ensure_text_generation_quota()
        _validate_models(payload.text_model)
        _validate_tone(payload.tone)
        validate_rubric(payload.product, allow_all=True)
        material = payload.text.strip()
        if not material:
            if not payload.url:
                raise HTTPException(
                    status_code=422,
                    detail="Додайте URL або вставте текст матеріалу",
                )
            try:
                material = await fetch_page_text(payload.url)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Не вдалося прочитати сторінку: {exc}. "
                        "Вставте текст матеріалу вручну."
                    ),
                ) from exc
        ideas, input_tokens, output_tokens = await idea_generator.from_material(
            material=material,
            source_url=payload.url,
            product=payload.product,
            count=payload.count,
            tone=payload.tone,
            model=payload.text_model,
            rubrics=active_rubrics(),
        )
        record_text_usage(payload.text_model, input_tokens, output_tokens, user["id"])
        return {
            "ideas": save_ideas(
                ideas.ideas,
                source_url=payload.url,
                forced_tone=payload.tone,
            )
        }

    @app.post("/api/ideas/{idea_id}/generate")
    def generate_from_idea(
        idea_id: int,
        payload: GenerationRequest,
        user: dict = Depends(require_permission("content.create")),
    ) -> dict:
        ensure_text_generation_quota()
        ensure_image_generation_quota()
        _validate_generation(payload, repository)
        try:
            job = repository.select_idea(
                idea_id,
                text_model=payload.text_model,
                image_model=payload.image_model,
                reference_ids=payload.reference_ids,
                template_id=payload.template_id,
                logo_reference_id=payload.logo_reference_id,
                company_logo_reference_id=payload.company_logo_reference_id,
                link_url=payload.link_url.strip(),
                tone=payload.tone,
                created_by_user_id=user["id"],
                generation_mode=payload.generation_mode,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail="Створіть хоча б одну активну рубрику перед генерацією.",
            ) from exc
        return {"job_id": job.id}

    @app.post("/api/ideas/{idea_id}/plan")
    def add_idea_to_plan(
        idea_id: int,
        payload: IdeaPlanRequest,
        _: dict = Depends(require_permission("ideas.create")),
    ) -> dict:
        try:
            item = repository.add_idea_to_plan(
                idea_id,
                payload.planned_for.isoformat(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Тему не знайдено") from exc
        return {
            **item,
            "title_plain": strip_formatting(item.get("title", "")),
            "angle_preview": sanitize_preview_html(item.get("angle", "")),
        }

    @app.post("/api/jobs/{job_id}/retry-fast")
    async def retry_job_fast(
        job_id: int,
        user: dict = Depends(require_permission("content.create")),
    ) -> dict:
        ensure_text_generation_quota()
        ensure_image_generation_quota()
        try:
            job = repository.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Завдання не знайдено") from exc
        if job.status not in {
            "failed",
            "queued_text",
            "text_batch",
            "queued_image",
            "image_batch",
        }:
            raise HTTPException(
                status_code=409,
                detail="Це завдання вже завершено або не може бути перезапущене",
            )
        batch_id = (
            job.text_batch_id if job.status == "text_batch" else job.image_batch_id
        )
        if batch_id:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            try:
                batch = await client.batches.retrieve(batch_id)
                if batch.status in {
                    "completed",
                    "failed",
                    "expired",
                    "cancelled",
                    "cancelling",
                }:
                    return {
                        "job_id": None,
                        "cancelled_job_id": None,
                        "batch_status": batch.status,
                        "message": (
                            "OpenAI Batch уже завершився. Результат буде "
                            "оброблено автоматично, швидкий дубль не створено."
                        ),
                    }
                await client.batches.cancel(batch_id)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 409:
                    batch = await client.batches.retrieve(batch_id)
                    if batch.status in {
                        "completed",
                        "failed",
                        "expired",
                        "cancelled",
                        "cancelling",
                    }:
                        return {
                            "job_id": None,
                            "cancelled_job_id": None,
                            "batch_status": batch.status,
                            "message": (
                                "OpenAI Batch завершився під час скасування. "
                                "Результат буде оброблено автоматично, "
                                "швидкий дубль не створено."
                            ),
                        }
                raise HTTPException(
                    status_code=502,
                    detail=f"Не вдалося скасувати OpenAI Batch: {exc}",
                ) from exc
        repository.update_job(
            job.id,
            status="cancelled",
            error="Скасовано користувачем. Створено швидке завдання.",
        )
        reference_ids = json.loads(job.reference_ids or "[]")
        if job.draft_id:
            replacement = repository.create_image_job(
                job.draft_id,
                image_model=job.image_model,
                reference_ids=reference_ids,
                template_id=job.template_id,
                logo_reference_id=job.logo_reference_id,
                company_logo_reference_id=job.company_logo_reference_id,
                created_by_user_id=user["id"],
                generation_mode="fast",
            )
        else:
            replacement = repository.create_job(
                job.topic,
                job.product,
                job.chat_id,
                text_model=job.text_model,
                image_model=job.image_model,
                reference_ids=reference_ids,
                template_id=job.template_id,
                logo_reference_id=job.logo_reference_id,
                company_logo_reference_id=job.company_logo_reference_id,
                link_url=job.link_url,
                idea_id=None,
                tone=job.tone,
                created_by_user_id=user["id"],
                generation_mode="fast",
            )
        return {"job_id": replacement.id, "cancelled_job_id": job.id}

    @app.delete("/api/jobs/{job_id}")
    def delete_failed_job(
        job_id: int,
        _: dict = Depends(require_permission("content.delete")),
    ) -> dict:
        try:
            return repository.delete_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Завдання не знайдено") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/ideas/{idea_id}")
    def delete_idea(
        idea_id: int,
        _: dict = Depends(require_permission("ideas.delete")),
    ) -> dict:
        try:
            repository.delete_idea(idea_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Тему не знайдено") from exc
        return {"deleted": idea_id}

    @app.post("/api/ideas/bulk")
    def bulk_ideas(
        payload: BulkActionRequest,
        user: dict = Depends(require_permission("ideas.delete")),
    ) -> dict:
        ids = [int(item) for item in payload.ids]
        if payload.action == "delete":
            return {"changed": repository.delete_ideas(ids)}
        if payload.action == "assign_rubric":
            return {"changed": repository.assign_ideas_rubric(ids, payload.value)}
        if payload.action == "create_drafts":
            if not has_permission(
                user.get("role") or "viewer",
                "content.create",
                platform_admin=bool(user.get("is_super_admin")),
            ):
                raise HTTPException(status_code=403, detail="Недостатньо прав")
            try:
                jobs = [
                    repository.select_idea(
                        idea_id,
                        created_by_user_id=user["id"],
                        generation_mode="fast",
                    ).id
                    for idea_id in ids
                ]
            except KeyError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="Створіть хоча б одну активну рубрику перед генерацією.",
                ) from exc
            return {"changed": len(jobs), "job_ids": jobs}
        raise HTTPException(status_code=422, detail="Невідома масова дія")

    @app.post("/api/templates")
    def create_template(
        payload: CustomTemplateRequest,
        _: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        slug = re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")[:45]
        template_id = f"custom-{slug or 'style'}-{uuid4().hex[:6]}"
        return repository.add_custom_template(
            template_id=template_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
            prompt=payload.prompt.strip(),
            layout=payload.layout,
            accent=payload.accent.lower(),
            mood=payload.mood.strip(),
            use_rules=payload.use_rules.strip(),
            avoid_rules=payload.avoid_rules.strip(),
            prompt_examples=payload.prompt_examples.strip(),
            active=payload.active,
        )

    @app.post("/api/templates/bulk")
    def bulk_templates(
        payload: BulkActionRequest,
        _: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        changed = 0
        for template_id in [str(item) for item in payload.ids]:
            try:
                if payload.action in {"activate", "deactivate"}:
                    repository.update_custom_template(
                        template_id,
                        active=payload.action == "activate",
                    )
                elif payload.action == "delete":
                    template = repository.delete_custom_template(template_id)
                    if template.get("preview_path"):
                        Path(template["preview_path"]).unlink(missing_ok=True)
                else:
                    raise HTTPException(status_code=422, detail="Невідома масова дія")
                changed += 1
            except KeyError:
                continue
        return {"changed": changed}

    @app.put("/api/templates/{template_id}")
    def update_template(
        template_id: str,
        payload: CustomTemplateUpdateRequest,
        _: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        try:
            return repository.update_custom_template(
                template_id,
                **payload.model_dump(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Стиль не знайдено") from exc

    @app.post("/api/templates/{template_id}/duplicate")
    def duplicate_template(
        template_id: str,
        _: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        try:
            source = repository.get_custom_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Стиль не знайдено") from exc
        return repository.add_custom_template(
            template_id=f"custom-copy-{uuid4().hex[:10]}",
            name=f"{source['name']} — копія",
            description=source["description"],
            prompt=source["prompt"],
            layout=source["layout"],
            accent=source["accent"],
            mood=source.get("mood", ""),
            use_rules=source.get("use_rules", ""),
            avoid_rules=source.get("avoid_rules", ""),
            prompt_examples=source.get("prompt_examples", ""),
            active=bool(source.get("active", 1)),
        )

    @app.delete("/api/templates/{template_id}")
    def delete_template(
        template_id: str,
        _: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        try:
            template = repository.delete_custom_template(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Шаблон не знайдено") from exc
        if template.get("preview_path"):
            Path(template["preview_path"]).unlink(missing_ok=True)
        return {"deleted": template_id}

    @app.get("/api/templates/{template_id}/preview")
    def template_preview(
        template_id: str,
        _: str = Depends(authorize),
    ) -> FileResponse:
        built_in = next(
            (item for item in VISUAL_TEMPLATES if item["id"] == template_id),
            None,
        )
        if built_in:
            path = (
                Path(__file__).parent
                / "assets"
                / "template_previews"
                / f"{template_id}.png"
            )
        else:
            try:
                template = repository.get_custom_template(template_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Шаблон не знайдено") from exc
            path = Path(template["preview_path"] or "")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Прев’ю ще не згенеровано")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/templates/{template_id}/generate-preview")
    async def generate_template_preview(
        template_id: str,
        user: dict = Depends(require_permission("visual_styles.manage")),
    ) -> dict:
        ensure_image_generation_quota()
        try:
            template = repository.get_custom_template(template_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Кастомний шаблон не знайдено",
            ) from exc
        image_generator = image_generator_for(repository.organization_id)
        path, response = await image_generator.generate(
            "AI-аналітика клієнтського досвіду",
            "A credible customer experience team using AI analytics, voice signals and structured business insights.",
            model=settings.openai_image_model,
            template_id=template_id,
            template=template,
        )
        repository.set_template_preview(template_id, str(path))
        usage = getattr(response, "usage", None)
        repository.add_usage(
            job_id=0,
            kind="image",
            model=settings.openai_image_model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            units=1,
            cost=0.041,
            user_id=user["id"],
        )
        return {"preview": f"api/templates/{template_id}/preview"}

    @app.post("/api/references")
    async def upload_reference(
        file: UploadFile = File(...),
        name: str = Form(default=""),
        material_type: str = Form(default="reference_image"),
        description: str = Form(default=""),
        user: dict = Depends(require_permission("brand_materials.manage")),
    ) -> dict:
        media_type = file.content_type or ""
        allowed_types = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        }
        if media_type not in allowed_types:
            raise HTTPException(
                status_code=422,
                detail="Підтримуються PNG, JPG, WebP, PDF, DOCX або PPTX",
            )
        content = await file.read()
        if not content or len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Файл має бути меншим за 20 MB")
        if media_type.startswith("image/"):
            try:
                image = Image.open(BytesIO(content))
                image.verify()
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Пошкоджений файл зображення") from exc
        suffix = allowed_types[media_type]
        _, reference_dir = organization_dirs(repository.organization_id)
        path = reference_dir / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        return repository.add_reference(
            name=(name.strip() or Path(file.filename or "reference").stem)[:100],
            filename=(file.filename or path.name)[:200],
            path=str(path),
            media_type=media_type,
            material_type=material_type,
            description=description.strip(),
            created_by_user_id=user["id"],
        )

    @app.post("/api/brand/materials/link")
    def add_brand_material_link(
        payload: BrandMaterialLinkRequest,
        user: dict = Depends(require_permission("brand_materials.manage")),
    ) -> dict:
        if not payload.source_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="Посилання має починатися з http:// або https://",
            )
        return repository.add_reference(
            name=payload.name.strip(),
            filename="",
            path="",
            media_type="text/uri-list",
            material_type=payload.material_type,
            description=payload.description.strip(),
            source_url=payload.source_url.strip(),
            active=payload.active,
            created_by_user_id=user["id"],
        )

    @app.post("/api/brand/materials/bulk")
    def bulk_brand_materials(
        payload: BulkActionRequest,
        _: dict = Depends(require_permission("brand_materials.manage")),
    ) -> dict:
        changed = 0
        for reference_id in [int(item) for item in payload.ids]:
            try:
                if payload.action in {"activate", "deactivate"}:
                    repository.update_reference(
                        reference_id,
                        active=payload.action == "activate",
                    )
                elif payload.action == "delete":
                    reference = repository.delete_reference(reference_id)
                    if reference.get("path"):
                        Path(reference["path"]).unlink(missing_ok=True)
                else:
                    raise HTTPException(status_code=422, detail="Невідома масова дія")
                changed += 1
            except KeyError:
                continue
        return {"changed": changed}

    @app.put("/api/brand/materials/{reference_id}")
    def update_brand_material(
        reference_id: int,
        payload: BrandMaterialUpdateRequest,
        _: dict = Depends(require_permission("brand_materials.manage")),
    ) -> dict:
        if payload.source_url and not payload.source_url.startswith(
            ("http://", "https://")
        ):
            raise HTTPException(
                status_code=422,
                detail="Посилання має починатися з http:// або https://",
            )
        try:
            return repository.update_reference(
                reference_id,
                **payload.model_dump(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Матеріал не знайдено") from exc

    @app.get("/api/references/{reference_id}/image")
    def reference_image(
        reference_id: int, _: str = Depends(authorize)
    ) -> FileResponse:
        try:
            reference = repository.get_reference(reference_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        path = Path(reference["path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Reference file is missing")
        return FileResponse(path, media_type=reference["media_type"])

    @app.delete("/api/references/{reference_id}")
    def delete_reference(
        reference_id: int,
        _: dict = Depends(require_permission("brand_materials.manage")),
    ) -> dict:
        try:
            reference = repository.delete_reference(reference_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if reference.get("path"):
            Path(reference["path"]).unlink(missing_ok=True)
        return {"deleted": reference_id}

    @app.get("/api/drafts/{draft_id}")
    def draft_detail(draft_id: int, _: str = Depends(authorize)) -> dict:
        try:
            return repository.draft_record(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/drafts/{draft_id}/favorite")
    def favorite_draft(
        draft_id: int,
        payload: FavoriteRequest,
        _: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        try:
            return repository.set_draft_favorite(draft_id, payload.favorite)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc

    @app.post("/api/drafts")
    def create_manual_draft(
        payload: ManualDraftRequest,
        user: dict = Depends(require_permission("content.create")),
    ) -> dict:
        validate_rubric(payload.product)
        caption_html = canonicalize_draft_caption(
            payload.caption_html,
            payload.title,
            payload.link_url,
        )
        draft = repository.create(
            topic=payload.title,
            product=payload.product,
            title=payload.title,
            visual_title=payload.visual_title,
            caption_html=caption_html,
            image_prompt=(
                "A polished editorial visual for a professional social media post."
            ),
            image_path="",
            link_url=payload.link_url,
            tone="expert",
        )
        saas.audit(
            organization_id(user),
            user["id"],
            "draft_created",
            str(draft.id),
        )
        return repository.draft_record(draft.id)

    @app.delete("/api/drafts/{draft_id}")
    def delete_draft(
        draft_id: int,
        _: dict = Depends(require_permission("content.delete")),
    ) -> dict:
        try:
            draft = repository.delete_draft(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc
        for field in ("image_path",):
            if draft.get(field):
                Path(draft[field]).unlink(missing_ok=True)
        return {"deleted": draft_id}

    @app.post("/api/drafts/bulk")
    def bulk_drafts(
        payload: BulkActionRequest,
        user: dict = Depends(authorize),
        x_requested_with: str | None = Header(default=None),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        ids = [int(item) for item in payload.ids]
        required = "content.delete" if payload.action == "delete" else "content.edit"
        if not has_permission(
            user.get("role") or "viewer",
            required,
            platform_admin=bool(user.get("is_super_admin")),
        ):
            raise HTTPException(status_code=403, detail="Недостатньо прав")
        if payload.action == "delete":
            changed = 0
            for draft_id in ids:
                try:
                    repository.delete_draft(draft_id)
                    changed += 1
                except KeyError:
                    continue
            return {"changed": changed}
        if payload.action == "assign_rubric":
            return {"changed": repository.assign_drafts_rubric(ids, payload.value)}
        if payload.action == "status":
            changed = 0
            for draft_id in ids:
                try:
                    repository.transition_draft(draft_id, payload.value)
                    changed += 1
                except (KeyError, ValueError):
                    continue
            return {"changed": changed}
        raise HTTPException(status_code=422, detail="Невідома масова дія")

    @app.get("/api/drafts/{draft_id}/image")
    def draft_image(draft_id: int, _: str = Depends(authorize)) -> FileResponse:
        try:
            draft = repository.draft_record(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        image_path = Path(draft["image_path"])
        if not draft["image_path"] or not image_path.is_file():
            raise HTTPException(status_code=404, detail="Image is not ready")
        media_type = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        return FileResponse(image_path, media_type=media_type)

    @app.get("/api/drafts/{draft_id}/social-variants")
    def social_variants(
        draft_id: int,
        _: dict = Depends(authorize),
    ) -> list[dict]:
        try:
            repository.draft_record(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc
        return repository.list_social_variants(draft_id)

    @app.post("/api/drafts/{draft_id}/social-variants")
    async def generate_social_variant(
        draft_id: int,
        payload: SocialVariantRequest,
        user: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        ensure_text_generation_quota()
        ensure_image_generation_quota()
        _validate_models(payload.text_model, payload.image_model)
        if payload.platform not in SOCIAL_PLATFORM_RULES:
            raise HTTPException(status_code=422, detail="Ця соцмережа не підтримується")
        try:
            draft = repository.draft_record(draft_id)
            rubric = repository.get_rubric(draft["product"])
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку або рубрику не знайдено") from exc
        template_ids = {item["id"] for item in VISUAL_TEMPLATES}
        template_ids.update(item["id"] for item in repository.list_custom_templates())
        if payload.template_id not in template_ids:
            raise HTTPException(status_code=422, detail="Невідомий візуальний шаблон")
        logo = (
            repository.get_reference(payload.logo_reference_id)
            if payload.logo_reference_id
            else None
        )
        company_logo = (
            repository.get_reference(payload.company_logo_reference_id)
            if payload.company_logo_reference_id
            else None
        )
        references = repository.references_by_ids(payload.reference_ids)
        social, input_tokens, output_tokens = await editorial_tools.adapt_for_social(
            title=draft["title"],
            telegram_text=re.sub(r"<[^>]+>", "", draft["caption_html"]),
            platform=payload.platform,
            rubric=rubric,
            link_url=draft["link_url"],
            model=payload.text_model,
        )
        record_text_usage(
            payload.text_model,
            input_tokens,
            output_tokens,
            user["id"],
        )
        platform_rules = SOCIAL_PLATFORM_RULES[payload.platform]
        try:
            template = repository.get_custom_template(payload.template_id)
        except KeyError:
            template = None
        image_path, response = await image_generator_for(
            organization_id(user)
        ).generate(
            social.visual_title,
            social.image_prompt,
            model=payload.image_model,
            reference_paths=[Path(item["path"]) for item in references],
            template_id=payload.template_id,
            logo_path=Path(logo["path"]) if logo else None,
            company_logo_path=Path(company_logo["path"]) if company_logo else None,
            template=template,
            size=platform_rules["api_size"],
            output_size=platform_rules["output_size"],
            platform=platform_rules["label"],
        )
        usage = getattr(response, "usage", None)
        repository.add_usage(
            job_id=0,
            kind="image",
            model=payload.image_model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            units=1,
            cost=settings.image_standard_price_per_generation,
            user_id=user["id"],
        )
        return repository.save_social_variant(
            draft_id=draft_id,
            platform=payload.platform,
            title=social.title,
            visual_title=social.visual_title,
            text_content=social.text,
            hashtags=social.hashtags,
            image_prompt=social.image_prompt,
            image_path=str(image_path),
            text_model=payload.text_model,
            image_model=payload.image_model,
            created_by_user_id=user["id"],
        )

    @app.put("/api/drafts/{draft_id}/social-variants/{platform}")
    def update_social_variant(
        draft_id: int,
        platform: str,
        payload: SocialVariantUpdateRequest,
        _: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        try:
            current = repository.get_social_variant(draft_id, platform)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Версію не знайдено") from exc
        return repository.save_social_variant(
            draft_id=draft_id,
            platform=platform,
            title=payload.title.strip(),
            visual_title=payload.visual_title.strip(),
            text_content=payload.text_content.strip(),
            hashtags=current["hashtags"],
            image_prompt=current["image_prompt"],
            image_path=current["image_path"],
            text_model=current["text_model"],
            image_model=current["image_model"],
            created_by_user_id=current["created_by_user_id"],
        )

    @app.get("/api/drafts/{draft_id}/social-variants/{platform}/image")
    def social_variant_image(
        draft_id: int,
        platform: str,
        download: bool = False,
        _: dict = Depends(authorize),
    ) -> FileResponse:
        try:
            variant = repository.get_social_variant(draft_id, platform)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Версію не знайдено") from exc
        path = Path(variant["image_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Зображення не знайдено")
        filename = f"{platform}-post-{draft_id}.png" if download else None
        return FileResponse(path, media_type="image/png", filename=filename)

    @app.get("/wave-cover")
    def wave_cover(_: str = Depends(authorize)) -> FileResponse:
        path = Path(__file__).parent / "assets" / "VoicerWave.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Voicer Wave cover is missing")
        return FileResponse(path, media_type="image/jpeg")

    @app.put("/api/drafts/{draft_id}")
    def edit_draft(
        draft_id: int,
        payload: DraftEditRequest,
        _: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        link_url = payload.link_url.strip()
        if link_url and not link_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="Посилання має починатися з http:// або https://",
            )
        title = plain_text(payload.title)
        caption_html = canonicalize_draft_caption(
            payload.caption_html,
            title,
            link_url,
        )
        repository.update_draft(
            draft_id,
            title=title,
            visual_title=payload.visual_title,
            caption_html=caption_html,
            link_url=link_url,
        )
        return repository.draft_record(draft_id)

    @app.post("/api/drafts/{draft_id}/status")
    def change_draft_status(
        draft_id: int,
        payload: ContentStatusRequest,
        _: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        if payload.status in {"scheduled", "published"}:
            raise HTTPException(
                status_code=409,
                detail="Для цього статусу використайте планування або публікацію",
            )
        try:
            return repository.transition_draft(draft_id, payload.status)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Чернетку не знайдено",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/drafts/{draft_id}/regenerate-image")
    def regenerate_image(
        draft_id: int,
        payload: GenerationRequest,
        user: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        ensure_image_generation_quota()
        _validate_generation(payload, repository)
        draft_record = repository.draft_record(draft_id)
        rubric = repository.get_rubric(draft_record["product"])
        if rubric.get("fixed_cover_path"):
            raise HTTPException(
                status_code=409,
                detail="Ця рубрика використовує фіксовану обкладинку",
            )
        job = repository.create_image_job(
            draft_id,
            image_model=payload.image_model,
            reference_ids=payload.reference_ids,
            template_id=payload.template_id,
            logo_reference_id=payload.logo_reference_id,
            company_logo_reference_id=payload.company_logo_reference_id,
            created_by_user_id=user["id"],
            generation_mode=payload.generation_mode,
        )
        return {"job_id": job.id}

    @app.post("/api/drafts/{draft_id}/regenerate-text")
    def regenerate_text(
        draft_id: int,
        payload: GenerationRequest,
        user: dict = Depends(require_permission("content.edit")),
    ) -> dict:
        ensure_text_generation_quota()
        ensure_image_generation_quota()
        _validate_generation(payload, repository)
        draft = repository.draft_record(draft_id)
        job = repository.create_job(
            f"{draft['topic']}. Створи нову редакційну версію з іншим вступом і структурою.",
            draft["product"],
            0,
            text_model=payload.text_model,
            image_model=payload.image_model,
            reference_ids=payload.reference_ids,
            template_id=payload.template_id,
            logo_reference_id=payload.logo_reference_id,
            company_logo_reference_id=payload.company_logo_reference_id,
            link_url=payload.link_url.strip() or draft["link_url"],
            tone=payload.tone or draft.get("tone") or "expert",
            created_by_user_id=user["id"],
            generation_mode=payload.generation_mode,
        )
        return {"job_id": job.id}

    @app.post("/api/drafts/{draft_id}/publish")
    async def publish_draft(
        draft_id: int,
        user: dict = Depends(require_permission("content.publish")),
    ) -> dict:
        ensure_publication_quota()
        draft = repository.draft_record(draft_id)
        if draft["status"] not in {"ready", "scheduled"}:
            raise HTTPException(
                status_code=409,
                detail="Спочатку позначте пост як готовий",
            )
        image_path = Path(draft["image_path"])
        if not draft["image_path"] or not image_path.is_file():
            raise HTTPException(status_code=409, detail="Image is not ready")
        token, channel = telegram_credentials(int(user.get("organization_id") or 1))
        telegram = Bot(token)
        with image_path.open("rb") as image:
            message = await telegram.send_photo(
                chat_id=channel,
                photo=image,
                caption=draft["caption_html"],
                parse_mode=ParseMode.HTML,
            )
        repository.mark_published(draft_id)
        repository.set_telegram_message_id(draft_id, message.message_id)
        saas.audit(
            organization_id(user),
            user["id"],
            "draft_published",
            str(draft_id),
        )
        return {"message_id": message.message_id}

    @app.get("/api/drafts/{draft_id}/publish-jobs")
    def draft_publish_jobs(
        draft_id: int,
        user: dict = Depends(authorize),
    ) -> list[dict]:
        try:
            repository.draft_record(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc
        return saas.list_social_publish_jobs(
            organization_id(user),
            draft_id=draft_id,
            limit=50,
        )

    @app.post("/api/drafts/{draft_id}/instagram/publish")
    async def publish_instagram_draft(
        draft_id: int,
        user: dict = Depends(require_permission("content.publish")),
    ) -> dict:
        ensure_publication_quota()
        setup = instagram_setup_status()
        if setup["setup_required"]:
            raise HTTPException(
                status_code=409,
                detail="Instagram ще не налаштовано. Telegram працює без змін.",
            )
        try:
            job = instagram_publisher.create_job_for_draft(
                organization_id=organization_id(user),
                draft_id=draft_id,
                scheduled_at=None,
                status="queued",
                created_by_user_id=user["id"],
            )
            result = await instagram_publisher.publish_job(int(job["id"]))
            saas.audit(
                organization_id(user),
                user["id"],
                "instagram_published",
                str(draft_id),
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Instagram не підключено") from exc
        except InstagramApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/drafts/{draft_id}/instagram/schedule")
    def schedule_instagram_draft(
        draft_id: int,
        payload: InstagramScheduleRequest,
        user: dict = Depends(require_permission("content.schedule")),
    ) -> dict:
        ensure_active_subscription(saas.get_organization(repository.organization_id))
        setup = instagram_setup_status()
        if setup["setup_required"]:
            raise HTTPException(
                status_code=409,
                detail="Instagram ще не налаштовано. Telegram працює без змін.",
            )
        scheduled_at = payload.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        scheduled_at = scheduled_at.astimezone(timezone.utc)
        if scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Час публікації має бути в майбутньому")
        try:
            job = instagram_publisher.create_job_for_draft(
                organization_id=organization_id(user),
                draft_id=draft_id,
                scheduled_at=scheduled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                status="scheduled",
                created_by_user_id=user["id"],
            )
            saas.audit(
                organization_id(user),
                user["id"],
                "instagram_scheduled",
                f"{draft_id}:{job['scheduled_at']}",
            )
            return job
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Instagram не підключено") from exc
        except InstagramApiError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/drafts/{draft_id}/schedule")
    def schedule_draft(
        draft_id: int,
        payload: ScheduleRequest,
        user: dict = Depends(require_permission("content.schedule")),
    ) -> dict:
        ensure_active_subscription(saas.get_organization(repository.organization_id))
        scheduled_at = payload.scheduled_at
        draft = repository.draft_record(draft_id)
        if draft["status"] == "published":
            raise HTTPException(
                status_code=409,
                detail="Опублікований пост не можна повторно планувати",
            )
        image_path = Path(draft["image_path"])
        if not draft["image_path"] or not image_path.is_file():
            raise HTTPException(
                status_code=409,
                detail="Спочатку додайте або згенеруйте візуал для публікації",
            )
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        scheduled_at = scheduled_at.astimezone(timezone.utc)
        if scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Schedule time must be in the future")
        value = scheduled_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        repository.schedule_draft(draft_id, value)
        saas.audit(
            organization_id(user),
            user["id"],
            "draft_scheduled",
            f"{draft_id}:{value}",
        )
        return {"scheduled_at": value}

    @app.post("/api/drafts/{draft_id}/cancel-schedule")
    def cancel_schedule(
        draft_id: int,
        _: dict = Depends(require_permission("content.schedule")),
    ) -> dict:
        repository.cancel_schedule(draft_id)
        return {"status": "ready"}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


LOGIN_HTML = r"""
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вхід · Content Studio</title>
  <style>
    *{box-sizing:border-box}body{margin:0;background:#0d1324;color:#111827;font:15px/1.45 Inter,system-ui,sans-serif;letter-spacing:0}
    body::before,body::after{content:"";position:fixed;border-radius:50%;filter:blur(2px);pointer-events:none}body::before{width:440px;height:440px;left:-150px;top:-180px;background:radial-gradient(circle,rgba(16,191,174,.34),transparent 68%)}body::after{width:520px;height:520px;right:-190px;bottom:-220px;background:radial-gradient(circle,rgba(37,99,235,.32),transparent 68%)}
    main{min-height:100vh;display:grid;place-items:center;padding:20px;position:relative}.login{width:min(420px,100%);background:rgba(255,255,255,.96);border:1px solid rgba(255,255,255,.7);padding:32px;border-radius:8px;box-shadow:0 35px 100px rgba(0,0,0,.38);animation:enter .45s ease both;backdrop-filter:blur(18px)}
    .login::before{content:"";display:block;width:42px;height:42px;margin-bottom:22px;border-radius:8px;background:linear-gradient(135deg,#10bfae,#2563eb);box-shadow:0 14px 32px rgba(16,191,174,.28)}
    h1{font-size:22px;margin:0 0 5px;letter-spacing:.06em}.sub{color:#64748b;margin:0 0 24px}label{display:block;color:#64748b;font-size:12px;font-weight:700;margin-top:14px}
    input{width:100%;margin-top:6px;border:1px solid #d5dee9;border-radius:8px;padding:12px;font:inherit;transition:border-color .15s ease,box-shadow .15s ease}input:focus{outline:0;border-color:#2563eb;box-shadow:0 0 0 4px rgba(37,99,235,.10)}button{width:100%;margin-top:22px;border:0;border-radius:8px;padding:12px;background:linear-gradient(135deg,#2563eb,#1d4ed8);box-shadow:0 14px 30px rgba(37,99,235,.24);color:#fff;font:inherit;font-weight:800;cursor:pointer;transition:transform .16s ease,box-shadow .16s ease}button:hover{transform:translateY(-1px);box-shadow:0 18px 38px rgba(37,99,235,.30)}
    .error{min-height:22px;margin-top:12px;color:#bd2c2c;font-size:13px}@keyframes enter{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:none}}@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
  </style>
</head>
<body><main><form class="login" id="loginForm">
  <h1>CONTENT STUDIO</h1>
  <p class="sub">Увійдіть до редакційної панелі</p>
  <label>Логін<input id="username" autocomplete="username" required autofocus></label>
  <label>Пароль<input id="password" type="password" autocomplete="current-password" required></label>
  <button type="submit">Увійти</button><div class="error" id="error"></div>
</form></main>
<script>
document.querySelector("#loginForm").onsubmit=async e=>{e.preventDefault();const error=document.querySelector("#error");error.textContent="";try{const r=await fetch("api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:document.querySelector("#username").value,password:document.querySelector("#password").value})});const d=await r.json();if(!r.ok)throw new Error(d.detail||"Помилка входу");location.reload()}catch(err){error.textContent=err.message}};
</script></body></html>
"""


ADMIN_HTML = r"""
<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Content Studio</title>
  <style>
    :root { --ink:#101827;--muted:#647084;--line:#dce3ea;--paper:#f6f8fa;--white:#fff;--cyan:#00a994;--blue:#1765d8;--amber:#a96200;--red:#bd2c2c; }
    *{box-sizing:border-box} [hidden]{display:none!important} body{margin:0;color:var(--ink);background:var(--paper);font:14px/1.45 Inter,system-ui,sans-serif;letter-spacing:0}
    header{min-height:64px;padding:0 28px;color:#fff;background:#111a2d;border-bottom:3px solid #18ecd6;display:flex;align-items:center;justify-content:space-between}.account{display:flex;align-items:center;gap:10px}.account button{padding:6px 9px;background:transparent;color:#fff;border-color:#43506a}
    h1{margin:0;font-size:18px} h2{font-size:17px;margin:24px 0 10px} main{max-width:1500px;margin:auto;padding:22px 28px 50px}.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:22px}
    button,.button{border:1px solid var(--line);background:#fff;color:var(--ink);padding:9px 13px;border-radius:5px;font:inherit;font-weight:700;cursor:pointer}
    button:hover{border-color:var(--blue)} button.primary{background:var(--blue);border-color:var(--blue);color:#fff} button.success{background:var(--cyan);border-color:var(--cyan);color:#fff}
    .spinner{display:inline-block;width:14px;height:14px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:6px}@keyframes spin{to{transform:rotate(360deg)}}.status.busy::before{content:"";display:inline-block;width:10px;height:10px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .7s linear infinite;margin-right:6px}
    button.danger{color:var(--red)} button:disabled{opacity:.45;cursor:not-allowed}.tab{border:0;border-radius:0;background:transparent;color:var(--muted);padding:12px 16px}
    .tab.active{color:var(--ink);border-bottom:3px solid var(--cyan)}.view{display:none}.view.active{display:block}.toolbar{display:grid;grid-template-columns:150px 85px 150px minmax(220px,1fr) auto;gap:10px;align-items:end;background:#fff;border:1px solid var(--line);padding:16px;border-radius:6px}
    .modelbar{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px;padding:14px 16px;background:#fff;border:1px solid var(--line);border-radius:6px}.modelbar small{display:block;color:var(--muted);margin-top:4px}
    label{display:block;color:var(--muted);font-size:12px;font-weight:700}input,select,textarea{width:100%;margin-top:5px;border:1px solid #c8d2dc;border-radius:5px;padding:10px;background:#fff;color:var(--ink);font:inherit}
    textarea{min-height:170px;resize:vertical}.ideas{margin-top:18px;border:1px solid var(--line);background:#fff}.idea{display:grid;grid-template-columns:26px 90px minmax(240px,1fr) auto;gap:12px;align-items:center;padding:14px;border-bottom:1px solid var(--line)}
    .idea:last-child{border-bottom:0}.idea strong{display:block;margin-bottom:3px}.idea p{margin:0;color:var(--muted)}.badge{display:inline-block;padding:3px 7px;border-radius:4px;background:#edf3fa;color:var(--blue);font-size:11px;font-weight:800;text-transform:uppercase}
    .drafts{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:16px}.draft{background:#fff;border:1px solid var(--line);border-radius:6px;overflow:hidden}.draft img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;background:#e8edf2}
    .draft-body{padding:14px}.draft h3{font-size:16px;margin:0 0 7px}.draft p{color:var(--muted);margin:0 0 12px;max-height:84px;overflow:hidden}.draft-meta{display:flex;gap:8px;align-items:center;justify-content:space-between}
    .status{font-weight:800;color:var(--blue)}.status.ready,.status.draft,.status.completed{color:var(--cyan)}.status.failed{color:var(--red)}.status.scheduled,.status.in_progress,.status.text_batch,.status.image_batch{color:var(--amber)}.wait-warning{color:#a25a00;font-weight:800}.wait-danger{color:var(--red);font-weight:800}
    .metrics{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--line);gap:1px;margin-bottom:22px}.metric{background:#fff;padding:17px}.metric span{color:var(--muted);font-size:12px}.metric strong{display:block;font-size:24px;margin-top:5px}
    table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line)}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#edf1f5;color:var(--muted);font-size:12px}
    dialog{width:min(1050px,calc(100% - 24px));border:0;border-radius:7px;padding:0;box-shadow:0 24px 80px #10182755}dialog::backdrop{background:#0b1220aa}.editor-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--line)}
    .editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:18px}.editor-grid img{width:100%;aspect-ratio:3/2;object-fit:cover;background:#e8edf2;border:1px solid var(--line)}.editor-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.schedule{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:12px}
    #socialVariant{margin-top:12px;padding:12px;border:1px solid var(--line);background:#f7f9fb}#socialVariant #socialImage{width:100%;max-height:420px;aspect-ratio:auto;object-fit:contain;background:#eef2f5}.button{display:inline-flex;align-items:center;padding:9px 13px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:var(--ink);font-weight:800;text-decoration:none}
    .notice{position:fixed;right:18px;bottom:18px;max-width:380px;padding:12px 16px;border-radius:5px;background:#111a2d;color:#fff;display:none;z-index:10}.empty{padding:28px;text-align:center;color:var(--muted)}
    .asset-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.asset-upload input{display:none}.assets{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:10px}.asset{position:relative;background:#fff;border:1px solid var(--line);border-radius:6px;overflow:hidden}.asset.selected{border:2px solid var(--cyan)}.asset img{display:block;width:100%;aspect-ratio:1;object-fit:contain;background:#eef2f5;padding:8px}.asset-info{display:flex;gap:5px;align-items:center;padding:8px}.asset-info span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:700;flex:1}.asset-delete{padding:4px 7px;color:var(--red)}.reference-note{color:var(--muted);margin:6px 0 12px}
    .section-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.templates{display:grid;grid-template-columns:repeat(4,minmax(190px,1fr));gap:10px}.template{position:relative;min-height:210px;text-align:left;padding:0;border:1px solid var(--line);background:#fff;overflow:hidden}.template.selected{border:2px solid var(--cyan);box-shadow:inset 0 0 0 1px var(--cyan)}.template img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;background:#e8edf2}.template-copy{display:block;padding:11px}.template strong{display:block;margin-bottom:5px}.template span{display:block;color:var(--muted);font-weight:400;font-size:12px}.template-actions{display:flex;gap:6px;padding:0 10px 10px}.template-actions button{padding:5px 8px;font-size:11px}.brand-options{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;padding:14px 16px;background:#fff;border:1px solid var(--line);border-radius:6px}.custom-template{padding:16px;background:#fff;border:1px solid var(--line);display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}.custom-template .wide{grid-column:1/-1}.formatbar{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}.formatbar button{width:34px;height:32px;padding:0}.pagination{display:flex;justify-content:center;align-items:center;gap:8px;margin:16px 0}.pagination span{color:var(--muted);font-weight:700}
    .calendar-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.calendar-nav{display:flex;align-items:center;gap:7px}.calendar{display:grid;grid-template-columns:repeat(7,minmax(140px,1fr));border-left:1px solid var(--line);border-top:1px solid var(--line);background:#fff}.weekday,.day{border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.weekday{padding:8px;background:#edf1f5;color:var(--muted);font-size:12px;font-weight:800;text-align:center}.day{min-height:165px;padding:8px}.day.outside{background:#f7f8fa;color:#9aa5b2}.day.today{box-shadow:inset 0 0 0 2px var(--cyan)}.day-number{font-weight:800;margin-bottom:6px}.calendar-item{display:block;width:100%;margin:5px 0;padding:7px;border:0;border-left:4px solid var(--cyan);background:#eaf7f5;text-align:left;font-size:11px;font-weight:700}.calendar-item.published{border-color:var(--blue);background:#edf3fb}.calendar-item.planned{border-color:var(--amber);background:#fff6e7}.calendar-item time,.calendar-item small{display:block;color:var(--muted);font-size:10px}.calendar-item .cal-product{display:inline-block;margin:3px 0;color:var(--blue);text-transform:uppercase;font-size:9px}
    .user-create{display:grid;grid-template-columns:1fr 1fr auto auto;gap:10px;align-items:end;background:#fff;border:1px solid var(--line);padding:16px;border-radius:6px;margin-bottom:16px}.check-label{display:flex;gap:8px;align-items:center;padding-bottom:10px}.check-label input{width:auto;margin:0}.user-actions{display:flex;gap:6px;flex-wrap:wrap}.company-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.company-card{background:#fff;border:1px solid var(--line);border-radius:6px;padding:16px}.company-card span{display:block;color:var(--muted);font-size:12px;font-weight:800}.company-card strong{display:block;font-size:21px;margin-top:4px}.company-form{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;align-items:end;background:#fff;border:1px solid var(--line);border-radius:6px;padding:16px;margin-bottom:16px}.company-form .wide{grid-column:span 2}.masked{font-family:ui-monospace,SFMono-Regular,monospace;color:var(--muted)}
    .planning-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.planning-panel{background:#fff;border:1px solid var(--line);padding:16px;border-radius:6px}.planning-panel h2{margin:0 0 12px}.planning-panel .editor-actions button{flex:1}.idea-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.meta-chip{padding:2px 6px;border-radius:3px;background:#edf1f5;color:var(--muted);font-size:10px;font-weight:800}.meta-chip.warn{background:#fff0dc;color:#914f00}.variants{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0}.variant-list{display:flex;gap:5px;flex-wrap:wrap}.variant-list button{font-size:11px;padding:5px 7px}.favorite{color:#a96200}
    :root{--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--paper:#f7f8fb;--white:#fff;--cyan:#10bfae;--blue:#2563eb;--amber:#b7791f;--red:#dc2626;--violet:#7c3aed;--nav:#0d1324;--soft:#f3f6fb;--shadow:0 18px 55px rgba(15,23,42,.10);--shadow-sm:0 10px 28px rgba(15,23,42,.07);--radius:8px}
    body{min-height:100vh;background:radial-gradient(circle at 18% 4%,rgba(16,191,174,.16),transparent 28%),radial-gradient(circle at 90% 0,rgba(37,99,235,.12),transparent 30%),linear-gradient(180deg,#f8fafc 0,#f3f6fb 100%);font:14px/1.48 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .app-shell{min-height:100vh;display:grid;grid-template-columns:268px minmax(0,1fr)}.sidebar{position:sticky;top:0;height:100vh;padding:18px;background:linear-gradient(180deg,#0c1222,#111827);color:#e5eefc;display:flex;flex-direction:column;border-right:1px solid rgba(255,255,255,.08);box-shadow:8px 0 35px rgba(15,23,42,.16);z-index:3}.brand{display:flex;align-items:center;gap:12px;padding:8px 8px 18px}.brand-mark{width:38px;height:38px;border-radius:8px;background:linear-gradient(135deg,var(--cyan),var(--blue));box-shadow:0 12px 30px rgba(16,191,174,.24);position:relative}.brand-mark::after{content:"";position:absolute;inset:10px;border:2px solid rgba(255,255,255,.75);border-radius:50%}.brand h1{font-size:14px;letter-spacing:.08em}.brand span,.sidebar-foot span{display:block;color:#91a0b8;font-size:12px}.tabs{display:flex;flex-direction:column;gap:6px;border:0;margin:0}.tab{position:relative;display:flex;width:100%;align-items:center;justify-content:flex-start;border:1px solid transparent;border-radius:8px;color:#afbdd2;background:transparent;padding:11px 12px;transition:background .18s ease,color .18s ease,transform .18s ease,border-color .18s ease}.tab::before{content:"";width:8px;height:8px;border-radius:999px;background:#3b465d;margin-right:10px;transition:background .18s ease,box-shadow .18s ease}.tab:hover{transform:translateX(3px);background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.08);color:#fff}.tab.active{background:linear-gradient(135deg,rgba(16,191,174,.18),rgba(37,99,235,.15));border-color:rgba(16,191,174,.35);color:#fff;box-shadow:inset 0 0 0 1px rgba(255,255,255,.04)}.tab.active::before{background:var(--cyan);box-shadow:0 0 0 4px rgba(16,191,174,.16)}.sidebar-foot{margin-top:auto;padding:14px 10px;border:1px solid rgba(255,255,255,.08);border-radius:8px;background:rgba(255,255,255,.04)}
    .workspace{min-width:0}.topbar{position:sticky;top:0;z-index:2;min-height:74px;padding:14px 28px;background:rgba(248,250,252,.82);backdrop-filter:blur(18px);border-bottom:1px solid rgba(148,163,184,.22);display:flex;align-items:center;justify-content:space-between;color:var(--ink)}.topbar h2{margin:0;font-size:20px}.topbar p{margin:2px 0 0;color:var(--muted)}.account{gap:12px;color:var(--ink)}.account span{padding:7px 10px;border:1px solid var(--line);border-radius:999px;background:#fff;box-shadow:var(--shadow-sm)}.account button{color:var(--ink);border-color:var(--line);background:#fff}
    main{max-width:none;padding:24px 28px 54px}.view.active{display:block;animation:rise .28s ease both}@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@keyframes glow{0%,100%{box-shadow:0 0 0 0 rgba(16,191,174,.18)}50%{box-shadow:0 0 0 6px rgba(16,191,174,.03)}}@keyframes shimmer{to{transform:translateX(260%)}}
    button,.button,input,select,textarea{border-radius:8px}button,.button{transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease,background .16s ease}button:hover,.button:hover{transform:translateY(-1px);box-shadow:var(--shadow-sm)}button.primary{background:linear-gradient(135deg,#2563eb,#1d4ed8);box-shadow:0 14px 30px rgba(37,99,235,.22)}button.success{background:linear-gradient(135deg,#10bfae,#0f9f91);box-shadow:0 14px 30px rgba(16,191,174,.22)}input,select,textarea{border-color:#d8e0eb;background:#fff;transition:border-color .15s ease,box-shadow .15s ease}input:focus,select:focus,textarea:focus{outline:0;border-color:rgba(37,99,235,.65);box-shadow:0 0 0 4px rgba(37,99,235,.10)}
    .toolbar,.modelbar,.planning-panel,.custom-template,.brand-options,.company-form,.user-create,.company-card,.metric,.draft,.template,.asset,table{background:rgba(255,255,255,.92);border-color:rgba(203,213,225,.78);box-shadow:var(--shadow-sm)}.toolbar{grid-template-columns:180px 90px 170px minmax(240px,1fr) auto;padding:18px;border-radius:8px}.modelbar{grid-template-columns:repeat(3,minmax(0,1fr));border-radius:8px}.section-head{margin-top:24px}.section-head h2,.calendar-head h2,h2{font-size:19px;letter-spacing:0}
    .metrics{border:0;background:transparent;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.metric{position:relative;overflow:hidden;border:1px solid rgba(203,213,225,.78);border-radius:8px}.metric::after{content:"";position:absolute;inset:0 auto 0 -50%;width:22%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.75),transparent);transform:translateX(-100%);animation:shimmer 6s ease-in-out infinite}.metric strong{font-size:28px}
    .ideas{border:0;background:transparent;display:grid;gap:10px}.idea{position:relative;grid-template-columns:26px 110px minmax(240px,1fr) auto;background:#fff;border:1px solid rgba(203,213,225,.78);border-radius:8px;box-shadow:var(--shadow-sm);overflow:hidden;transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}.idea:hover{transform:translateY(-2px);box-shadow:var(--shadow);border-color:rgba(16,191,174,.42)}.idea::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,var(--cyan),var(--blue));opacity:.85}.badge,.meta-chip{border-radius:999px}.badge{background:#eef6ff;color:#1d4ed8;letter-spacing:.03em}
    .templates{grid-template-columns:repeat(4,minmax(210px,1fr))}.template{border-radius:8px;min-height:230px;box-shadow:var(--shadow-sm);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}.template:hover,.draft:hover,.asset:hover,.planning-panel:hover{transform:translateY(-2px);box-shadow:var(--shadow)}.template.selected{border-color:var(--cyan);box-shadow:0 0 0 4px rgba(16,191,174,.10),var(--shadow)}.template img{filter:saturate(1.06) contrast(1.02)}.template-copy strong{color:#111827}.assets{grid-template-columns:repeat(6,minmax(145px,1fr))}.asset{border-radius:8px;transition:transform .18s ease,box-shadow .18s ease}.asset.selected{box-shadow:0 0 0 4px rgba(16,191,174,.10)}
    .drafts{grid-template-columns:repeat(3,minmax(280px,1fr));gap:18px}.draft{border-radius:8px;transition:transform .18s ease,box-shadow .18s ease}.draft img{filter:saturate(1.04)}.draft-body{padding:16px}.draft h3{font-size:17px}.draft p{line-height:1.55}.kanban{display:grid;grid-template-columns:repeat(5,minmax(230px,1fr));gap:12px;overflow-x:auto;align-items:start}.kanban-column{min-height:220px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#eef3f8}.kanban-column h3{margin:0 0 10px}.kanban-card{margin-bottom:10px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff;box-shadow:var(--shadow-sm)}.kanban-card h4{margin:8px 0}.kanban-card p{max-height:64px;overflow:hidden;color:var(--muted)}.home-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.home-card{padding:20px;border:1px solid var(--line);border-radius:8px;background:#fff;box-shadow:var(--shadow-sm)}.home-card strong{display:block;margin-top:8px;font-size:26px}.onboarding-modal{width:min(720px,calc(100vw - 28px));padding:0}.onboarding-body{padding:24px}.onboarding-progress{display:flex;gap:6px;margin:12px 0 22px}.onboarding-progress span{height:5px;flex:1;border-radius:99px;background:#dbe3ee}.onboarding-progress span.active{background:var(--cyan)}.onboarding-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.onboarding-fields .wide{grid-column:1/-1}.onboarding-actions{display:flex;justify-content:space-between;gap:10px;margin-top:22px}
    .calendar{border:0;gap:10px;background:transparent;grid-template-columns:repeat(7,minmax(0,1fr))}.weekday{border:0;border-radius:8px;background:#eaf0f7}.day{border:1px solid rgba(203,213,225,.78);border-radius:8px;background:rgba(255,255,255,.88);box-shadow:var(--shadow-sm);transition:transform .16s ease,box-shadow .16s ease}.day:hover{transform:translateY(-2px);box-shadow:var(--shadow)}.day.today{box-shadow:0 0 0 3px rgba(16,191,174,.18),var(--shadow-sm)}.calendar-item{border-radius:7px;border-left:0;background:linear-gradient(135deg,#ecfdf5,#eef6ff);box-shadow:inset 0 0 0 1px rgba(16,191,174,.16);transition:transform .15s ease,box-shadow .15s ease}.calendar-item:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(15,23,42,.10)}.calendar-item.published{background:linear-gradient(135deg,#eff6ff,#f5f3ff)}.calendar-item.planned{background:linear-gradient(135deg,#fff7ed,#fefce8)}
    th{background:#f4f7fb;color:#64748b;font-size:11px;letter-spacing:.04em;text-transform:uppercase}td{background:rgba(255,255,255,.78)}tbody tr{transition:background .16s ease}tbody tr:hover td{background:#f8fbff}.scroll{border-radius:8px;overflow:auto;box-shadow:var(--shadow-sm)}.scroll table{box-shadow:none}.status.busy{animation:glow 2s ease-in-out infinite}.notice{border-radius:8px;box-shadow:var(--shadow);animation:rise .22s ease both}
    dialog{border-radius:8px;box-shadow:0 30px 110px rgba(15,23,42,.42)}.editor-head{background:linear-gradient(135deg,#0f172a,#111827);color:#fff}.editor-head button{color:#fff;background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.16)}.editor-grid{background:#f8fafc}.editor-grid img{border-radius:8px;box-shadow:var(--shadow-sm)}#socialVariant{border-radius:8px;background:#fff;box-shadow:var(--shadow-sm)}
    .pricing-button{display:inline-flex;align-items:center;gap:8px;color:#fff!important;border:1px solid rgba(16,191,174,.42)!important;background:linear-gradient(135deg,#0f766e,#2563eb)!important;box-shadow:0 12px 28px rgba(37,99,235,.20)}.pricing-button::before{content:"★";color:#fde68a}.pricing-modal{width:min(1120px,calc(100vw - 28px));max-height:92vh;padding:0;overflow:auto}.pricing-head{display:flex;align-items:flex-start;justify-content:space-between;padding:24px 26px 18px;border-bottom:1px solid var(--line);background:#fff}.pricing-head h2{margin:0;font-size:25px}.pricing-head p{margin:5px 0 0;color:var(--muted)}.pricing-content{padding:22px 26px 26px;background:#f6f8fc}.pricing-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.price-card{position:relative;display:flex;flex-direction:column;min-height:430px;padding:20px;border:1px solid #dbe3ee;border-radius:8px;background:#fff;box-shadow:var(--shadow-sm)}.price-card.popular{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(16,191,174,.10),var(--shadow)}.popular-label{position:absolute;right:14px;top:14px;padding:4px 8px;border-radius:999px;background:#dcfce7;color:#087f6f;font-size:10px;font-weight:900;text-transform:uppercase}.price-card h3{margin:0;font-size:20px}.price-card .tagline{min-height:44px;color:var(--muted)}.price{display:flex;align-items:baseline;gap:7px;margin:14px 0}.price strong{font-size:34px}.price span{color:var(--muted)}.plan-limits{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}.plan-limit{padding:9px;border-radius:8px;background:#f3f6fb}.plan-limit strong,.plan-limit span{display:block}.plan-limit span{color:var(--muted);font-size:11px}.plan-features{display:grid;gap:8px;margin:0 0 18px;padding:0;list-style:none}.plan-features li{position:relative;padding-left:20px}.plan-features li::before{content:"✓";position:absolute;left:0;color:var(--cyan);font-weight:900}.price-card button{margin-top:auto;width:100%}.billing-note{display:flex;justify-content:space-between;gap:16px;margin-top:16px;padding:14px 16px;border:1px solid #dbe3ee;border-radius:8px;background:#fff;color:var(--muted)}.billing-note strong{color:var(--ink)}.current-plan{color:var(--cyan);font-weight:800}
    @media(max-width:1100px){.app-shell{grid-template-columns:1fr}.sidebar{position:static;height:auto}.tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}.tab:hover{transform:translateY(-1px)}.sidebar-foot{display:none}.modelbar{grid-template-columns:1fr 1fr}.topbar{position:static}.templates{grid-template-columns:repeat(3,1fr)}}
    @media(max-width:950px){.drafts{grid-template-columns:repeat(2,1fr)}.editor-grid{grid-template-columns:1fr}.toolbar,.user-create,.planning-grid,.company-form{grid-template-columns:1fr 1fr}.company-grid{grid-template-columns:repeat(2,1fr)}.toolbar label:nth-child(4){grid-column:1/-1}.assets,.templates{grid-template-columns:repeat(3,1fr)}.calendar-wrap{overflow-x:auto}.calendar{min-width:900px}.pricing-grid{grid-template-columns:1fr}.price-card{min-height:0}.home-grid{grid-template-columns:1fr}}
    @media(max-width:620px){main,.topbar{padding-left:14px;padding-right:14px}.sidebar{min-width:0}.brand h1{font-size:14px}.topbar{align-items:flex-start;flex-direction:column}.topbar>div:first-child{min-width:0}.topbar p{white-space:normal}.account{gap:6px;flex-wrap:wrap}.account #updated{display:none}.tabs{display:flex;max-width:100%;overflow-x:auto;flex-direction:row}.tab{width:auto;flex:0 0 auto;padding:11px 12px}.toolbar,.modelbar,.user-create,.brand-options,.custom-template,.planning-grid,.variants,.company-grid,.company-form{grid-template-columns:1fr}.toolbar label:nth-child(4),.custom-template .wide,.company-form .wide{grid-column:auto}.drafts{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.idea{grid-template-columns:24px 74px minmax(0,1fr)}.idea .editor-actions{grid-column:2/-1}.assets,.templates{grid-template-columns:repeat(2,minmax(0,1fr))}.scroll{overflow-x:auto}.scroll table{min-width:780px}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark"></span><div><h1>CONTENT STUDIO</h1><span>AI publishing workspace</span></div></div>
    <nav class="tabs">
      <button class="tab active" data-view="homeView" data-pipeline-label="Головна" data-kanban-hidden="true">Головна</button>
      <button class="tab" data-view="ideasView" data-pipeline-label="Ідеї" data-kanban-label="Бібліотека ідей">Ідеї</button>
      <button class="tab" data-view="planningView" data-pipeline-label="Контент-план" data-kanban-hidden="true">Контент-план</button>
      <button class="tab" data-view="draftsView" data-pipeline-label="Чернетки" data-kanban-label="Дошка">Чернетки</button>
      <button class="tab" data-view="calendarView">Календар</button>
      <button class="tab" data-view="opsView" data-pipeline-label="Витрати" data-kanban-label="Аналітика">Витрати</button>
      <button class="tab" data-view="companyView">Бренд</button>
      <button class="tab" id="usersTab" data-view="usersView">Налаштування</button>
      <button class="tab" id="platformTab" data-view="platformView" hidden>Платформа</button>
    </nav>
    <div class="sidebar-foot"><strong id="sidebarCompany">VoicerHub</strong><span>Content operations center</span></div>
  </aside>
  <div class="workspace">
    <header class="topbar">
      <div><h2 id="viewTitle">Теми</h2><p id="viewSubtitle">Плануйте і запускайте AI-публікації з одного робочого центру.</p></div>
      <div class="account"><button class="pricing-button" id="openPricing">Тарифи</button><select id="workspaceSelect" hidden aria-label="Workspace"></select><span id="currentCompany"></span><span id="currentUser"></span><span id="updated">—</span><button id="logout" title="Вийти">Вийти</button></div>
    </header>
<main>

  <section id="homeView" class="view active">
    <div class="home-grid">
      <article class="home-card"><span>Ідеї</span><strong id="homeIdeas">0</strong><button data-home-view="ideasView">Відкрити бібліотеку</button></article>
      <article class="home-card"><span>Чернетки в роботі</span><strong id="homeDrafts">0</strong><button data-home-view="draftsView">Відкрити чернетки</button></article>
      <article class="home-card"><span>Заплановано</span><strong id="homeScheduled">0</strong><button data-home-view="calendarView">Відкрити календар</button></article>
    </div>
  </section>

  <section id="ideasView" class="view">
    <div class="toolbar">
      <label>Рубрика<select id="ideaProduct"></select></label>
      <label>Кількість<input id="ideaCount" type="number" min="1" max="12" value="6"></label>
      <label>Тон<select id="ideaTone"><option value="expert">Експертний</option><option value="sales">Продаючий</option><option value="light">Легкий</option><option value="news">Новинний</option></select></label>
      <label>Фокус або побажання<input id="ideaFocus" placeholder="Наприклад: практичні кейси для відділу продажів"></label>
      <button class="primary" id="generateIdeas">Згенерувати теми</button>
    </div>
    <div class="modelbar">
      <label>Модель тексту
        <select id="textModel">
          <option value="gpt-5-mini">GPT-5 mini · економна</option>
          <option value="gpt-5.4-mini" selected>GPT-5.4 mini · баланс</option>
          <option value="gpt-5.4">GPT-5.4 · сильна</option>
          <option value="gpt-5.5">GPT-5.5 · максимальна</option>
        </select>
        <small>Застосовується до тем і текстів постів.</small>
      </label>
      <label id="imageModelField" class="image-setting">Модель зображень
        <select id="imageModel">
          <option value="gpt-image-1-mini">GPT Image 1 mini · економна</option>
          <option value="gpt-image-1.5">GPT Image 1.5</option>
          <option value="gpt-image-2" selected>GPT Image 2 · найкраща якість</option>
        </select>
        <small>GPT Image 2 краще зберігає деталі референсів.</small>
      </label>
      <label>Режим генерації
        <select id="generationMode">
          <option value="fast" selected>Швидко · звичайний API</option>
          <option value="batch">Економно · Batch до 24 годин</option>
        </select>
        <small>Для окремих постів рекомендовано швидкий режим.</small>
      </label>
    </div>
    <div class="section-head image-setting"><h2>Візуальний шаблон</h2><button id="showCustomTemplate">＋ Власний шаблон</button></div>
    <div id="customTemplateForm" class="custom-template image-setting" hidden>
      <label>Назва<input id="customTemplateName" placeholder="Наприклад: Premium Retail"></label>
      <label>Короткий опис<input id="customTemplateDescription" placeholder="Як виглядатиме зображення"></label>
      <label class="wide">Промпт стилю<textarea id="customTemplatePrompt" placeholder="Опишіть композицію, світло, матеріали, палітру та настрій. Не описуйте тему конкретного поста."></textarea></label>
      <label>Розташування заголовка<select id="customTemplateLayout"><option value="top_left">Зверху ліворуч</option><option value="left_panel">Ліва панель</option><option value="bottom_left">Знизу ліворуч</option><option value="top_band">Верхня смуга</option></select></label>
      <label>Акцентний колір<input id="customTemplateAccent" type="color" value="#18ecd6"></label>
      <div class="editor-actions wide"><button class="primary" id="createTemplate">Зберегти шаблон</button><button id="cancelCustomTemplate">Скасувати</button></div>
    </div>
    <div id="templates" class="templates image-setting"></div>
    <div class="asset-head image-setting">
      <div><h2>Бренд-матеріали</h2><p class="reference-note">Оберіть до 16 логотипів або прикладів. Вони будуть використані в новому зображенні.</p></div>
      <label class="button asset-upload">＋ Додати файли<input id="referenceUpload" type="file" accept="image/png,image/jpeg,image/webp" multiple></label>
    </div>
    <div class="brand-options image-setting">
      <label>Логотип продукту<select id="logoReference"><option value="">Без логотипа продукту</option></select><small>PNG/WebP з прозорістю накладається без фону.</small></label>
      <label>Логотип компанії<select id="companyLogoReference"><option value="">Без логотипа компанії</option></select><small>Опціональний окремий логотип у верхньому куті.</small></label>
      <div><strong>Як працюють файли</strong><p class="reference-note">Позначені картки використовуються як AI-референси. Логотип обирається окремо і може використовуватися без референсів.</p></div>
    </div>
    <label>Посилання для поста<input id="defaultLink" type="url" placeholder="https://voicerhub.com/ua/products/tony"><small>Буде додано як логічний клікабельний текст. Поле можна змінити в редакторі.</small></label>
    <div id="assets" class="assets image-setting"></div>
    <div id="waveCoverNotice" class="brand-options" hidden>
      <div><strong>Постійна обкладинка Voicer Wave</strong><p class="reference-note">Для цієї рубрики завжди використовується затверджене зображення Voicer Wave. OpenAI не генерує нову картинку, тому витрат на зображення немає.</p></div>
      <img src="wave-cover" alt="Voicer Wave" style="display:block;width:180px;max-width:100%;aspect-ratio:3/2;object-fit:cover;border:1px solid var(--line)">
    </div>
    <div class="editor-actions"><button class="success" id="generateSelected">Генерувати вибрані пости</button></div>
    <div id="ideas" class="ideas"></div>
    <div id="ideasPagination" class="pagination"></div>
  </section>

  <section id="planningView" class="view">
    <div class="planning-grid">
      <article class="planning-panel">
        <h2>Контент-план</h2>
        <label>Період<select id="planPeriod"><option value="week">Тиждень</option><option value="month">Місяць</option></select></label>
        <label>Початок<input id="planStart" type="date"></label>
        <label>Кількість постів<input id="planPosts" type="number" min="1" max="31" value="5"></label>
        <label>Рубрика<select id="planProduct"></select></label>
        <label>Фокус<textarea id="planFocus" placeholder="Цілі, аудиторія або основні акценти"></textarea></label>
        <div class="editor-actions"><button class="primary" id="generatePlan">Створити план</button></div>
      </article>
      <article class="planning-panel">
        <h2>Серія постів</h2>
        <label>Рубрика<select id="seriesProduct"></select></label>
        <label>Кількість частин<select id="seriesParts"><option>3</option><option>4</option><option>5</option></select></label>
        <label>Тон<select id="seriesTone"><option value="expert">Експертний</option><option value="sales">Продаючий</option><option value="light">Легкий</option><option value="news">Новинний</option></select></label>
        <label>Тема серії<textarea id="seriesTopic" placeholder="Наприклад: як побудувати контроль якості дзвінків"></textarea></label>
        <div class="editor-actions"><button class="primary" id="generateSeries">Створити серію</button></div>
      </article>
      <article class="planning-panel">
        <h2>Матеріал із сайту</h2>
        <label>URL<input id="materialUrl" type="url" placeholder="https://voicerhub.com/ua/..."></label>
        <label>Або текст матеріалу<textarea id="materialText" placeholder="Для сторінок, які не дозволяють автоматичне читання"></textarea></label>
        <label>Рубрика<select id="materialProduct"></select></label>
        <label>Кількість тем<input id="materialCount" type="number" min="1" max="8" value="3"></label>
        <label>Тон<select id="materialTone"><option value="expert">Експертний</option><option value="sales">Продаючий</option><option value="light">Легкий</option><option value="news">Новинний</option></select></label>
        <div class="editor-actions"><button class="primary" id="importMaterial">Створити теми</button></div>
      </article>
    </div>
    <p class="reference-note">Створені плани, серії та матеріали з сайту з’являються на сторінці «Теми» для перевірки й запуску.</p>
  </section>

  <section id="draftsView" class="view">
    <div class="section-head"><h2>Чернетки та приклади</h2><button id="toggleFavorites">☆ Показати вдалі приклади</button></div>
    <div id="drafts" class="drafts"></div>
    <div id="draftsPagination" class="pagination"></div>
  </section>

  <section id="calendarView" class="view">
    <div class="calendar-head"><h2 id="calendarTitle">Календар</h2><div class="calendar-nav"><button id="calendarPrev" title="Попередній місяць">←</button><button id="calendarToday">Сьогодні</button><button id="calendarNext" title="Наступний місяць">→</button></div></div>
    <div class="calendar-wrap"><div id="calendar" class="calendar"></div></div>
  </section>

  <section id="opsView" class="view">
    <div class="metrics">
      <div class="metric"><span>Загальні витрати</span><strong id="total">$0.0000</strong></div>
      <div class="metric"><span>Тексти</span><strong id="text">$0.0000</strong></div>
      <div class="metric"><span>Зображення</span><strong id="image">$0.0000</strong></div>
      <div class="metric"><span>Активні завдання</span><strong id="active">0</strong></div>
    </div>
    <h2>Генерація</h2><div class="scroll"><table><thead><tr><th>ID</th><th>Продукт</th><th>Тема</th><th>Режим і моделі</th><th>Статус</th><th>Очікування</th><th>Batch</th><th>Помилка</th><th>Дія</th></tr></thead><tbody id="jobs"></tbody></table></div>
    <h2>OpenAI Batch</h2><div class="scroll"><table><thead><tr><th>ID</th><th>Тип</th><th>Статус</th><th>Очікування</th><th>Виконано</th><th>Помилки</th><th>Токени</th><th>Вартість</th></tr></thead><tbody id="batches"></tbody></table></div>
  </section>

  <section id="usersView" class="view">
    <div id="userAdmin" hidden>
      <h2>Новий користувач</h2>
      <div class="user-create">
        <label>Логін<input id="newUsername" autocomplete="off" placeholder="name.surname"></label>
        <label>Тимчасовий пароль<input id="newPassword" type="password" autocomplete="new-password" placeholder="Мінімум 10 символів"></label>
        <label class="check-label"><input id="newIsAdmin" type="checkbox"> Адміністратор</label>
        <button class="primary" id="createUser">Додати</button>
      </div>
      <div class="scroll"><table><thead><tr><th>Логін</th><th>Роль</th><th>Статус</th><th>Створено</th><th>Дії</th></tr></thead><tbody id="users"></tbody></table></div>
    </div>
    <h2>Мій пароль</h2>
    <div class="user-create">
      <label>Новий пароль<input id="ownPassword" type="password" autocomplete="new-password" placeholder="Мінімум 10 символів"></label>
      <button id="changeOwnPassword">Змінити пароль</button>
    </div>
  </section>

  <section id="companyView" class="view">
    <div class="company-grid" id="companyCards"></div>
    <h2>Режим робочого простору</h2>
    <div class="company-form">
      <label>Навігація<select id="workspaceMode"><option value="pipeline">Pipeline</option><option value="kanban">Kanban</option></select></label>
      <button class="primary" id="saveWorkspaceMode">Зберегти режим</button>
      <button id="restartOnboarding">Повторити onboarding</button>
    </div>
    <h2>Telegram-канал</h2>
    <div class="company-form">
      <label class="wide">Канал або ID<input id="companyChannel" placeholder="@company_channel або -100..."></label>
      <label class="wide">Токен бота<input id="companyBotToken" type="password" autocomplete="off" placeholder="123456:ABC..."></label>
      <button class="primary" id="saveTelegram">Перевірити і зберегти</button>
    </div>
    <p class="reference-note">Бот повинен бути адміністратором каналу з правом публікувати повідомлення. Токен зберігається у зашифрованому вигляді.</p>
    <div class="section-head"><h2>Рубрики компанії</h2><button class="primary" id="showRubricForm">Додати рубрику</button></div>
    <div id="rubricForm" class="custom-template" hidden>
      <label>Назва<input id="rubricName" placeholder="Кейси клієнтів"></label>
      <label>Slug<input id="rubricSlug" placeholder="customer-cases"></label>
      <label class="wide">Що можна розповідати<textarea id="rubricDescription" placeholder="Опишіть продукт, аудиторію, факти та теми рубрики"></textarea></label>
      <label class="wide">Редакційні правила<textarea id="rubricInstructions" placeholder="Тон, структура, обмеження, бажані CTA"></textarea></label>
      <label class="wide">Посилання за замовчуванням<input id="rubricLink" type="url" placeholder="https://company.com/product"></label>
      <div class="editor-actions"><button class="primary" id="createRubric">Зберегти рубрику</button><button id="cancelRubric">Скасувати</button></div>
    </div>
    <div class="scroll"><table><thead><tr><th>Назва</th><th>Slug</th><th>Опис</th><th>Посилання</th><th>Статус</th><th></th></tr></thead><tbody id="rubrics"></tbody></table></div>
  </section>

  <section id="platformView" class="view">
    <h2>Нова компанія</h2>
    <div class="company-form">
      <label>Назва<input id="orgName" placeholder="Company name"></label>
      <label>Slug<input id="orgSlug" placeholder="company-name"></label>
      <label>Логін власника<input id="orgOwner" placeholder="owner.name"></label>
      <label>Пароль власника<input id="orgPassword" type="password" autocomplete="new-password" placeholder="Мінімум 10 символів"></label>
      <label>Користувачі<input id="orgUsers" type="number" min="1" max="50" value="50"></label>
      <label>Канали<input id="orgChannels" type="number" min="1" max="1" value="1"></label>
      <label>Публікації/міс<input id="orgPublications" type="number" min="1" value="90"></label>
      <label>AI бюджет/міс<input id="orgBudget" type="number" min="0" step="1" value="50"></label>
      <button class="primary" id="createOrganization">Створити компанію</button>
    </div>
    <div class="scroll"><table><thead><tr><th>ID</th><th>Компанія</th><th>Slug</th><th>Ліміти</th><th>Користувачі</th><th>Статус</th></tr></thead><tbody id="organizations"></tbody></table></div>
    <div class="section-head">
      <h2>Використання AI</h2>
      <label>Період
        <select id="usagePeriod">
          <option value="today">Сьогодні</option>
          <option value="7d">Останні 7 днів</option>
          <option value="month" selected>Поточний місяць</option>
          <option value="all">За весь час</option>
        </select>
      </label>
    </div>
    <div class="metrics" id="platformUsageTotals"></div>
    <h2>За компаніями</h2>
    <div class="scroll"><table><thead><tr><th>Компанія</th><th>Текстові генерації</th><th>Зображення</th><th>Вхідні токени</th><th>Вихідні токени</th><th>Вартість</th></tr></thead><tbody id="companyUsage"></tbody></table></div>
    <h2>За користувачами</h2>
    <div class="scroll"><table><thead><tr><th>Компанія</th><th>Користувач</th><th>Текстові генерації</th><th>Зображення</th><th>Токени</th><th>Вартість</th></tr></thead><tbody id="userUsage"></tbody></table></div>
    <h2>За моделями</h2>
    <div class="scroll"><table><thead><tr><th>Компанія</th><th>Тип</th><th>Модель</th><th>Операції</th><th>Токени / зображення</th><th>Вартість</th></tr></thead><tbody id="modelUsage"></tbody></table></div>
  </section>
</main>
  </div>
</div>

<dialog id="pricing" class="pricing-modal">
  <div class="pricing-head">
    <div><h2>Тарифи Content Studio</h2><p>Місячна підписка для вашої контент-команди.</p></div>
    <button id="closePricing" title="Закрити">✕</button>
  </div>
  <div class="pricing-content">
    <div class="pricing-grid" id="pricingGrid"></div>
    <div class="billing-note">
      <span><strong>Оплата:</strong> Telegram Stars. Після підтвердження тариф активується автоматично.</span>
      <span>Інші способи оплати з’являться незабаром.</span>
    </div>
  </div>
</dialog>

<dialog id="editor">
  <div class="editor-head"><strong>Редагування поста</strong><button id="closeEditor">✕</button></div>
  <div class="editor-grid">
    <div><img id="editorImage" alt="Зображення поста"><div class="editor-actions"><button id="regenImage">↻ Інша картинка</button></div></div>
    <div>
      <label>Заголовок<input id="editorTitle"></label>
      <label>Заголовок на візуалі<input id="editorVisualTitle"><small>Без emoji. Можна зробити коротшим за заголовок поста.</small></label>
      <button id="syncVisualTitle">Оновити із заголовка поста</button>
      <div class="variants">
        <div><label>Варіанти заголовка</label><div id="titleVariants" class="variant-list"></div></div>
        <div><label>Варіанти CTA</label><div id="ctaVariants" class="variant-list"></div></div>
      </div>
      <label>Текст Telegram<textarea id="editorCaption"></textarea></label>
      <div class="formatbar" aria-label="Форматування"><button data-format="b" title="Жирний"><b>B</b></button><button data-format="i" title="Курсив"><i>I</i></button><button data-format="u" title="Підкреслений"><u>U</u></button><button data-format="s" title="Закреслений"><s>S</s></button><button data-format="blockquote" title="Цитата">❞</button><button data-format="code" title="Моноширинний">&lt;/&gt;</button><button data-format="tg-spoiler" title="Прихований">◫</button><button id="insertLink" title="Посилання">↗</button></div>
      <label>Посилання<input id="editorLink" type="url" placeholder="https://voicerhub.com/ua/products/tony"></label>
      <h3>Версії для соцмереж</h3>
      <div class="editor-actions" id="socialButtons">
        <button data-social-generate="instagram">Instagram 1080×1350</button>
        <button data-social-generate="linkedin">LinkedIn 1200×627</button>
        <button data-social-generate="facebook">Facebook 1200×630</button>
        <button data-social-generate="x">X 1600×900</button>
      </div>
      <div id="socialVariant" hidden>
        <div class="editor-actions">
          <strong id="socialPlatform"></strong>
          <button id="copySocialText">Копіювати текст</button>
          <a id="downloadSocialImage" class="button" href="#">Завантажити зображення</a>
        </div>
        <img id="socialImage" alt="Версія для соцмережі">
        <label>Заголовок<input id="socialTitle"></label>
        <label>Заголовок на візуалі<input id="socialVisualTitle"></label>
        <label>Текст<textarea id="socialText"></textarea></label>
        <button id="saveSocialVariant">Зберегти версію</button>
      </div>
      <div class="modelbar" id="editorVisualSettings">
        <label>Шаблон картинки<select id="editorTemplate"></select></label>
        <label>Логотип продукту<select id="editorLogo"><option value="">Без логотипа</option></select></label>
        <label>Логотип компанії<select id="editorCompanyLogo"><option value="">Без логотипа</option></select></label>
      </div>
      <div class="editor-actions">
        <button class="primary" id="saveDraft">Зберегти</button>
        <button id="regenText">↻ Інший текст</button>
        <button id="favoriteDraft">☆ До прикладів</button>
        <button class="success" id="publishNow">Опублікувати зараз</button>
      </div>
      <div class="schedule"><input id="scheduleAt" type="datetime-local"><button id="scheduleDraft">Запланувати</button></div>
      <div class="editor-actions"><button class="danger" id="cancelSchedule">Скасувати розклад</button></div>
    </div>
  </div>
</dialog>
<dialog id="onboarding" class="onboarding-modal">
  <div class="pricing-head"><div><h2>Налаштування workspace</h2><p id="onboardingSubtitle"></p></div><button id="skipOnboarding">Пропустити</button></div>
  <div class="onboarding-body">
    <div id="onboardingProgress" class="onboarding-progress"></div>
    <div id="onboardingContent"></div>
    <div class="onboarding-actions"><button id="onboardingBack">Назад</button><button class="primary" id="onboardingNext">Продовжити</button></div>
  </div>
</dialog>
<div id="notice" class="notice"></div>

<script>
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=v=>`$${Number(v||0).toFixed(4)}`; const short=v=>v?`${v.slice(0,14)}...`:"—";
const rubricLabel=v=>state.data?.rubrics?.find(r=>r.slug===v)?.name||v;
const toneLabel=v=>({expert:"Експертний",sales:"Продаючий",light:"Легкий",news:"Новинний"}[v]||v);
const statusLabels={idea:"Ідея",suggested:"Ідея",selected:"У черзі",queued_text:"Очікує генерації тексту",text_batch:"Генерується текст",queued_image:"Очікує генерації зображення",image_batch:"Генерується зображення",review:"На перевірці",needs_changes:"Потрібні зміни",ready:"Готово",draft:"Чернетка",scheduled:"Заплановано",published:"Опубліковано",failed:"Помилка",completed:"Завершено",in_progress:"Виконується",cancelled:"Скасовано",expired:"Термін минув"};
const busyStatuses=new Set(["selected","queued_text","text_batch","queued_image","image_batch","in_progress"]);
const viewMeta={homeView:["Головна","Короткий огляд поточного workspace."],ideasView:["Ідеї","Зберігайте й перетворюйте ідеї на чернетки."],planningView:["Контент-план","Створюйте контент-плани, серії та матеріали на основі сайту."],draftsView:["Чернетки","Перевіряйте тексти, візуали та рух матеріалів."],calendarView:["Календар","Контролюйте ритм публікацій і майбутнє навантаження."],opsView:["Витрати","Слідкуйте за генераціями, Batch-завданнями і бюджетом."],companyView:["Бренд","Керуйте брендом, каналом, рубриками та режимом workspace."],usersView:["Налаштування","Керуйте користувачами, ролями та паролями."],platformView:["Платформа","Контролюйте компанії, використання AI та загальні ліміти."]};
const state={data:null,me:null,company:null,pricing:null,organizations:[],platformUsage:null,draftId:null,currentDraft:null,socialPlatform:null,socialVariants:[],referenceIds:new Set(),templateId:localStorage.getItem("templateId")||"editorial-dark",calendarDate:new Date(),ideaPage:1,draftPage:1,jobPage:1,pageSize:12,favoritesOnly:false,onboardingStep:1,routeDraftOpened:false}; const apiUrl=p=>{const u=new URL(p,location.href);u.username="";u.password="";return u};
function errorText(detail){if(typeof detail==="string")return detail;if(Array.isArray(detail))return detail.map(x=>x.msg||x.message||JSON.stringify(x)).join("; ");if(detail&&typeof detail==="object")return detail.message||detail.detail||JSON.stringify(detail);return "Невідома помилка"}
async function api(path,options={}){options.credentials="same-origin";options.headers={...(options.headers||{}),"X-Requested-With":"VoicerHubAdmin"};if(options.body&&!(options.body instanceof FormData))options.headers["Content-Type"]="application/json";const r=await fetch(apiUrl(path),options);if(!r.ok){let d={};try{d=await r.json()}catch{}const fallback={401:"Потрібно увійти знову",403:"Недостатньо прав",404:"Дані не знайдено",409:"Дію зараз неможливо виконати",422:"Перевірте введені дані",500:"Внутрішня помилка сервера"}[r.status]||`Помилка HTTP ${r.status}`;const detail=d.detail===undefined?fallback:errorText(d.detail);throw new Error(detail)}if(r.status===204)return {};return r.json()}
function toast(text,error=false){const n=document.querySelector("#notice");n.textContent=errorText(text);n.style.background=error?"#8f1d1d":"#111a2d";n.style.display="block";clearTimeout(n.timer);n.timer=setTimeout(()=>n.style.display="none",5000)}
async function loading(button,work,label="Виконується"){const old=button.innerHTML;button.disabled=true;button.innerHTML=`<span class="spinner"></span>${label}`;try{return await work()}catch(e){toast(e.message,true);return null}finally{button.disabled=false;button.innerHTML=old}}
const inferredLink=product=>state.data?.rubrics?.find(r=>r.slug===product)?.default_link||"";
const generationPayload=(product="",tone="")=>{const modal=document.querySelector("#editor");const inEditor=modal.open;return {text_model:document.querySelector("#textModel").value,image_model:document.querySelector("#imageModel").value,reference_ids:[...state.referenceIds],template_id:inEditor?document.querySelector("#editorTemplate").value:state.templateId,logo_reference_id:Number(inEditor?document.querySelector("#editorLogo").value:document.querySelector("#logoReference").value)||null,company_logo_reference_id:Number(inEditor?document.querySelector("#editorCompanyLogo").value:document.querySelector("#companyLogoReference").value)||null,link_url:(inEditor?document.querySelector("#editorLink").value:document.querySelector("#defaultLink").value)||inferredLink(product),tone:tone||document.querySelector("#ideaTone").value,generation_mode:document.querySelector("#generationMode").value}};
for(const id of ["textModel","imageModel","generationMode"]){const el=document.querySelector(`#${id}`);el.value=localStorage.getItem(id)||el.value;el.onchange=()=>localStorage.setItem(id,el.value)}
function setViewMeta(view){const meta=viewMeta[view]||[view,""];document.querySelector("#viewTitle").textContent=meta[0];document.querySelector("#viewSubtitle").textContent=meta[1]}
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab,.view").forEach(x=>x.classList.remove("active"));b.classList.add("active");document.querySelector(`#${b.dataset.view}`).classList.add("active");setViewMeta(b.dataset.view);renderActive(true)});
document.querySelectorAll("[data-home-view]").forEach(b=>b.onclick=()=>document.querySelector(`[data-view="${b.dataset.homeView}"]`).click());
function applyWorkspaceMode(){const mode=state.company?.settings?.workspace_mode||"pipeline";document.querySelector("#workspaceMode").value=mode;document.querySelectorAll(".tab[data-view]").forEach(tab=>{const hidden=mode==="kanban"&&tab.dataset.kanbanHidden==="true";tab.hidden=hidden||tab.id==="platformTab"&&!state.me?.is_super_admin;if(mode==="kanban"&&tab.dataset.kanbanLabel)tab.textContent=tab.dataset.kanbanLabel;if(mode==="pipeline"&&tab.dataset.pipelineLabel)tab.textContent=tab.dataset.pipelineLabel});if(document.querySelector(".tab.active")?.hidden)document.querySelector('[data-view="draftsView"]').click()}
function applyRoleAccess(){if(state.me?.role!=="viewer")return;for(const id of ["generateIdeas","generateSelected","generatePlan","generateSeries","importMaterial","showCustomTemplate","referenceUpload","saveWorkspaceMode","restartOnboarding","saveTelegram","showRubricForm","createUser","saveDraft","regenImage","regenText","favoriteDraft","publishNow","scheduleDraft","cancelSchedule"])document.querySelector(`#${id}`)?.setAttribute("hidden","");document.querySelectorAll("[data-social-generate]").forEach(button=>button.hidden=true)}
const paginate=(items,page,size)=>items.slice((page-1)*size,page*size);
function pagination(id,total,page,setter){const pages=Math.max(1,Math.ceil(total/state.pageSize));page=Math.min(page,pages);document.querySelector(`#${id}`).innerHTML=total>state.pageSize?`<button data-page-prev ${page<=1?"disabled":""}>←</button><span>Сторінка ${page} з ${pages}</span><button data-page-next ${page>=pages?"disabled":""}>→</button>`:"";document.querySelector(`#${id} [data-page-prev]`)?.addEventListener("click",()=>setter(page-1));document.querySelector(`#${id} [data-page-next]`)?.addEventListener("click",()=>setter(page+1))}
function renderIdeas(ideas){const page=paginate(ideas,state.ideaPage,state.pageSize);const writable=state.me?.role!=="viewer";document.querySelector("#ideas").innerHTML=page.length?page.map(i=>{const busy=busyStatuses.has(i.status);const available=["idea","suggested"].includes(i.status);const done=["ready","draft","review","needs_changes","scheduled","published"].includes(i.status);const duplicate=Number(i.duplicate_score||0)>=.62;return `<div class="idea"><input class="ideaCheck" type="checkbox" value="${i.id}" ${!available||!writable?"disabled":""}><span class="badge">${esc(rubricLabel(i.product))}</span><div><strong>${esc(i.series_part?`${i.series_part}/${i.series_title} · ${i.title}`:i.title)}</strong><p>${esc(i.angle)}</p><div class="idea-meta"><span class="meta-chip">${esc(toneLabel(i.tone))}</span>${i.planned_for?`<span class="meta-chip">${esc(new Date(`${i.planned_for}T12:00:00`).toLocaleDateString("uk-UA"))}</span>`:""}${i.source_url?`<span class="meta-chip">Матеріал із сайту</span>`:""}${duplicate?`<span class="meta-chip warn">Схожість ${Math.round(i.duplicate_score*100)}%</span>`:""}</div><span class="status ${esc(i.status)} ${busy?"busy":""}">${esc(statusLabels[i.status]||i.status)}</span></div><div class="editor-actions">${done&&i.draft_id?`<button data-open-idea="${i.draft_id}">Відкрити пост</button>`:writable?`<button data-idea="${i.id}" ${available?"":"disabled"}>${available?"Створити чернетку":esc(statusLabels[i.status]||i.status)}</button>`:""}${writable?`<button class="danger" data-delete-idea="${i.id}" title="Видалити тему">✕</button>`:""}</div></div>`}).join(""):`<div class="empty">Тут поки порожньо. Створіть перші ідеї або контент-план.</div>`;pagination("ideasPagination",ideas.length,state.ideaPage,p=>{state.ideaPage=p;renderIdeas(ideas)});document.querySelectorAll("[data-idea]").forEach(b=>b.onclick=()=>generateIdea(Number(b.dataset.idea)));document.querySelectorAll("[data-open-idea]").forEach(b=>b.onclick=()=>openDraft(b.dataset.openIdea));document.querySelectorAll("[data-delete-idea]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цю тему зі списку?"))return;try{await api(`api/ideas/${b.dataset.deleteIdea}`,{method:"DELETE"});await refresh()}catch(e){toast(e.message,true)}})}
function renderTemplates(templates){document.querySelector("#templates").innerHTML=templates.map(t=>`<article class="template ${t.id===state.templateId?"selected":""}" data-template="${esc(t.id)}">${t.has_preview?`<img src="api/templates/${esc(t.id)}/preview?v=2" alt="${esc(t.name)}">`:`<div class="empty">Прев’ю ще немає</div>`}<span class="template-copy"><strong>${esc(t.name)}</strong><span>${esc(t.description)}</span></span>${t.custom?`<span class="template-actions">${!t.has_preview?`<button data-preview-template="${esc(t.id)}">Створити прев’ю</button>`:""}<button class="danger" data-delete-template="${esc(t.id)}">Видалити</button></span>`:""}</article>`).join("");const editorSelect=document.querySelector("#editorTemplate");const current=editorSelect.value;editorSelect.innerHTML=templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");editorSelect.value=templates.some(t=>t.id===current)?current:state.templateId;document.querySelectorAll("[data-template]").forEach(card=>card.onclick=e=>{if(e.target.closest("[data-preview-template],[data-delete-template]"))return;state.templateId=card.dataset.template;localStorage.setItem("templateId",state.templateId);renderTemplates(templates)});document.querySelectorAll("[data-preview-template]").forEach(b=>b.onclick=()=>loading(b,async()=>{await api(`api/templates/${b.dataset.previewTemplate}/generate-preview`,{method:"POST"});await refresh()},"Генерується"));document.querySelectorAll("[data-delete-template]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цей шаблон?"))return;try{await api(`api/templates/${b.dataset.deleteTemplate}`,{method:"DELETE"});if(state.templateId===b.dataset.deleteTemplate)state.templateId="editorial-dark";await refresh()}catch(e){toast(e.message,true)}})}
function renderLogoOptions(assets){for(const id of ["logoReference","editorLogo","companyLogoReference","editorCompanyLogo"]){const select=document.querySelector(`#${id}`);const current=select.value;const company=id.toLowerCase().includes("company");select.innerHTML=`<option value="">${company?"Без логотипа компанії":"Без логотипа продукту"}</option>`+assets.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join("");if(assets.some(a=>String(a.id)===current))select.value=current}}
function renderAssets(assets){const valid=new Set(assets.map(a=>a.id));for(const id of state.referenceIds)if(!valid.has(id))state.referenceIds.delete(id);document.querySelector("#assets").innerHTML=assets.length?assets.map(a=>`<article class="asset ${state.referenceIds.has(a.id)?"selected":""}" data-asset="${a.id}"><img src="api/references/${a.id}/image" alt="${esc(a.name)}"><div class="asset-info"><input type="checkbox" ${state.referenceIds.has(a.id)?"checked":""}><span title="${esc(a.name)}">${esc(a.name)}</span><button class="asset-delete" data-delete-asset="${a.id}" title="Видалити">✕</button></div></article>`).join(""):`<div class="empty">Додайте логотипи продуктів, скриншоти або приклади стилю</div>`;document.querySelectorAll("[data-asset]").forEach(card=>card.onclick=e=>{if(e.target.closest("[data-delete-asset]"))return;const id=Number(card.dataset.asset);if(state.referenceIds.has(id))state.referenceIds.delete(id);else if(state.referenceIds.size>=16)return toast("Можна обрати не більше 16 матеріалів");else state.referenceIds.add(id);renderAssets(state.data.references)});document.querySelectorAll("[data-delete-asset]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цей бренд-матеріал?"))return;await api(`api/references/${b.dataset.deleteAsset}`,{method:"DELETE"});state.referenceIds.delete(Number(b.dataset.deleteAsset));refresh()})}
const draftTransitions={draft:["review","ready"],review:["needs_changes","ready"],needs_changes:["draft"],ready:["draft"],scheduled:["ready"],published:[]};
async function changeDraftStatus(id,status){try{await api(`api/drafts/${id}/status`,{method:"POST",body:JSON.stringify({status})});toast(`Статус: ${statusLabels[status]}`);await refresh()}catch(e){toast(e.message,true)}}
function statusActions(d){if(state.me?.role==="viewer")return "";return (draftTransitions[d.status]||[]).map(status=>`<button data-status-draft="${d.id}" data-status="${status}">${esc(statusLabels[status])}</button>`).join("")}
function renderDrafts(drafts){const filtered=state.favoritesOnly?drafts.filter(d=>d.is_favorite):drafts;const kanban=state.company?.settings?.workspace_mode==="kanban";const container=document.querySelector("#drafts");container.className=kanban?"kanban":"drafts";if(kanban){const columns=["draft","review","needs_changes","ready","scheduled"];container.innerHTML=columns.map(status=>{const items=filtered.filter(d=>d.status===status);return `<section class="kanban-column"><h3>${esc(statusLabels[status])} · ${items.length}</h3>${items.map(d=>`<article class="kanban-card" data-draft-card="${d.id}"><span class="badge">${esc(rubricLabel(d.product))}</span><h4>${esc(d.title)}</h4><p>${esc(d.caption_html.replace(/<[^>]+>/g,""))}</p><div class="editor-actions"><button data-draft="${d.id}">Відкрити</button>${statusActions(d)}</div></article>`).join("")||`<div class="empty">Немає матеріалів</div>`}</section>`}).join("");document.querySelector("#draftsPagination").innerHTML=""}else{const page=paginate(filtered,state.draftPage,state.pageSize);container.innerHTML=page.length?page.map(d=>`<article class="draft" data-draft-card="${d.id}">${d.image_path?`<img src="api/drafts/${d.id}/image" alt="">`:`<div class="empty"><span class="spinner"></span>Зображення генерується</div>`}<div class="draft-body"><div class="draft-meta"><span class="badge">${esc(rubricLabel(d.product))}${d.is_favorite?" · ★":""}</span><span class="status ${esc(d.status)}">${esc(statusLabels[d.status]||d.status)}</span></div><h3>${esc(d.title)}</h3><p>${esc(d.caption_html.replace(/<[^>]+>/g,""))}</p><div class="editor-actions"><button data-draft="${d.id}">Відкрити редактор</button>${statusActions(d)}</div></div></article>`).join(""):`<div class="empty">${state.favoritesOnly?"Вдалих прикладів ще немає":"Чернеток ще немає. Створіть їх з бібліотеки ідей."}</div>`;pagination("draftsPagination",filtered.length,state.draftPage,p=>{state.draftPage=p;renderDrafts(drafts)})}document.querySelectorAll("[data-draft]").forEach(b=>b.onclick=()=>openDraft(b.dataset.draft));document.querySelectorAll("[data-status-draft]").forEach(b=>b.onclick=()=>changeDraftStatus(b.dataset.statusDraft,b.dataset.status))}
function updateDraftStatuses(drafts){for(const d of drafts){const card=document.querySelector(`[data-draft-card="${d.id}"]`);if(card){const el=card.querySelector(".status");el.className=`status ${d.status}`;el.textContent=statusLabels[d.status]||d.status}}}
function renderUsers(users){document.querySelector("#users").innerHTML=users.map(u=>`<tr><td><strong>${esc(u.username)}</strong></td><td>${u.is_admin?"Адміністратор":"Редактор"}</td><td class="status ${u.active?"ready":"failed"}">${u.active?"Активний":"Заблокований"}</td><td>${esc(new Date(`${u.created_at}Z`).toLocaleDateString("uk-UA"))}</td><td><div class="user-actions"><button data-role-user="${u.id}">${u.is_admin?"Зробити редактором":"Зробити адміністратором"}</button><button data-active-user="${u.id}" class="${u.active?"danger":""}">${u.active?"Заблокувати":"Активувати"}</button><button data-password-user="${u.id}">Новий пароль</button></div></td></tr>`).join("");document.querySelectorAll("[data-role-user]").forEach(b=>b.onclick=async()=>{const u=users.find(x=>x.id===Number(b.dataset.roleUser));await api(`api/users/${u.id}`,{method:"PATCH",body:JSON.stringify({is_admin:!u.is_admin})});refreshUsers()});document.querySelectorAll("[data-active-user]").forEach(b=>b.onclick=async()=>{const u=users.find(x=>x.id===Number(b.dataset.activeUser));await api(`api/users/${u.id}`,{method:"PATCH",body:JSON.stringify({active:!u.active})});refreshUsers()});document.querySelectorAll("[data-password-user]").forEach(b=>b.onclick=async()=>{const password=prompt("Новий пароль, мінімум 10 символів");if(!password)return;await api(`api/users/${b.dataset.passwordUser}/password`,{method:"PUT",body:JSON.stringify({password})});toast("Пароль змінено")})}
function renderCompany(company){state.company=company;document.querySelector("#currentCompany").textContent=company.name;document.querySelector("#sidebarCompany").textContent=company.name;document.querySelector("#companyCards").innerHTML=`<div class="company-card"><span>Компанія</span><strong>${esc(company.name)}</strong></div><div class="company-card"><span>Користувачі</span><strong>${company.user_count} / ${company.max_users}</strong></div><div class="company-card"><span>Telegram-канали</span><strong>${company.telegram?.configured?"1 підключено":`0 / ${company.max_channels}`}</strong></div><div class="company-card"><span>Публікації цього місяця</span><strong>${company.publication_count} / ${company.monthly_publications}</strong></div><div class="company-card"><span>Текстові генерації</span><strong>\${company.text_generation_count || 0} / \${company.monthly_text_generations || 0}</strong></div><div class="company-card"><span>Зображення</span><strong>\${company.image_generation_count || 0} / \${company.monthly_image_generations || 0}</strong></div>`;document.querySelector("#companyChannel").value=company.telegram?.channel_id||"";applyWorkspaceMode()}
function renderPricing(data){state.pricing=data;const expires=data.expires_at?new Date(data.expires_at).toLocaleDateString("uk-UA"):"";document.querySelector("#pricingGrid").innerHTML=data.plans.map(plan=>{const current=data.current_plan===plan.code;return `<article class="price-card ${plan.popular?"popular":""}">${plan.popular?`<span class="popular-label">Найпопулярніший</span>`:""}<h3>${esc(plan.name)}</h3><p class="tagline">${esc(plan.tagline)}</p><div class="price"><strong>${number(plan.stars)} ★</strong><span>/ 30 днів</span></div><div class="plan-limits"><div class="plan-limit"><strong>${number(plan.publications)}</strong><span>публікацій / місяць</span></div><div class="plan-limit"><strong>${number(plan.users)}</strong><span>користувачів</span></div><div class="plan-limit"><strong>${number(plan.channels)}</strong><span>Telegram-канал</span></div><div class="plan-limit"><strong>\${number(plan.text_generations || 0)}</strong><span>текстів / місяць</span></div><div class="plan-limit"><strong>\${number(plan.image_generations || 0)}</strong><span>зображень / місяць</span></div></div><ul class="plan-features">${plan.features.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>${current?`<button disabled class="current-plan">Поточний тариф${expires?` · до ${expires}`:""}</button>`:`<button class="${plan.popular?"success":"primary"}" data-buy-plan="${esc(plan.code)}" ${state.me?.is_admin?"":"disabled"}>${state.me?.is_admin?"Оплатити в Telegram":"Доступно адміністратору"}</button>`}</article>`}).join("");document.querySelectorAll("[data-buy-plan]").forEach(button=>button.onclick=()=>buyPlan(button,button.dataset.buyPlan))}
async function buyPlan(button,planCode){const popup=window.open("about:blank","_blank");const result=await loading(button,()=>api("api/billing/checkout",{method:"POST",body:JSON.stringify({plan_code:planCode})}),"Створюється рахунок");if(!result){popup?.close();return}if(popup)popup.location=result.invoice_url;else location.href=result.invoice_url;toast("Рахунок відкрито в Telegram")}
function renderRubrics(items){const active=items.filter(r=>r.active);document.querySelector("#rubrics").innerHTML=items.map(r=>`<tr><td><strong>${esc(r.name)}</strong></td><td class="masked">${esc(r.slug)}</td><td>${esc(r.description.slice(0,160))}</td><td>${r.default_link?`<a href="${esc(r.default_link)}" target="_blank">Відкрити</a>`:"—"}</td><td class="status ${r.active?"ready":"failed"}">${r.active?"Активна":"Вимкнена"}</td><td><button data-toggle-rubric="${r.id}">${r.active?"Вимкнути":"Увімкнути"}</button></td></tr>`).join("")||`<tr><td colspan="6" class="empty">Створіть першу рубрику компанії</td></tr>`;const options=active.map(r=>`<option value="${esc(r.slug)}">${esc(r.name)}</option>`).join("");for(const id of ["ideaProduct","planProduct","materialProduct"]){const select=document.querySelector(`#${id}`),current=select.value;select.innerHTML=`<option value="all">Усі рубрики</option>${options}`;if([...select.options].some(o=>o.value===current))select.value=current}const series=document.querySelector("#seriesProduct"),seriesCurrent=series.value;series.innerHTML=options;if([...series.options].some(o=>o.value===seriesCurrent))series.value=seriesCurrent;syncRubricControls();document.querySelectorAll("[data-toggle-rubric]").forEach(b=>b.onclick=async()=>{const r=items.find(x=>x.id===Number(b.dataset.toggleRubric));await api(`api/rubrics/${r.id}`,{method:"PUT",body:JSON.stringify({name:r.name,description:r.description,instructions:r.instructions,default_link:r.default_link,active:!r.active})});await refresh()})}
function renderOrganizations(items){state.organizations=items;document.querySelector("#organizations").innerHTML=items.map(o=>`<tr><td>${o.id}</td><td><strong>${esc(o.name)}</strong></td><td class="masked">${esc(o.slug)}</td><td>${o.monthly_publications} публікацій<br>$${Number(o.monthly_ai_budget).toFixed(0)} AI</td><td>${o.user_count} / ${o.max_users}</td><td class="status ${o.active?"ready":"failed"}">${o.active?"Активна":"Заблокована"}</td></tr>`).join("")}
const number=value=>Number(value||0).toLocaleString("uk-UA");
function renderPlatformUsage(report){state.platformUsage=report;const t=report.totals;document.querySelector("#platformUsageTotals").innerHTML=`<div class="metric"><span>Витрати</span><strong>${money(t.cost)}</strong></div><div class="metric"><span>Текстові генерації</span><strong>${number(t.text_generations)}</strong></div><div class="metric"><span>Зображення</span><strong>${number(t.image_generations)}</strong></div><div class="metric"><span>Токени</span><strong>${number(t.input_tokens+t.output_tokens)}</strong></div>`;document.querySelector("#companyUsage").innerHTML=report.companies.map(r=>`<tr><td><strong>${esc(r.organization_name)}</strong></td><td>${number(r.text_generations)}</td><td>${number(r.image_generations)}</td><td>${number(r.input_tokens)}</td><td>${number(r.output_tokens)}</td><td>${money(r.cost)}</td></tr>`).join("")||`<tr><td colspan="6" class="empty">Немає використання за цей період</td></tr>`;document.querySelector("#userUsage").innerHTML=report.users.map(r=>`<tr><td>${esc(r.organization_name)}</td><td><strong>${esc(r.username)}</strong></td><td>${number(r.text_generations)}</td><td>${number(r.image_generations)}</td><td>${number(r.input_tokens+r.output_tokens)}</td><td>${money(r.cost)}</td></tr>`).join("")||`<tr><td colspan="6" class="empty">Немає використання за цей період</td></tr>`;document.querySelector("#modelUsage").innerHTML=report.models.map(r=>`<tr><td>${esc(r.organization_name)}</td><td>${r.kind==="text"?"Текст":"Зображення"}</td><td class="masked">${esc(r.model)}</td><td>${number(r.operations)}</td><td>${r.kind==="text"?`${number(r.input_tokens)} / ${number(r.output_tokens)}`:number(r.units)}</td><td>${money(r.cost)}</td></tr>`).join("")||`<tr><td colspan="6" class="empty">Немає використання за цей період</td></tr>`}
const elapsedInfo=raw=>{if(!raw)return {text:"—",hours:0,cls:""};const hours=Math.max(0,(Date.now()-parseServerDate(raw).getTime())/3600000);const mins=Math.floor(hours*60);const text=mins<60?`${mins} хв`:`${Math.floor(mins/60)} год ${mins%60} хв`;return {text,hours,cls:hours>=12?"wait-danger":hours>=2?"wait-warning":""}};
function renderOps(d){document.querySelector("#total").textContent=money(d.totals.total_cost);document.querySelector("#text").textContent=money(d.totals.text_cost);document.querySelector("#image").textContent=money(d.totals.image_cost);const terminal=new Set(["ready","published","failed","cancelled"]);document.querySelector("#active").textContent=Object.entries(d.job_counts).filter(([k])=>!terminal.has(k)).reduce((s,[,v])=>s+v,0);document.querySelector("#jobs").innerHTML=d.jobs.map(r=>{const wait=elapsedInfo(r.updated_at||r.created_at);const batchActive=["text_batch","image_batch"].includes(r.status);return `<tr><td>${r.id}</td><td>${esc(rubricLabel(r.product))}</td><td>${esc(r.topic)}</td><td>${r.generation_mode==="fast"?"Швидко":"Економно"}<br>${esc(r.text_model||"—")}<br>${esc(r.image_model||"—")}</td><td class="status ${esc(r.status)} ${busyStatuses.has(r.status)?"busy":""}">${esc(statusLabels[r.status]||r.status)}</td><td class="${batchActive?wait.cls:""}">${busyStatuses.has(r.status)?wait.text:"—"}</td><td>${esc(short(r.text_batch_id||r.image_batch_id))}</td><td>${esc(r.error||"—")}</td><td>${batchActive?`<button data-retry-fast="${r.id}">Скасувати й швидко</button>`:"—"}</td></tr>`}).join("");document.querySelector("#batches").innerHTML=d.batches.map(r=>{const wait=elapsedInfo(r.created_at);return `<tr><td>${esc(short(r.id))}</td><td>${r.kind==="text"?"Текст":"Зображення"}</td><td class="status ${esc(r.status)} ${r.status==="in_progress"?"busy":""}">${esc(statusLabels[r.status]||r.status)}</td><td class="${r.status==="in_progress"?wait.cls:""}">${r.status==="in_progress"?wait.text:"—"}</td><td>${r.completed}/${r.total}</td><td>${r.failed}</td><td>${r.input_tokens}/${r.output_tokens}</td><td>${money(r.estimated_cost)}</td></tr>`}).join("");document.querySelectorAll("[data-retry-fast]").forEach(b=>b.onclick=()=>{if(!confirm("Скасувати Batch і запустити нову швидку генерацію? Завершені OpenAI-запити можуть бути тарифіковані."))return;loading(b,async()=>{const result=await api(`api/jobs/${b.dataset.retryFast}/retry-fast`,{method:"POST"});toast(result.job_id?"Batch скасовано. Швидку генерацію запущено.":result.message||"Batch уже завершено.");await refresh()},"Запускається")})}
const localKey=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
const parseServerDate=raw=>new Date(raw.endsWith("Z")?raw:`${raw.replace(" ","T")}Z`);
function renderCalendar(){if(!state.data)return;const month=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth(),1);document.querySelector("#calendarTitle").textContent=month.toLocaleDateString("uk-UA",{month:"long",year:"numeric"});const monday=(month.getDay()+6)%7;const start=new Date(month);start.setDate(1-monday);const items=(state.data.drafts||[]).filter(d=>d.scheduled_at||d.published_at).map(d=>({...d,eventDate:parseServerDate(d.scheduled_at||d.published_at),kind:"draft"}));items.push(...(state.data.ideas||[]).filter(i=>i.planned_for&&!i.draft_id).map(i=>({...i,eventDate:new Date(`${i.planned_for}T12:00:00`),kind:"idea"})));let html=["Пн","Вт","Ср","Чт","Пт","Сб","Нд"].map(x=>`<div class="weekday">${x}</div>`).join("");for(let i=0;i<42;i++){const date=new Date(start);date.setDate(start.getDate()+i);const key=localKey(date);const dayItems=items.filter(d=>localKey(d.eventDate)===key);html+=`<div class="day ${date.getMonth()===month.getMonth()?"":"outside"} ${key===localKey(new Date())?"today":""}"><div class="day-number">${date.getDate()}</div>${dayItems.map(d=>d.kind==="idea"?`<button class="calendar-item planned" data-calendar-idea="${d.id}"><time>Контент-план · ${esc(toneLabel(d.tone))}</time><span class="cal-product">${esc(rubricLabel(d.product))}</span>${esc(d.title)}<small>${d.series_part?`Серія ${d.series_part}`:"Тема очікує генерації"}</small></button>`:`<button class="calendar-item ${d.status==="published"?"published":""}" data-calendar-draft="${d.id}"><time>${d.eventDate.toLocaleTimeString("uk-UA",{hour:"2-digit",minute:"2-digit"})} · ${esc(statusLabels[d.status]||d.status)}</time><span class="cal-product">${esc(rubricLabel(d.product))}</span>${esc(d.title)}<small>${d.link_url?"Є посилання":"Без посилання"}</small></button>`).join("")}</div>`}document.querySelector("#calendar").innerHTML=html;document.querySelectorAll("[data-calendar-draft]").forEach(b=>b.onclick=()=>openDraft(b.dataset.calendarDraft));document.querySelectorAll("[data-calendar-idea]").forEach(b=>b.onclick=()=>{document.querySelector('[data-view="ideasView"]').click();const idea=state.data.ideas.find(i=>i.id===Number(b.dataset.calendarIdea));if(idea)toast(`Тема: ${idea.title}`)})}
async function refreshUsers(){if(!state.me?.is_admin)return;try{renderUsers(await api("api/users"))}catch(e){toast(e.message)}}
async function refreshCompany(){try{renderCompany(await api("api/company"))}catch(e){toast(e.message,true)}}
async function refreshOrganizations(){if(!state.me?.is_super_admin)return;try{renderOrganizations(await api("api/organizations"))}catch(e){toast(e.message,true)}}
async function refreshPlatformUsage(){if(!state.me?.is_super_admin)return;try{renderPlatformUsage(await api(`api/platform/usage?period=${document.querySelector("#usagePeriod").value}`))}catch(e){toast(e.message,true)}}
function activeView(){return document.querySelector(".view.active")?.id}
function renderHome(){const ideas=state.data?.ideas||[],drafts=state.data?.drafts||[];document.querySelector("#homeIdeas").textContent=ideas.filter(i=>["idea","suggested"].includes(i.status)).length;document.querySelector("#homeDrafts").textContent=drafts.filter(d=>["draft","review","needs_changes","ready"].includes(d.status)).length;document.querySelector("#homeScheduled").textContent=drafts.filter(d=>d.status==="scheduled").length}
function renderActive(full=false){if(!state.data)return;renderRubrics(state.data.rubrics||[]);renderHome();const view=activeView();if(view==="ideasView"){renderIdeas(state.data.ideas);if(full){renderTemplates(state.data.templates||[]);renderLogoOptions(state.data.references||[]);renderAssets(state.data.references||[])}}else if(view==="draftsView"){if(full||state.company?.settings?.workspace_mode==="kanban")renderDrafts(state.data.drafts);else updateDraftStatuses(state.data.drafts)}else if(view==="calendarView")renderCalendar();else if(view==="opsView")renderOps(state.data);else if(view==="companyView"&&state.company)renderCompany(state.company);else if(view==="platformView"){renderOrganizations(state.organizations);if(state.platformUsage)renderPlatformUsage(state.platformUsage)}}
function renderWorkspaceSelector(){const select=document.querySelector("#workspaceSelect");const rows=state.me?.workspaces||[];select.hidden=rows.length<2&&!state.me?.is_super_admin;select.innerHTML=rows.map(x=>`<option value="${x.id}" ${Number(state.me.organization_id)===Number(x.id)?"selected":""}>Workspace: ${esc(x.name)}</option>`).join("")}
function onboardingMarkup(step){const settings=state.company?.settings||{};const company=state.company||{};const rubrics=state.data?.rubrics||[];const titles=["Компанія","Бренд","Telegram","Рубрики","Перший контент-план"];document.querySelector("#onboardingSubtitle").textContent=`Крок ${step} з 5 · ${titles[step-1]}`;document.querySelector("#onboardingProgress").innerHTML=[1,2,3,4,5].map(x=>`<span class="${x<=step?"active":""}"></span>`).join("");document.querySelector("#onboardingBack").disabled=step===1;document.querySelector("#onboardingNext").textContent=step===5?"Завершити":"Продовжити";if(step===1)return `<div class="onboarding-fields"><label>Назва компанії<input id="obName" value="${esc(company.name||"")}"></label><label>Slug<input id="obSlug" value="${esc(company.slug||"workspace")}"></label><label>Мова<select id="obLanguage"><option value="uk">Українська</option><option value="en">English</option></select></label><label>Основний колір<input id="obColor" type="color" value="${esc(settings.brand_primary_color||"#10bfae")}"></label></div>`;if(step===2)return `<div class="onboarding-fields"><label class="wide">Опис компанії<textarea id="obDescription">${esc(settings.company_description||"")}</textarea></label><label class="wide">Tone of voice<textarea id="obTone">${esc(settings.tone_of_voice||"")}</textarea></label><label>Ключові послуги<textarea id="obServices">${esc(settings.key_services||"")}</textarea></label><label>Заборонені фрази<textarea id="obForbidden">${esc(settings.forbidden_phrases||"")}</textarea></label><label class="wide">Сайт<input id="obWebsite" type="url" value="${esc(settings.website_url||"")}"></label></div>`;if(step===3)return `<div class="onboarding-fields"><label class="wide">Канал або ID<input id="obChannel" value="${esc(company.telegram?.channel_id||"")}" placeholder="@company_channel"></label><label class="wide">Токен бота<input id="obToken" type="password" placeholder="Можна пропустити цей крок"></label></div>`;if(step===4)return `<div class="onboarding-fields"><label class="wide">Початкові рубрики, по одній у рядку<textarea id="obRubrics" placeholder="Експертні матеріали&#10;Кейси клієнтів&#10;Новини компанії">${rubrics.map(r=>r.name).join("\n")}</textarea></label></div>`;return `<div class="onboarding-fields"><label>Період<select id="obPeriod"><option value="week">Тиждень</option><option value="month">Місяць</option></select></label><label>Кількість постів<input id="obPosts" type="number" min="1" max="31" value="5"></label><label>Створити як<select id="obCreateAs"><option value="ideas">Ідеї</option><option value="drafts">Чернетки в черзі</option></select></label><label class="wide">Мета плану<textarea id="obFocus" placeholder="Що має дати цей контент-план"></textarea></label></div>`}
function showOnboarding(step=1){state.onboardingStep=Math.max(1,Math.min(5,step));document.querySelector("#onboardingContent").innerHTML=onboardingMarkup(state.onboardingStep);const modal=document.querySelector("#onboarding");if(!modal.open)modal.showModal()}
async function saveOnboardingStep(){const step=state.onboardingStep;if(step===1){await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:document.querySelector("#obName").value,slug:document.querySelector("#obSlug").value,primary_language:document.querySelector("#obLanguage").value,brand_primary_color:document.querySelector("#obColor").value,brand_logo_asset_id:null})})}else if(step===2){await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#obDescription").value,tone_of_voice:document.querySelector("#obTone").value,key_services:document.querySelector("#obServices").value,forbidden_phrases:document.querySelector("#obForbidden").value,website_url:document.querySelector("#obWebsite").value})})}else if(step===3){const token=document.querySelector("#obToken").value;if(token)await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#obChannel").value,bot_token:token})})}else if(step===4){const rubrics=document.querySelector("#obRubrics").value.split("\n").map(name=>name.trim()).filter(Boolean).map(name=>({name,description:`Матеріали та публікації для рубрики «${name}».`}));if(rubrics.length)await api("api/onboarding/rubrics",{method:"POST",body:JSON.stringify({rubrics})})}else{await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({period:document.querySelector("#obPeriod").value,start_date:new Date().toISOString().slice(0,10),posts:Number(document.querySelector("#obPosts").value),product:"all",focus:document.querySelector("#obFocus").value,text_model:document.querySelector("#textModel").value,create_as:document.querySelector("#obCreateAs").value,rubric_slugs:[],channel_ids:[]})});await api("api/onboarding/complete",{method:"POST"});document.querySelector("#onboarding").close();state.company=null;await refreshCompany();await refresh();return}state.onboardingStep++;showOnboarding(state.onboardingStep)}
async function refresh(background=false){try{if(!state.me){state.me=await api("api/me");document.querySelector("#currentUser").textContent=state.me.username;renderWorkspaceSelector();applyRoleAccess();if(state.me.is_admin){document.querySelector("#userAdmin").hidden=false;await refreshUsers()}if(state.me.is_super_admin){document.querySelector("#platformTab").hidden=false;await refreshOrganizations();await refreshPlatformUsage()}await refreshCompany()}const d=await api("api/dashboard");state.data=d;renderActive(!background);document.querySelector("#updated").textContent=new Date().toLocaleTimeString("uk-UA");const settings=state.company?.settings;if(!background&&state.me?.is_admin&&settings&&!["completed","skipped"].includes(settings.onboarding_status))showOnboarding(Math.max(1,Number(settings.onboarding_step||0)+1));if(!state.routeDraftOpened){const parts=location.pathname.split("/").filter(Boolean);if(parts.length===4&&parts[0]==="workspace"&&parts[2]==="drafts"&&Number(parts[3])){state.routeDraftOpened=true;await openDraft(parts[3],false)}}}catch(e){if(e.message.includes("увійти"))location.reload();else if(!background)toast(e.message,true)}}
async function generateIdea(id){const idea=state.data.ideas.find(i=>i.id===id);const button=document.querySelector(`[data-idea="${id}"]`);await loading(button,async()=>{await api(`api/ideas/${id}/generate`,{method:"POST",body:JSON.stringify(generationPayload(idea?.product,idea?.tone))});toast("Пост поставлено в чергу генерації");await refresh()},"Додається")}
function syncRubricControls(){const rubric=state.data?.rubrics?.find(r=>r.slug===document.querySelector("#ideaProduct").value);const fixed=!!rubric?.fixed_cover_path;document.querySelectorAll(".image-setting:not(#customTemplateForm)").forEach(el=>el.hidden=fixed);if(fixed)document.querySelector("#customTemplateForm").hidden=true;document.querySelector("#waveCoverNotice").hidden=!fixed}
document.querySelector("#ideaProduct").onchange=syncRubricControls;
document.querySelector("#generateIdeas").onclick=async()=>{const b=document.querySelector("#generateIdeas");await loading(b,async()=>{await api("api/ideas/generate",{method:"POST",body:JSON.stringify({product:document.querySelector("#ideaProduct").value,count:Number(document.querySelector("#ideaCount").value),focus:document.querySelector("#ideaFocus").value,text_model:document.querySelector("#textModel").value,tone:document.querySelector("#ideaTone").value})});state.ideaPage=1;toast("Нові теми готові");await refresh()},"Генерується")};
document.querySelector("#planStart").value=new Date().toISOString().slice(0,10);
document.querySelector("#generatePlan").onclick=async()=>{const b=document.querySelector("#generatePlan");await loading(b,async()=>{await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({period:document.querySelector("#planPeriod").value,start_date:document.querySelector("#planStart").value,posts:Number(document.querySelector("#planPosts").value),product:document.querySelector("#planProduct").value,focus:document.querySelector("#planFocus").value,text_model:document.querySelector("#textModel").value})});toast("Контент-план додано до тем");await refresh();document.querySelector('[data-view="ideasView"]').click()},"Планується")};
document.querySelector("#generateSeries").onclick=async()=>{const b=document.querySelector("#generateSeries");await loading(b,async()=>{await api("api/series/generate",{method:"POST",body:JSON.stringify({product:document.querySelector("#seriesProduct").value,parts:Number(document.querySelector("#seriesParts").value),topic:document.querySelector("#seriesTopic").value,tone:document.querySelector("#seriesTone").value,text_model:document.querySelector("#textModel").value})});toast("Серію додано до тем");await refresh();document.querySelector('[data-view="ideasView"]').click()},"Створюється")};
document.querySelector("#importMaterial").onclick=async()=>{const b=document.querySelector("#importMaterial");await loading(b,async()=>{await api("api/materials/import",{method:"POST",body:JSON.stringify({url:document.querySelector("#materialUrl").value,text:document.querySelector("#materialText").value,product:document.querySelector("#materialProduct").value,count:Number(document.querySelector("#materialCount").value),tone:document.querySelector("#materialTone").value,text_model:document.querySelector("#textModel").value})});toast("Матеріал перетворено на теми");await refresh();document.querySelector('[data-view="ideasView"]').click()},"Читається")};
document.querySelector("#referenceUpload").onchange=async e=>{const files=[...e.target.files];if(!files.length)return;try{for(const file of files){const form=new FormData();form.append("file",file);await api("api/references",{method:"POST",body:form})}toast(`Додано матеріалів: ${files.length}`);await refresh()}catch(err){toast(err.message)}finally{e.target.value=""}};
document.querySelector("#toggleFavorites").onclick=()=>{state.favoritesOnly=!state.favoritesOnly;state.draftPage=1;document.querySelector("#toggleFavorites").textContent=state.favoritesOnly?"← Усі чернетки":"☆ Показати вдалі приклади";renderDrafts(state.data.drafts)};
document.querySelector("#generateSelected").onclick=async()=>{const ids=[...document.querySelectorAll(".ideaCheck:checked")].map(x=>x.value);for(const id of ids)await generateIdea(id);if(!ids.length)toast("Оберіть хоча б одну тему")};
const jsonList=value=>{try{return JSON.parse(value||"[]")}catch{return[]}};
function showSocialVariant(v){state.socialPlatform=v.platform;document.querySelector("#socialVariant").hidden=false;document.querySelector("#socialPlatform").textContent=({instagram:"Instagram",linkedin:"LinkedIn",facebook:"Facebook",x:"X"}[v.platform]||v.platform);document.querySelector("#socialTitle").value=v.title;document.querySelector("#socialVisualTitle").value=v.visual_title||stripEmoji(v.title);document.querySelector("#socialText").value=v.text_content;document.querySelector("#socialImage").src=`api/drafts/${state.draftId}/social-variants/${v.platform}/image?v=${Date.now()}`;document.querySelector("#downloadSocialImage").href=`api/drafts/${state.draftId}/social-variants/${v.platform}/image?download=true`}
const stripEmoji=value=>value.replace(/[\\u{1F000}-\\u{1FFFF}\\u{2300}-\\u{27BF}\\u{2B00}-\\u{2BFF}\\uFE0E\\uFE0F\\u200D]/gu,"").replace(/\\s+/g," ").trim();
async function openDraft(id,navigate=true){try{const d=await api(`api/drafts/${id}`);const rubric=state.data?.rubrics?.find(r=>r.slug===d.product);const fixed=!!rubric?.fixed_cover_path;state.draftId=id;state.currentDraft=d;state.socialVariants=await api(`api/drafts/${id}/social-variants`);state.socialPlatform=null;document.querySelector("#socialVariant").hidden=true;document.querySelector("#editorTitle").value=d.title;document.querySelector("#editorVisualTitle").value=d.visual_title||stripEmoji(d.title);document.querySelector("#editorCaption").value=d.caption_html;document.querySelector("#editorLink").value=d.link_url||"";document.querySelector("#titleVariants").innerHTML=jsonList(d.title_options).map(x=>`<button data-title-option="${esc(x)}">${esc(x)}</button>`).join("");document.querySelector("#ctaVariants").innerHTML=jsonList(d.cta_options).map(x=>`<button data-cta-option="${esc(x)}">${esc(x)}</button>`).join("");document.querySelectorAll("[data-title-option]").forEach(b=>b.onclick=()=>document.querySelector("#editorTitle").value=b.dataset.titleOption);document.querySelectorAll("[data-cta-option]").forEach(b=>b.onclick=()=>{const area=document.querySelector("#editorCaption");area.value=`${area.value.trim()}\\n\\n${b.dataset.ctaOption}`});const favorite=document.querySelector("#favoriteDraft");favorite.textContent=d.is_favorite?"★ У прикладах":"☆ До прикладів";favorite.classList.toggle("favorite",!!d.is_favorite);document.querySelector("#editorTemplate").value=state.templateId;document.querySelector("#editorLogo").value=document.querySelector("#logoReference").value;document.querySelector("#editorCompanyLogo").value=document.querySelector("#companyLogoReference").value;document.querySelector("#editorImage").src=`api/drafts/${id}/image`;document.querySelector("#regenImage").hidden=fixed;document.querySelector("#editorVisualSettings").hidden=fixed;document.querySelector("#cancelSchedule").style.display=d.status==="scheduled"?"inline-block":"none";document.querySelector("#scheduleDraft").disabled=d.status!=="ready";document.querySelector("#publishNow").disabled=!["ready","scheduled"].includes(d.status);document.querySelectorAll("[data-social-generate]").forEach(b=>{const existing=state.socialVariants.find(v=>v.platform===b.dataset.socialGenerate);b.textContent=existing?`Відкрити ${b.dataset.socialGenerate}`:b.textContent});if(navigate)history.pushState({draftId:id},"",`/workspace/${state.me.organization_slug}/drafts/${id}`);document.querySelector("#editor").showModal()}catch(e){toast(e.message,true)}}
function closeEditor(){document.querySelector("#editor").close();if(location.pathname.includes("/drafts/"))history.pushState({},"","/")}
document.querySelector("#closeEditor").onclick=closeEditor;
document.querySelector("#editor").addEventListener("cancel",event=>{event.preventDefault();closeEditor()});
window.addEventListener("popstate",()=>{if(!location.pathname.includes("/drafts/")&&document.querySelector("#editor").open)document.querySelector("#editor").close()});
document.querySelector("#syncVisualTitle").onclick=()=>document.querySelector("#editorVisualTitle").value=stripEmoji(document.querySelector("#editorTitle").value);
document.querySelector("#saveDraft").onclick=async()=>{const b=document.querySelector("#saveDraft");await loading(b,async()=>{await api(`api/drafts/${state.draftId}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#editorTitle").value,visual_title:document.querySelector("#editorVisualTitle").value,caption_html:document.querySelector("#editorCaption").value,link_url:document.querySelector("#editorLink").value})});toast("Зміни збережено");await refresh(true)},"Збереження")};
document.querySelector("#regenImage").onclick=async()=>{const b=document.querySelector("#regenImage");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/regenerate-image`,{method:"POST",body:JSON.stringify(generationPayload())});document.querySelector("#editor").close();toast("Нова картинка поставлена в чергу");await refresh(true)},"Додається")};
document.querySelector("#regenText").onclick=async()=>{const b=document.querySelector("#regenText");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/regenerate-text`,{method:"POST",body:JSON.stringify(generationPayload())});document.querySelector("#editor").close();toast("Нова версія тексту поставлена в чергу");await refresh(true)},"Додається")};
document.querySelector("#favoriteDraft").onclick=async()=>{const b=document.querySelector("#favoriteDraft");const next=!state.currentDraft?.is_favorite;await loading(b,async()=>{const d=await api(`api/drafts/${state.draftId}/favorite`,{method:"PUT",body:JSON.stringify({favorite:next})});state.currentDraft=d;b.textContent=d.is_favorite?"★ У прикладах":"☆ До прикладів";b.classList.toggle("favorite",!!d.is_favorite);toast(d.is_favorite?"Пост додано до прикладів":"Пост прибрано з прикладів");await refresh(true)},"Зберігається")};
document.querySelector("#publishNow").onclick=async()=>{const channel=state.company?.telegram?.channel_id||"підключений канал";if(!confirm(`Опублікувати цей пост у ${channel} зараз?`))return;const b=document.querySelector("#publishNow");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/publish`,{method:"POST"});document.querySelector("#editor").close();toast("Пост опубліковано");await refresh()},"Публікується")};
document.querySelector("#scheduleDraft").onclick=async()=>{const value=document.querySelector("#scheduleAt").value;if(!value)return toast("Оберіть дату і час");const b=document.querySelector("#scheduleDraft");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});document.querySelector("#editor").close();toast("Публікацію заплановано");await refresh()},"Планується")};
document.querySelector("#cancelSchedule").onclick=async()=>{const b=document.querySelector("#cancelSchedule");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/cancel-schedule`,{method:"POST"});document.querySelector("#editor").close();toast("Розклад скасовано");await refresh()},"Скасовується")};
document.querySelector("#calendarPrev").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar()};
document.querySelector("#calendarNext").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar()};
document.querySelector("#calendarToday").onclick=()=>{state.calendarDate=new Date();renderCalendar()};
document.querySelector("#logout").onclick=async()=>{await api("api/logout",{method:"POST"});location.reload()};
document.querySelector("#workspaceSelect").onchange=async e=>{await api("api/workspace/select",{method:"POST",body:JSON.stringify({organization_id:Number(e.target.value)})});location.reload()};
document.querySelector("#saveWorkspaceMode").onclick=async()=>{const mode=document.querySelector("#workspaceMode").value;await api("api/workspace/mode",{method:"PUT",body:JSON.stringify({workspace_mode:mode})});state.company.settings.workspace_mode=mode;applyWorkspaceMode();renderActive(true);toast("Режим workspace збережено")};
document.querySelector("#restartOnboarding").onclick=async()=>{await api("api/onboarding/restart",{method:"POST"});state.company.settings.onboarding_status="not_started";state.company.settings.onboarding_step=0;showOnboarding(1)};
document.querySelector("#skipOnboarding").onclick=async()=>{await api("api/onboarding/skip",{method:"POST"});state.company.settings.onboarding_status="skipped";document.querySelector("#onboarding").close();toast("Onboarding можна запустити знову в налаштуваннях бренду")};
document.querySelector("#onboardingBack").onclick=()=>showOnboarding(state.onboardingStep-1);
document.querySelector("#onboardingNext").onclick=async()=>{const b=document.querySelector("#onboardingNext");await loading(b,saveOnboardingStep,state.onboardingStep===5?"Створюється":"Зберігається")};
document.querySelector("#openPricing").onclick=async()=>{try{const data=await api("api/plans");renderPricing(data);document.querySelector("#pricing").showModal()}catch(e){toast(e.message,true)}};
document.querySelector("#closePricing").onclick=()=>document.querySelector("#pricing").close();
document.querySelector("#createUser").onclick=async()=>{const username=document.querySelector("#newUsername").value;const password=document.querySelector("#newPassword").value;try{await api("api/users",{method:"POST",body:JSON.stringify({username,password,is_admin:document.querySelector("#newIsAdmin").checked})});document.querySelector("#newUsername").value="";document.querySelector("#newPassword").value="";document.querySelector("#newIsAdmin").checked=false;toast("Користувача додано");refreshUsers()}catch(e){toast(e.message)}};
document.querySelector("#changeOwnPassword").onclick=async()=>{const password=document.querySelector("#ownPassword").value;if(!password)return toast("Введіть новий пароль");try{await api("api/account/password",{method:"PUT",body:JSON.stringify({password})});location.reload()}catch(e){toast(e.message)}};
document.querySelector("#saveTelegram").onclick=async()=>{const b=document.querySelector("#saveTelegram");await loading(b,async()=>{await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#companyChannel").value,bot_token:document.querySelector("#companyBotToken").value})});document.querySelector("#companyBotToken").value="";await refreshCompany();toast("Telegram-канал підключено")},"Перевіряється")};
document.querySelector("#showRubricForm").onclick=()=>document.querySelector("#rubricForm").hidden=false;
document.querySelector("#cancelRubric").onclick=()=>document.querySelector("#rubricForm").hidden=true;
document.querySelector("#createRubric").onclick=async()=>{const b=document.querySelector("#createRubric");await loading(b,async()=>{await api("api/rubrics",{method:"POST",body:JSON.stringify({name:document.querySelector("#rubricName").value,slug:document.querySelector("#rubricSlug").value,description:document.querySelector("#rubricDescription").value,instructions:document.querySelector("#rubricInstructions").value,default_link:document.querySelector("#rubricLink").value})});for(const id of ["rubricName","rubricSlug","rubricDescription","rubricInstructions","rubricLink"])document.querySelector(`#${id}`).value="";document.querySelector("#rubricForm").hidden=true;toast("Рубрику створено");await refresh()},"Збереження")};
document.querySelector("#createOrganization").onclick=async()=>{const b=document.querySelector("#createOrganization");await loading(b,async()=>{await api("api/organizations",{method:"POST",body:JSON.stringify({name:document.querySelector("#orgName").value,slug:document.querySelector("#orgSlug").value,owner_username:document.querySelector("#orgOwner").value,owner_password:document.querySelector("#orgPassword").value,max_users:Number(document.querySelector("#orgUsers").value),max_channels:Number(document.querySelector("#orgChannels").value),monthly_publications:Number(document.querySelector("#orgPublications").value),monthly_ai_budget:Number(document.querySelector("#orgBudget").value)})});for(const id of ["orgName","orgSlug","orgOwner","orgPassword"])document.querySelector(`#${id}`).value="";await refreshOrganizations();toast("Компанію та власника створено")},"Створюється")};
document.querySelector("#usagePeriod").onchange=refreshPlatformUsage;
document.querySelector("#showCustomTemplate").onclick=()=>document.querySelector("#customTemplateForm").hidden=false;
document.querySelector("#cancelCustomTemplate").onclick=()=>document.querySelector("#customTemplateForm").hidden=true;
document.querySelector("#createTemplate").onclick=async()=>{const b=document.querySelector("#createTemplate");await loading(b,async()=>{await api("api/templates",{method:"POST",body:JSON.stringify({name:document.querySelector("#customTemplateName").value,description:document.querySelector("#customTemplateDescription").value,prompt:document.querySelector("#customTemplatePrompt").value,layout:document.querySelector("#customTemplateLayout").value,accent:document.querySelector("#customTemplateAccent").value})});document.querySelector("#customTemplateForm").hidden=true;toast("Шаблон додано. Тепер можна згенерувати його прев’ю.");await refresh()},"Збереження")};
document.querySelectorAll("[data-social-generate]").forEach(b=>b.onclick=()=>loading(b,async()=>{const platform=b.dataset.socialGenerate;const existing=state.socialVariants.find(v=>v.platform===platform);if(existing){showSocialVariant(existing);return}const v=await api(`api/drafts/${state.draftId}/social-variants`,{method:"POST",body:JSON.stringify({platform,text_model:document.querySelector("#textModel").value,image_model:document.querySelector("#imageModel").value,reference_ids:[...state.referenceIds],template_id:document.querySelector("#editorTemplate").value,logo_reference_id:Number(document.querySelector("#editorLogo").value)||null,company_logo_reference_id:Number(document.querySelector("#editorCompanyLogo").value)||null})});state.socialVariants.push(v);showSocialVariant(v);toast("Версію для соцмережі створено")},"Генерується"));
document.querySelector("#copySocialText").onclick=async()=>{const v=state.socialVariants.find(x=>x.platform===state.socialPlatform);const hashtags=v?.hashtags?.map(x=>x.startsWith("#")?x:`#${x}`).join(" ")||"";await navigator.clipboard.writeText(`${document.querySelector("#socialTitle").value}\\n\\n${document.querySelector("#socialText").value}${hashtags?`\\n\\n${hashtags}`:""}`);toast("Текст скопійовано")};
document.querySelector("#saveSocialVariant").onclick=async()=>{const v=await api(`api/drafts/${state.draftId}/social-variants/${state.socialPlatform}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#socialTitle").value,visual_title:document.querySelector("#socialVisualTitle").value,text_content:document.querySelector("#socialText").value})});state.socialVariants=state.socialVariants.map(x=>x.platform===v.platform?v:x);showSocialVariant(v);toast("Версію збережено")};
function wrapSelection(tag,attrs=""){const area=document.querySelector("#editorCaption");const start=area.selectionStart,end=area.selectionEnd,selected=area.value.slice(start,end)||"текст";const open=`<${tag}${attrs}>`,close=`</${tag}>`;area.setRangeText(open+selected+close,start,end,"select");area.focus()}
document.querySelectorAll("[data-format]").forEach(b=>b.onclick=()=>wrapSelection(b.dataset.format));
document.querySelector("#insertLink").onclick=()=>{const url=prompt("Вставте URL посилання");if(url)wrapSelection("a",` href="${url.replace(/"/g,"&quot;")}"`)};
syncRubricControls();refresh();setInterval(()=>refresh(true),15000);
</script>
</body></html>
"""


app = create_app()


def main() -> None:
    uvicorn.run("voicerhub_bot.admin:app", host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
