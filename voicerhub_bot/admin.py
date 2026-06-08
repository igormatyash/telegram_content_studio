from io import BytesIO
from datetime import date, datetime, timedelta, timezone
import html
import json
from pathlib import Path
from uuid import uuid4
import re

import uvicorn
from openai import AsyncOpenAI
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, Field
from telegram import Bot
from telegram.constants import ParseMode

from voicerhub_bot.auth import AuthRepository, SESSION_DAYS
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
from voicerhub_bot.rendering import MAX_CAPTION_LENGTH, sanitize_telegram_html
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.storage import DraftRepository, TenantRepository
from voicerhub_bot.visual_templates import DEFAULT_TEMPLATE_ID, VISUAL_TEMPLATES


class IdeaRequest(BaseModel):
    product: str = "all"
    count: int = Field(default=6, ge=1, le=12)
    focus: str = Field(default="", max_length=500)
    text_model: str = "gpt-5.4-mini"
    tone: str = "expert"


class ContentPlanRequest(BaseModel):
    product: str = "all"
    period: str = Field(default="week", pattern=r"^(week|month)$")
    posts: int = Field(default=5, ge=1, le=31)
    start_date: date
    focus: str = Field(default="", max_length=500)
    text_model: str = "gpt-5.4-mini"


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
    slug: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=20, max_length=3000)
    instructions: str = Field(default="", max_length=3000)
    default_link: str = Field(default="", max_length=500)


class RubricUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=20, max_length=3000)
    instructions: str = Field(default="", max_length=3000)
    default_link: str = Field(default="", max_length=500)
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
    caption_html: str = Field(min_length=20, max_length=MAX_CAPTION_LENGTH)
    link_url: str = Field(default="", max_length=500)


class FavoriteRequest(BaseModel):
    favorite: bool


class ProofreadRequest(BaseModel):
    text_model: str = "gpt-5.4-mini"


class CustomTemplateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=5, max_length=180)
    prompt: str = Field(min_length=30, max_length=1600)
    layout: str = Field(
        default="top_left",
        pattern=r"^(top_left|left_panel|bottom_left|top_band)$",
    )
    accent: str = Field(default="#18ecd6", pattern=r"^#[0-9A-Fa-f]{6}$")


class ScheduleRequest(BaseModel):
    scheduled_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=10, max_length=200)
    is_admin: bool = False


class UserUpdateRequest(BaseModel):
    is_admin: bool | None = None
    active: bool | None = None


class PasswordRequest(BaseModel):
    password: str = Field(min_length=10, max_length=200)


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9-]+$")
    owner_username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    owner_password: str = Field(min_length=10, max_length=200)
    max_users: int = Field(default=50, ge=1, le=50)
    max_channels: int = Field(default=1, ge=1, le=1)
    monthly_publications: int = Field(default=90, ge=1, le=10000)
    monthly_ai_budget: float = Field(default=50, ge=0, le=100000)


class TelegramConnectionRequest(BaseModel):
    bot_token: str = Field(min_length=20, max_length=200)
    channel_id: str = Field(min_length=2, max_length=200)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare_directories()
    repository = TenantRepository(settings.database_path, settings.organizations_dir)
    auth = AuthRepository(settings.database_path)
    auth.ensure_bootstrap_admin(settings.admin_username, settings.admin_password)
    saas = SaasRepository(settings.database_path, settings.app_encryption_key)
    saas.ensure_legacy_organization(channel_id=settings.telegram_channel)
    repository.for_organization(1).ensure_legacy_rubrics(
        str(Path(__file__).parent / "assets" / "VoicerWave.jpg")
    )
    idea_generator = IdeaGenerator(settings)
    editorial_tools = EditorialTools(settings)
    app = FastAPI(title=settings.product_name, docs_url=None, redoc_url=None)

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

    def authorize(
        voicerhub_session: str | None = Cookie(default=None),
    ) -> dict:
        user = auth.session_user(voicerhub_session)
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        organization_id = int(user.get("organization_id") or 1)
        repository.use(organization_id)
        return user

    def authorize_write(
        user: dict = Depends(authorize),
        x_requested_with: str | None = Header(default=None),
    ) -> dict:
        if x_requested_with != "VoicerHubAdmin":
            raise HTTPException(status_code=403, detail="Missing request guard")
        return user

    def authorize_admin(user: dict = Depends(authorize_write)) -> dict:
        if not user["is_admin"]:
            raise HTTPException(status_code=403, detail="Administrator access required")
        return user

    def authorize_super_admin(user: dict = Depends(authorize_write)) -> dict:
        if not user.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Platform administrator required")
        return user

    def organization_id(user: dict) -> int:
        return int(user.get("organization_id") or 1)

    def ensure_organization_user(current: dict, target_user_id: int) -> None:
        if target_user_id not in saas.member_ids(organization_id(current)):
            raise HTTPException(status_code=404, detail="Користувача не знайдено")

    def ensure_ai_budget() -> None:
        company = saas.get_organization(repository.organization_id)
        budget = float(company["monthly_ai_budget"])
        if budget > 0 and repository.current_month_cost() >= budget:
            raise HTTPException(
                status_code=402,
                detail="Місячний AI-бюджет компанії вичерпано",
            )

    def ensure_publication_quota() -> None:
        company = saas.get_organization(repository.organization_id)
        if (
            repository.current_month_publications()
            >= company["monthly_publications"]
        ):
            raise HTTPException(
                status_code=409,
                detail="Місячний ліміт публікацій вичерпано",
            )

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

    @app.get("/", response_class=HTMLResponse)
    def dashboard(voicerhub_session: str | None = Cookie(default=None)) -> str:
        user = auth.session_user(voicerhub_session)
        if user:
            repository.use(int(user.get("organization_id") or 1))
        return ADMIN_HTML if user else LOGIN_HTML

    @app.post("/api/login")
    def login(payload: LoginRequest, response: Response) -> dict:
        user = auth.authenticate(payload.username, payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Невірний логін або пароль")
        token = auth.create_session(user["id"])
        response.set_cookie(
            "voicerhub_session",
            token,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
        )
        return {"user": user}

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
        return user

    @app.get("/api/users")
    def users(user: dict = Depends(authorize_admin)) -> list[dict]:
        return auth.list_users(int(user.get("organization_id") or 1))

    @app.post("/api/users")
    def create_user(
        payload: UserCreateRequest,
        current: dict = Depends(authorize_admin),
    ) -> dict:
        company = saas.get_organization(organization_id(current))
        if len(saas.member_ids(organization_id(current))) >= company["max_users"]:
            raise HTTPException(
                status_code=409,
                detail="Досягнуто ліміт користувачів компанії",
            )
        try:
            return auth.create_user(
                payload.username,
                payload.password,
                is_admin=payload.is_admin,
                organization_id=organization_id(current),
                role="admin" if payload.is_admin else "editor",
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="Такий логін вже існує") from exc
            raise

    @app.get("/api/organizations")
    def organizations(_: dict = Depends(authorize_super_admin)) -> list[dict]:
        return saas.list_organizations()

    @app.get("/api/platform/usage")
    def platform_usage(
        period: str = "month",
        _: dict = Depends(authorize_super_admin),
    ) -> dict:
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

        users = {user["id"]: user for user in auth.list_users()}
        companies = []
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
        for company in saas.list_organizations():
            report = repository.for_organization(company["id"]).usage_summary(
                since=since_value
            )
            company_totals = report["totals"]
            companies.append(
                {
                    "organization_id": company["id"],
                    "organization_name": company["name"],
                    **company_totals,
                }
            )
            for key in totals:
                totals[key] += company_totals[key]
            for row in report["users"]:
                user = users.get(row["user_id"])
                user_rows.append(
                    {
                        "organization_id": company["id"],
                        "organization_name": company["name"],
                        "user_id": row["user_id"],
                        "username": (
                            user["username"] if user else "Система / не визначено"
                        ),
                        **{key: value for key, value in row.items() if key != "user_id"},
                    }
                )
            for row in report["models"]:
                model_rows.append(
                    {
                        "organization_id": company["id"],
                        "organization_name": company["name"],
                        **row,
                    }
                )
        return {
            "period": period,
            "since": since.isoformat() if since else None,
            "totals": totals,
            "companies": companies,
            "users": sorted(
                user_rows,
                key=lambda row: (-float(row["cost"]), row["organization_name"]),
            ),
            "models": sorted(
                model_rows,
                key=lambda row: (-float(row["cost"]), row["organization_name"]),
            ),
        }

    @app.post("/api/organizations")
    def create_organization(
        payload: OrganizationCreateRequest,
        current: dict = Depends(authorize_super_admin),
    ) -> dict:
        if len(saas.list_organizations()) >= settings.max_organizations:
            raise HTTPException(
                status_code=409,
                detail=f"Досягнуто ліміт у {settings.max_organizations} компанії",
            )
        try:
            organization = saas.create_organization(
                name=payload.name,
                slug=payload.slug,
                max_users=payload.max_users,
                max_channels=payload.max_channels,
                monthly_publications=payload.monthly_publications,
                monthly_ai_budget=payload.monthly_ai_budget,
            )
            owner = auth.create_user(
                payload.owner_username,
                payload.owner_password,
                is_admin=True,
                organization_id=organization["id"],
                role="owner",
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(
                    status_code=409,
                    detail="Компанія або логін уже існує",
                ) from exc
            raise
        repository.for_organization(organization["id"])
        saas.audit(
            organization["id"],
            current["id"],
            "organization.created",
            payload.slug,
        )
        return {**organization, "owner": owner}

    @app.get("/api/company")
    def current_company(user: dict = Depends(authorize)) -> dict:
        current_organization_id = organization_id(user)
        company = saas.get_organization(current_organization_id)
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
            **company,
            "telegram": telegram_connection,
            "user_count": len(saas.member_ids(current_organization_id)),
            "ai_spend": repository.current_month_cost(),
            "publication_count": repository.current_month_publications(),
        }

    @app.get("/api/rubrics")
    def rubrics(_: dict = Depends(authorize)) -> list[dict]:
        return repository.list_rubrics(include_inactive=True)

    @app.post("/api/rubrics")
    def create_rubric(
        payload: RubricCreateRequest,
        user: dict = Depends(authorize_admin),
    ) -> dict:
        slug = re.sub(r"[^a-z0-9-]+", "-", payload.slug.lower()).strip("-")
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
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="Такий slug уже існує") from exc
            raise
        saas.audit(organization_id(user), user["id"], "rubric.created", slug)
        return rubric

    @app.put("/api/rubrics/{rubric_id}")
    def update_rubric(
        rubric_id: int,
        payload: RubricUpdateRequest,
        user: dict = Depends(authorize_admin),
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
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Рубрику не знайдено") from exc
        saas.audit(organization_id(user), user["id"], "rubric.updated", rubric["slug"])
        return rubric

    @app.put("/api/company/telegram")
    async def connect_telegram(
        payload: TelegramConnectionRequest,
        user: dict = Depends(authorize_admin),
    ) -> dict:
        organization_id = int(user.get("organization_id") or 1)
        try:
            bot = Bot(payload.bot_token.strip())
            profile = await bot.get_me()
            member = await bot.get_chat_member(payload.channel_id.strip(), profile.id)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="Не вдалося перевірити бота або доступ до каналу",
            ) from exc
        if member.status not in {"administrator", "creator"}:
            raise HTTPException(
                status_code=422,
                detail="Бот повинен бути адміністратором Telegram-каналу",
            )
        try:
            connection = saas.save_telegram_connection(
                organization_id,
                channel_id=payload.channel_id,
                bot_token=payload.bot_token,
                bot_username=profile.username or "",
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Шифрування секретів ще не налаштовано",
            ) from exc
        saas.audit(
            organization_id,
            user["id"],
            "telegram.connected",
            payload.channel_id,
        )
        return connection

    @app.patch("/api/users/{user_id}")
    def update_user(
        user_id: int,
        payload: UserUpdateRequest,
        current: dict = Depends(authorize_admin),
    ) -> dict:
        ensure_organization_user(current, user_id)
        if user_id == current["id"] and payload.active is False:
            raise HTTPException(status_code=422, detail="Не можна заблокувати себе")
        if user_id == current["id"] and payload.is_admin is False:
            raise HTTPException(status_code=422, detail="Не можна забрати свою роль")
        try:
            return auth.update_user(
                user_id, is_admin=payload.is_admin, active=payload.active
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/users/{user_id}/password")
    def admin_set_password(
        user_id: int,
        payload: PasswordRequest,
        current: dict = Depends(authorize_admin),
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
        data["templates"] = [
            {**item, "custom": False, "has_preview": True}
            for item in VISUAL_TEMPLATES
        ] + [
            {**item, "custom": True, "has_preview": bool(item["preview_path"])}
            for item in repository.list_custom_templates()
        ]
        return data

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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        return {"ideas": saved}

    @app.post("/api/content-plan/generate")
    async def generate_content_plan(
        payload: ContentPlanRequest,
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        return {"plan_id": plan_id, "ideas": save_ideas(plan.ideas, plan_id=plan_id)}

    @app.post("/api/series/generate")
    async def generate_series(
        payload: SeriesRequest,
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
        _validate_generation(payload, repository)
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
        return {"job_id": job.id}

    @app.post("/api/jobs/{job_id}/retry-fast")
    async def retry_job_fast(
        job_id: int,
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
        try:
            job = repository.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Завдання не знайдено") from exc
        if job.status not in {
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
        if job.draft_id and job.status in {"queued_image", "image_batch"}:
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

    @app.delete("/api/ideas/{idea_id}")
    def delete_idea(idea_id: int, _: str = Depends(authorize_write)) -> dict:
        try:
            repository.delete_idea(idea_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Тему не знайдено") from exc
        return {"deleted": idea_id}

    @app.post("/api/templates")
    def create_template(
        payload: CustomTemplateRequest,
        _: str = Depends(authorize_write),
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
        )

    @app.delete("/api/templates/{template_id}")
    def delete_template(
        template_id: str,
        _: str = Depends(authorize_write),
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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        _: str = Depends(authorize_write),
    ) -> dict:
        media_type = file.content_type or ""
        if media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise HTTPException(status_code=422, detail="Use PNG, JPG or WebP")
        content = await file.read()
        if not content or len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Image must be under 20 MB")
        try:
            image = Image.open(BytesIO(content))
            image.verify()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid image file") from exc
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[
            media_type
        ]
        _, reference_dir = organization_dirs(repository.organization_id)
        path = reference_dir / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        return repository.add_reference(
            name=Path(file.filename or "reference").stem[:100],
            filename=(file.filename or path.name)[:200],
            path=str(path),
            media_type=media_type,
        )

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
        reference_id: int, _: str = Depends(authorize_write)
    ) -> dict:
        try:
            reference = repository.delete_reference(reference_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        _: str = Depends(authorize_write),
    ) -> dict:
        try:
            return repository.set_draft_favorite(draft_id, payload.favorite)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc

    @app.post("/api/drafts/{draft_id}/proofread")
    async def proofread_draft(
        draft_id: int,
        payload: ProofreadRequest,
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
        _validate_models(payload.text_model)
        try:
            draft = repository.draft_record(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Чернетку не знайдено") from exc
        caption, input_tokens, output_tokens = await editorial_tools.proofread(
            draft["caption_html"],
            payload.text_model,
        )
        repository.update_draft(
            draft_id,
            title=draft["title"],
            caption_html=caption,
            link_url=draft["link_url"],
        )
        record_text_usage(payload.text_model, input_tokens, output_tokens, user["id"])
        return repository.draft_record(draft_id)

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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
            social.title,
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
        _: dict = Depends(authorize_write),
    ) -> dict:
        try:
            current = repository.get_social_variant(draft_id, platform)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Версію не знайдено") from exc
        return repository.save_social_variant(
            draft_id=draft_id,
            platform=platform,
            title=payload.title.strip(),
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
        _: str = Depends(authorize_write),
    ) -> dict:
        link_url = payload.link_url.strip()
        if link_url and not link_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="Посилання має починатися з http:// або https://",
            )
        caption_html = sanitize_telegram_html(payload.caption_html.strip())
        if link_url and "<a " not in caption_html:
            caption_html += (
                f'\n\n<a href="{html.escape(link_url, quote=True)}">'
                "Детальніше про продукт</a>"
            )
        repository.update_draft(
            draft_id,
            title=payload.title.strip(),
            caption_html=caption_html,
            link_url=link_url,
        )
        return repository.draft_record(draft_id)

    @app.post("/api/drafts/{draft_id}/regenerate-image")
    def regenerate_image(
        draft_id: int,
        payload: GenerationRequest,
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_ai_budget()
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
        user: dict = Depends(authorize_write),
    ) -> dict:
        ensure_publication_quota()
        draft = repository.draft_record(draft_id)
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
        return {"message_id": message.message_id}

    @app.post("/api/drafts/{draft_id}/schedule")
    def schedule_draft(
        draft_id: int,
        payload: ScheduleRequest,
        _: str = Depends(authorize_write),
    ) -> dict:
        scheduled_at = payload.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        scheduled_at = scheduled_at.astimezone(timezone.utc)
        if scheduled_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Schedule time must be in the future")
        value = scheduled_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        repository.schedule_draft(draft_id, value)
        return {"scheduled_at": value}

    @app.post("/api/drafts/{draft_id}/cancel-schedule")
    def cancel_schedule(
        draft_id: int,
        _: str = Depends(authorize_write),
    ) -> dict:
        repository.cancel_schedule(draft_id)
        return {"status": "draft"}

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
    .drafts{grid-template-columns:repeat(3,minmax(280px,1fr));gap:18px}.draft{border-radius:8px;transition:transform .18s ease,box-shadow .18s ease}.draft img{filter:saturate(1.04)}.draft-body{padding:16px}.draft h3{font-size:17px}.draft p{line-height:1.55}
    .calendar{border:0;gap:10px;background:transparent;grid-template-columns:repeat(7,minmax(0,1fr))}.weekday{border:0;border-radius:8px;background:#eaf0f7}.day{border:1px solid rgba(203,213,225,.78);border-radius:8px;background:rgba(255,255,255,.88);box-shadow:var(--shadow-sm);transition:transform .16s ease,box-shadow .16s ease}.day:hover{transform:translateY(-2px);box-shadow:var(--shadow)}.day.today{box-shadow:0 0 0 3px rgba(16,191,174,.18),var(--shadow-sm)}.calendar-item{border-radius:7px;border-left:0;background:linear-gradient(135deg,#ecfdf5,#eef6ff);box-shadow:inset 0 0 0 1px rgba(16,191,174,.16);transition:transform .15s ease,box-shadow .15s ease}.calendar-item:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(15,23,42,.10)}.calendar-item.published{background:linear-gradient(135deg,#eff6ff,#f5f3ff)}.calendar-item.planned{background:linear-gradient(135deg,#fff7ed,#fefce8)}
    th{background:#f4f7fb;color:#64748b;font-size:11px;letter-spacing:.04em;text-transform:uppercase}td{background:rgba(255,255,255,.78)}tbody tr{transition:background .16s ease}tbody tr:hover td{background:#f8fbff}.scroll{border-radius:8px;overflow:auto;box-shadow:var(--shadow-sm)}.scroll table{box-shadow:none}.status.busy{animation:glow 2s ease-in-out infinite}.notice{border-radius:8px;box-shadow:var(--shadow);animation:rise .22s ease both}
    dialog{border-radius:8px;box-shadow:0 30px 110px rgba(15,23,42,.42)}.editor-head{background:linear-gradient(135deg,#0f172a,#111827);color:#fff}.editor-head button{color:#fff;background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.16)}.editor-grid{background:#f8fafc}.editor-grid img{border-radius:8px;box-shadow:var(--shadow-sm)}#socialVariant{border-radius:8px;background:#fff;box-shadow:var(--shadow-sm)}
    @media(max-width:1100px){.app-shell{grid-template-columns:1fr}.sidebar{position:static;height:auto}.tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}.tab:hover{transform:translateY(-1px)}.sidebar-foot{display:none}.modelbar{grid-template-columns:1fr 1fr}.topbar{position:static}.templates{grid-template-columns:repeat(3,1fr)}}
    @media(max-width:950px){.drafts{grid-template-columns:repeat(2,1fr)}.editor-grid{grid-template-columns:1fr}.toolbar,.user-create,.planning-grid,.company-form{grid-template-columns:1fr 1fr}.company-grid{grid-template-columns:repeat(2,1fr)}.toolbar label:nth-child(4){grid-column:1/-1}.assets,.templates{grid-template-columns:repeat(3,1fr)}.calendar-wrap{overflow-x:auto}.calendar{min-width:900px}}
    @media(max-width:620px){main,.topbar{padding-left:14px;padding-right:14px}.sidebar{min-width:0}.brand h1{font-size:14px}.topbar{align-items:flex-start;flex-direction:column}.topbar>div:first-child{min-width:0}.topbar p{white-space:normal}.account{gap:6px;flex-wrap:wrap}.account #updated{display:none}.tabs{display:flex;max-width:100%;overflow-x:auto;flex-direction:row}.tab{width:auto;flex:0 0 auto;padding:11px 12px}.toolbar,.modelbar,.user-create,.brand-options,.custom-template,.planning-grid,.variants,.company-grid,.company-form{grid-template-columns:1fr}.toolbar label:nth-child(4),.custom-template .wide,.company-form .wide{grid-column:auto}.drafts{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}.idea{grid-template-columns:24px 74px minmax(0,1fr)}.idea .editor-actions{grid-column:2/-1}.assets,.templates{grid-template-columns:repeat(2,minmax(0,1fr))}.scroll{overflow-x:auto}.scroll table{min-width:780px}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
  </style>
</head>
<body>
<div class="app-shell">
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark"></span><div><h1>CONTENT STUDIO</h1><span>AI publishing workspace</span></div></div>
    <nav class="tabs">
      <button class="tab active" data-view="ideasView">Теми</button>
      <button class="tab" data-view="planningView">Планування</button>
      <button class="tab" data-view="draftsView">Редактор</button>
      <button class="tab" data-view="calendarView">Календар</button>
      <button class="tab" data-view="opsView">Черга та витрати</button>
      <button class="tab" data-view="companyView">Компанія</button>
      <button class="tab" id="usersTab" data-view="usersView">Доступ</button>
      <button class="tab" id="platformTab" data-view="platformView" hidden>Платформа</button>
    </nav>
    <div class="sidebar-foot"><strong id="sidebarCompany">VoicerHub</strong><span>Content operations center</span></div>
  </aside>
  <div class="workspace">
    <header class="topbar">
      <div><h2 id="viewTitle">Теми</h2><p id="viewSubtitle">Плануйте і запускайте AI-публікації з одного робочого центру.</p></div>
      <div class="account"><span id="currentCompany"></span><span id="currentUser"></span><span id="updated">—</span><button id="logout" title="Вийти">Вийти</button></div>
    </header>
<main>

  <section id="ideasView" class="view active">
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

<dialog id="editor">
  <div class="editor-head"><strong>Редагування поста</strong><button id="closeEditor">✕</button></div>
  <div class="editor-grid">
    <div><img id="editorImage" alt="Зображення поста"><div class="editor-actions"><button id="regenImage">↻ Інша картинка</button></div></div>
    <div>
      <label>Заголовок<input id="editorTitle"></label>
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
        <button id="proofreadDraft">✓ Перевірити українську</button>
        <button id="favoriteDraft">☆ До прикладів</button>
        <button class="success" id="publishNow">Опублікувати зараз</button>
      </div>
      <div class="schedule"><input id="scheduleAt" type="datetime-local"><button id="scheduleDraft">Запланувати</button></div>
      <div class="editor-actions"><button class="danger" id="cancelSchedule">Скасувати розклад</button></div>
    </div>
  </div>
</dialog>
<div id="notice" class="notice"></div>

<script>
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=v=>`$${Number(v||0).toFixed(4)}`; const short=v=>v?`${v.slice(0,14)}...`:"—";
const rubricLabel=v=>state.data?.rubrics?.find(r=>r.slug===v)?.name||v;
const toneLabel=v=>({expert:"Експертний",sales:"Продаючий",light:"Легкий",news:"Новинний"}[v]||v);
const statusLabels={suggested:"Запропоновано",selected:"У черзі",queued_text:"Очікує генерації тексту",text_batch:"Генерується текст",queued_image:"Очікує генерації зображення",image_batch:"Генерується зображення",ready:"Готово",draft:"Чернетка",scheduled:"Заплановано",published:"Опубліковано",failed:"Помилка",completed:"Завершено",in_progress:"Виконується",cancelled:"Скасовано",expired:"Термін минув"};
const busyStatuses=new Set(["selected","queued_text","text_batch","queued_image","image_batch","in_progress"]);
const viewMeta={ideasView:["Теми","Плануйте і запускайте AI-публікації з одного робочого центру."],planningView:["Планування","Створюйте контент-плани, серії та матеріали на основі сайту."],draftsView:["Редактор","Перевіряйте тексти, візуали та версії для соціальних мереж."],calendarView:["Календар","Контролюйте ритм публікацій і майбутнє навантаження."],opsView:["Черга та витрати","Слідкуйте за генераціями, Batch-завданнями і бюджетом."],companyView:["Компанія","Керуйте каналом, рубриками та корпоративним контекстом."],usersView:["Доступ","Керуйте користувачами, ролями та паролями."],platformView:["Платформа","Контролюйте компанії, використання AI та загальні ліміти."]};
const state={data:null,me:null,company:null,organizations:[],platformUsage:null,draftId:null,currentDraft:null,socialPlatform:null,socialVariants:[],referenceIds:new Set(),templateId:localStorage.getItem("templateId")||"editorial-dark",calendarDate:new Date(),ideaPage:1,draftPage:1,jobPage:1,pageSize:12,favoritesOnly:false}; const apiUrl=p=>{const u=new URL(p,location.href);u.username="";u.password="";return u};
function errorText(detail){if(typeof detail==="string")return detail;if(Array.isArray(detail))return detail.map(x=>x.msg||x.message||JSON.stringify(x)).join("; ");if(detail&&typeof detail==="object")return detail.message||detail.detail||JSON.stringify(detail);return "Невідома помилка"}
async function api(path,options={}){options.credentials="same-origin";options.headers={...(options.headers||{}),"X-Requested-With":"VoicerHubAdmin"};if(options.body&&!(options.body instanceof FormData))options.headers["Content-Type"]="application/json";const r=await fetch(apiUrl(path),options);if(!r.ok){let d={};try{d=await r.json()}catch{}const fallback={401:"Потрібно увійти знову",403:"Недостатньо прав",404:"Дані не знайдено",409:"Дію зараз неможливо виконати",422:"Перевірте введені дані",500:"Внутрішня помилка сервера"}[r.status]||`Помилка HTTP ${r.status}`;const detail=d.detail===undefined?fallback:errorText(d.detail);throw new Error(detail)}if(r.status===204)return {};return r.json()}
function toast(text,error=false){const n=document.querySelector("#notice");n.textContent=errorText(text);n.style.background=error?"#8f1d1d":"#111a2d";n.style.display="block";clearTimeout(n.timer);n.timer=setTimeout(()=>n.style.display="none",5000)}
async function loading(button,work,label="Виконується"){const old=button.innerHTML;button.disabled=true;button.innerHTML=`<span class="spinner"></span>${label}`;try{return await work()}catch(e){toast(e.message,true);return null}finally{button.disabled=false;button.innerHTML=old}}
const inferredLink=product=>state.data?.rubrics?.find(r=>r.slug===product)?.default_link||"";
const generationPayload=(product="",tone="")=>{const modal=document.querySelector("#editor");const inEditor=modal.open;return {text_model:document.querySelector("#textModel").value,image_model:document.querySelector("#imageModel").value,reference_ids:[...state.referenceIds],template_id:inEditor?document.querySelector("#editorTemplate").value:state.templateId,logo_reference_id:Number(inEditor?document.querySelector("#editorLogo").value:document.querySelector("#logoReference").value)||null,company_logo_reference_id:Number(inEditor?document.querySelector("#editorCompanyLogo").value:document.querySelector("#companyLogoReference").value)||null,link_url:(inEditor?document.querySelector("#editorLink").value:document.querySelector("#defaultLink").value)||inferredLink(product),tone:tone||document.querySelector("#ideaTone").value,generation_mode:document.querySelector("#generationMode").value}};
for(const id of ["textModel","imageModel","generationMode"]){const el=document.querySelector(`#${id}`);el.value=localStorage.getItem(id)||el.value;el.onchange=()=>localStorage.setItem(id,el.value)}
function setViewMeta(view){const meta=viewMeta[view]||[view,""];document.querySelector("#viewTitle").textContent=meta[0];document.querySelector("#viewSubtitle").textContent=meta[1]}
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab,.view").forEach(x=>x.classList.remove("active"));b.classList.add("active");document.querySelector(`#${b.dataset.view}`).classList.add("active");setViewMeta(b.dataset.view);renderActive(true)});
const paginate=(items,page,size)=>items.slice((page-1)*size,page*size);
function pagination(id,total,page,setter){const pages=Math.max(1,Math.ceil(total/state.pageSize));page=Math.min(page,pages);document.querySelector(`#${id}`).innerHTML=total>state.pageSize?`<button data-page-prev ${page<=1?"disabled":""}>←</button><span>Сторінка ${page} з ${pages}</span><button data-page-next ${page>=pages?"disabled":""}>→</button>`:"";document.querySelector(`#${id} [data-page-prev]`)?.addEventListener("click",()=>setter(page-1));document.querySelector(`#${id} [data-page-next]`)?.addEventListener("click",()=>setter(page+1))}
function renderIdeas(ideas){const page=paginate(ideas,state.ideaPage,state.pageSize);document.querySelector("#ideas").innerHTML=page.length?page.map(i=>{const busy=busyStatuses.has(i.status);const done=["ready","draft","scheduled","published"].includes(i.status);const duplicate=Number(i.duplicate_score||0)>=.62;return `<div class="idea"><input class="ideaCheck" type="checkbox" value="${i.id}" ${i.status!=="suggested"?"disabled":""}><span class="badge">${esc(rubricLabel(i.product))}</span><div><strong>${esc(i.series_part?`${i.series_part}/${i.series_title} · ${i.title}`:i.title)}</strong><p>${esc(i.angle)}</p><div class="idea-meta"><span class="meta-chip">${esc(toneLabel(i.tone))}</span>${i.planned_for?`<span class="meta-chip">${esc(new Date(`${i.planned_for}T12:00:00`).toLocaleDateString("uk-UA"))}</span>`:""}${i.source_url?`<span class="meta-chip">Матеріал із сайту</span>`:""}${duplicate?`<span class="meta-chip warn">Схожість ${Math.round(i.duplicate_score*100)}%</span>`:""}</div><span class="status ${esc(i.status)} ${busy?"busy":""}">${esc(statusLabels[i.status]||i.status)}</span></div><div class="editor-actions">${done&&i.draft_id?`<button data-open-idea="${i.draft_id}">Відкрити пост</button>`:`<button data-idea="${i.id}" ${i.status!=="suggested"?"disabled":""}>${i.status==="suggested"?"Створити пост":esc(statusLabels[i.status]||i.status)}</button>`}<button class="danger" data-delete-idea="${i.id}" title="Видалити тему">✕</button></div></div>`}).join(""):`<div class="empty">Згенеруйте перший набір тем</div>`;pagination("ideasPagination",ideas.length,state.ideaPage,p=>{state.ideaPage=p;renderIdeas(ideas)});document.querySelectorAll("[data-idea]").forEach(b=>b.onclick=()=>generateIdea(Number(b.dataset.idea)));document.querySelectorAll("[data-open-idea]").forEach(b=>b.onclick=()=>openDraft(b.dataset.openIdea));document.querySelectorAll("[data-delete-idea]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цю тему зі списку?"))return;try{await api(`api/ideas/${b.dataset.deleteIdea}`,{method:"DELETE"});await refresh()}catch(e){toast(e.message,true)}})}
function renderTemplates(templates){document.querySelector("#templates").innerHTML=templates.map(t=>`<article class="template ${t.id===state.templateId?"selected":""}" data-template="${esc(t.id)}">${t.has_preview?`<img src="api/templates/${esc(t.id)}/preview?v=2" alt="${esc(t.name)}">`:`<div class="empty">Прев’ю ще немає</div>`}<span class="template-copy"><strong>${esc(t.name)}</strong><span>${esc(t.description)}</span></span>${t.custom?`<span class="template-actions">${!t.has_preview?`<button data-preview-template="${esc(t.id)}">Створити прев’ю</button>`:""}<button class="danger" data-delete-template="${esc(t.id)}">Видалити</button></span>`:""}</article>`).join("");const editorSelect=document.querySelector("#editorTemplate");const current=editorSelect.value;editorSelect.innerHTML=templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");editorSelect.value=templates.some(t=>t.id===current)?current:state.templateId;document.querySelectorAll("[data-template]").forEach(card=>card.onclick=e=>{if(e.target.closest("[data-preview-template],[data-delete-template]"))return;state.templateId=card.dataset.template;localStorage.setItem("templateId",state.templateId);renderTemplates(templates)});document.querySelectorAll("[data-preview-template]").forEach(b=>b.onclick=()=>loading(b,async()=>{await api(`api/templates/${b.dataset.previewTemplate}/generate-preview`,{method:"POST"});await refresh()},"Генерується"));document.querySelectorAll("[data-delete-template]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цей шаблон?"))return;try{await api(`api/templates/${b.dataset.deleteTemplate}`,{method:"DELETE"});if(state.templateId===b.dataset.deleteTemplate)state.templateId="editorial-dark";await refresh()}catch(e){toast(e.message,true)}})}
function renderLogoOptions(assets){for(const id of ["logoReference","editorLogo","companyLogoReference","editorCompanyLogo"]){const select=document.querySelector(`#${id}`);const current=select.value;const company=id.toLowerCase().includes("company");select.innerHTML=`<option value="">${company?"Без логотипа компанії":"Без логотипа продукту"}</option>`+assets.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join("");if(assets.some(a=>String(a.id)===current))select.value=current}}
function renderAssets(assets){const valid=new Set(assets.map(a=>a.id));for(const id of state.referenceIds)if(!valid.has(id))state.referenceIds.delete(id);document.querySelector("#assets").innerHTML=assets.length?assets.map(a=>`<article class="asset ${state.referenceIds.has(a.id)?"selected":""}" data-asset="${a.id}"><img src="api/references/${a.id}/image" alt="${esc(a.name)}"><div class="asset-info"><input type="checkbox" ${state.referenceIds.has(a.id)?"checked":""}><span title="${esc(a.name)}">${esc(a.name)}</span><button class="asset-delete" data-delete-asset="${a.id}" title="Видалити">✕</button></div></article>`).join(""):`<div class="empty">Додайте логотипи продуктів, скриншоти або приклади стилю</div>`;document.querySelectorAll("[data-asset]").forEach(card=>card.onclick=e=>{if(e.target.closest("[data-delete-asset]"))return;const id=Number(card.dataset.asset);if(state.referenceIds.has(id))state.referenceIds.delete(id);else if(state.referenceIds.size>=16)return toast("Можна обрати не більше 16 матеріалів");else state.referenceIds.add(id);renderAssets(state.data.references)});document.querySelectorAll("[data-delete-asset]").forEach(b=>b.onclick=async()=>{if(!confirm("Видалити цей бренд-матеріал?"))return;await api(`api/references/${b.dataset.deleteAsset}`,{method:"DELETE"});state.referenceIds.delete(Number(b.dataset.deleteAsset));refresh()})}
function renderDrafts(drafts){const filtered=state.favoritesOnly?drafts.filter(d=>d.is_favorite):drafts;const page=paginate(filtered,state.draftPage,state.pageSize);document.querySelector("#drafts").innerHTML=page.length?page.map(d=>`<article class="draft" data-draft-card="${d.id}">${d.image_path?`<img src="api/drafts/${d.id}/image" alt="">`:`<div class="empty"><span class="spinner"></span>Зображення генерується</div>`}<div class="draft-body"><div class="draft-meta"><span class="badge">${esc(rubricLabel(d.product))}${d.is_favorite?" · ★":""}</span><span class="status ${esc(d.status)}">${esc(statusLabels[d.status]||d.status)}</span></div><h3>${esc(d.title)}</h3><p>${esc(d.caption_html.replace(/<[^>]+>/g,""))}</p><button data-draft="${d.id}">Відкрити редактор</button></div></article>`).join(""):`<div class="empty">${state.favoritesOnly?"Вдалих прикладів ще немає":"Готових чернеток поки немає"}</div>`;pagination("draftsPagination",filtered.length,state.draftPage,p=>{state.draftPage=p;renderDrafts(drafts)});document.querySelectorAll("[data-draft]").forEach(b=>b.onclick=()=>openDraft(b.dataset.draft))}
function updateDraftStatuses(drafts){for(const d of drafts){const card=document.querySelector(`[data-draft-card="${d.id}"]`);if(card){const el=card.querySelector(".status");el.className=`status ${d.status}`;el.textContent=statusLabels[d.status]||d.status}}}
function renderUsers(users){document.querySelector("#users").innerHTML=users.map(u=>`<tr><td><strong>${esc(u.username)}</strong></td><td>${u.is_admin?"Адміністратор":"Редактор"}</td><td class="status ${u.active?"ready":"failed"}">${u.active?"Активний":"Заблокований"}</td><td>${esc(new Date(`${u.created_at}Z`).toLocaleDateString("uk-UA"))}</td><td><div class="user-actions"><button data-role-user="${u.id}">${u.is_admin?"Зробити редактором":"Зробити адміністратором"}</button><button data-active-user="${u.id}" class="${u.active?"danger":""}">${u.active?"Заблокувати":"Активувати"}</button><button data-password-user="${u.id}">Новий пароль</button></div></td></tr>`).join("");document.querySelectorAll("[data-role-user]").forEach(b=>b.onclick=async()=>{const u=users.find(x=>x.id===Number(b.dataset.roleUser));await api(`api/users/${u.id}`,{method:"PATCH",body:JSON.stringify({is_admin:!u.is_admin})});refreshUsers()});document.querySelectorAll("[data-active-user]").forEach(b=>b.onclick=async()=>{const u=users.find(x=>x.id===Number(b.dataset.activeUser));await api(`api/users/${u.id}`,{method:"PATCH",body:JSON.stringify({active:!u.active})});refreshUsers()});document.querySelectorAll("[data-password-user]").forEach(b=>b.onclick=async()=>{const password=prompt("Новий пароль, мінімум 10 символів");if(!password)return;await api(`api/users/${b.dataset.passwordUser}/password`,{method:"PUT",body:JSON.stringify({password})});toast("Пароль змінено")})}
function renderCompany(company){state.company=company;document.querySelector("#currentCompany").textContent=company.name;document.querySelector("#sidebarCompany").textContent=company.name;document.querySelector("#companyCards").innerHTML=`<div class="company-card"><span>Компанія</span><strong>${esc(company.name)}</strong></div><div class="company-card"><span>Користувачі</span><strong>${company.user_count} / ${company.max_users}</strong></div><div class="company-card"><span>Telegram-канали</span><strong>${company.telegram?.configured?"1 підключено":`0 / ${company.max_channels}`}</strong></div><div class="company-card"><span>Публікації цього місяця</span><strong>${company.publication_count} / ${company.monthly_publications}</strong></div><div class="company-card"><span>AI-витрати цього місяця</span><strong>${money(company.ai_spend)} / $${Number(company.monthly_ai_budget).toFixed(0)}</strong></div>`;document.querySelector("#companyChannel").value=company.telegram?.channel_id||""}
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
function renderActive(full=false){if(!state.data)return;renderRubrics(state.data.rubrics||[]);const view=activeView();if(view==="ideasView"){renderIdeas(state.data.ideas);if(full){renderTemplates(state.data.templates||[]);renderLogoOptions(state.data.references||[]);renderAssets(state.data.references||[])}}else if(view==="draftsView"){if(full)renderDrafts(state.data.drafts);else updateDraftStatuses(state.data.drafts)}else if(view==="calendarView")renderCalendar();else if(view==="opsView")renderOps(state.data);else if(view==="companyView"&&state.company)renderCompany(state.company);else if(view==="platformView"){renderOrganizations(state.organizations);if(state.platformUsage)renderPlatformUsage(state.platformUsage)}}
async function refresh(background=false){try{if(!state.me){state.me=await api("api/me");document.querySelector("#currentUser").textContent=state.me.username;if(state.me.is_admin){document.querySelector("#userAdmin").hidden=false;await refreshUsers()}if(state.me.is_super_admin){document.querySelector("#platformTab").hidden=false;await refreshOrganizations();await refreshPlatformUsage()}await refreshCompany()}const d=await api("api/dashboard");state.data=d;renderActive(!background);document.querySelector("#updated").textContent=new Date().toLocaleTimeString("uk-UA")}catch(e){if(e.message.includes("увійти"))location.reload();else if(!background)toast(e.message,true)}}
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
function showSocialVariant(v){state.socialPlatform=v.platform;document.querySelector("#socialVariant").hidden=false;document.querySelector("#socialPlatform").textContent=({instagram:"Instagram",linkedin:"LinkedIn",facebook:"Facebook",x:"X"}[v.platform]||v.platform);document.querySelector("#socialTitle").value=v.title;document.querySelector("#socialText").value=v.text_content;document.querySelector("#socialImage").src=`api/drafts/${state.draftId}/social-variants/${v.platform}/image?v=${Date.now()}`;document.querySelector("#downloadSocialImage").href=`api/drafts/${state.draftId}/social-variants/${v.platform}/image?download=true`}
async function openDraft(id){try{const d=await api(`api/drafts/${id}`);const rubric=state.data?.rubrics?.find(r=>r.slug===d.product);const fixed=!!rubric?.fixed_cover_path;state.draftId=id;state.currentDraft=d;state.socialVariants=await api(`api/drafts/${id}/social-variants`);state.socialPlatform=null;document.querySelector("#socialVariant").hidden=true;document.querySelector("#editorTitle").value=d.title;document.querySelector("#editorCaption").value=d.caption_html;document.querySelector("#editorLink").value=d.link_url||"";document.querySelector("#titleVariants").innerHTML=jsonList(d.title_options).map(x=>`<button data-title-option="${esc(x)}">${esc(x)}</button>`).join("");document.querySelector("#ctaVariants").innerHTML=jsonList(d.cta_options).map(x=>`<button data-cta-option="${esc(x)}">${esc(x)}</button>`).join("");document.querySelectorAll("[data-title-option]").forEach(b=>b.onclick=()=>document.querySelector("#editorTitle").value=b.dataset.titleOption);document.querySelectorAll("[data-cta-option]").forEach(b=>b.onclick=()=>{const area=document.querySelector("#editorCaption");area.value=`${area.value.trim()}\\n\\n${b.dataset.ctaOption}`});const favorite=document.querySelector("#favoriteDraft");favorite.textContent=d.is_favorite?"★ У прикладах":"☆ До прикладів";favorite.classList.toggle("favorite",!!d.is_favorite);document.querySelector("#editorTemplate").value=state.templateId;document.querySelector("#editorLogo").value=document.querySelector("#logoReference").value;document.querySelector("#editorCompanyLogo").value=document.querySelector("#companyLogoReference").value;document.querySelector("#editorImage").src=`api/drafts/${id}/image`;document.querySelector("#regenImage").hidden=fixed;document.querySelector("#editorVisualSettings").hidden=fixed;document.querySelector("#cancelSchedule").style.display=d.status==="scheduled"?"inline-block":"none";document.querySelectorAll("[data-social-generate]").forEach(b=>{const existing=state.socialVariants.find(v=>v.platform===b.dataset.socialGenerate);b.textContent=existing?`Відкрити ${b.dataset.socialGenerate}`:b.textContent});document.querySelector("#editor").showModal()}catch(e){toast(e.message,true)}}
document.querySelector("#closeEditor").onclick=()=>document.querySelector("#editor").close();
document.querySelector("#saveDraft").onclick=async()=>{const b=document.querySelector("#saveDraft");await loading(b,async()=>{await api(`api/drafts/${state.draftId}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#editorTitle").value,caption_html:document.querySelector("#editorCaption").value,link_url:document.querySelector("#editorLink").value})});toast("Зміни збережено");await refresh(true)},"Збереження")};
document.querySelector("#regenImage").onclick=async()=>{const b=document.querySelector("#regenImage");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/regenerate-image`,{method:"POST",body:JSON.stringify(generationPayload())});document.querySelector("#editor").close();toast("Нова картинка поставлена в чергу");await refresh(true)},"Додається")};
document.querySelector("#regenText").onclick=async()=>{const b=document.querySelector("#regenText");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/regenerate-text`,{method:"POST",body:JSON.stringify(generationPayload())});document.querySelector("#editor").close();toast("Нова версія тексту поставлена в чергу");await refresh(true)},"Додається")};
document.querySelector("#proofreadDraft").onclick=async()=>{const b=document.querySelector("#proofreadDraft");await loading(b,async()=>{const d=await api(`api/drafts/${state.draftId}/proofread`,{method:"POST",body:JSON.stringify({text_model:document.querySelector("#textModel").value})});document.querySelector("#editorCaption").value=d.caption_html;toast("Українську та термінологію перевірено")},"Перевіряється")};
document.querySelector("#favoriteDraft").onclick=async()=>{const b=document.querySelector("#favoriteDraft");const next=!state.currentDraft?.is_favorite;await loading(b,async()=>{const d=await api(`api/drafts/${state.draftId}/favorite`,{method:"PUT",body:JSON.stringify({favorite:next})});state.currentDraft=d;b.textContent=d.is_favorite?"★ У прикладах":"☆ До прикладів";b.classList.toggle("favorite",!!d.is_favorite);toast(d.is_favorite?"Пост додано до прикладів":"Пост прибрано з прикладів");await refresh(true)},"Зберігається")};
document.querySelector("#publishNow").onclick=async()=>{const channel=state.company?.telegram?.channel_id||"підключений канал";if(!confirm(`Опублікувати цей пост у ${channel} зараз?`))return;const b=document.querySelector("#publishNow");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/publish`,{method:"POST"});document.querySelector("#editor").close();toast("Пост опубліковано");await refresh()},"Публікується")};
document.querySelector("#scheduleDraft").onclick=async()=>{const value=document.querySelector("#scheduleAt").value;if(!value)return toast("Оберіть дату і час");const b=document.querySelector("#scheduleDraft");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});document.querySelector("#editor").close();toast("Публікацію заплановано");await refresh()},"Планується")};
document.querySelector("#cancelSchedule").onclick=async()=>{const b=document.querySelector("#cancelSchedule");await loading(b,async()=>{await api(`api/drafts/${state.draftId}/cancel-schedule`,{method:"POST"});document.querySelector("#editor").close();toast("Розклад скасовано");await refresh()},"Скасовується")};
document.querySelector("#calendarPrev").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar()};
document.querySelector("#calendarNext").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar()};
document.querySelector("#calendarToday").onclick=()=>{state.calendarDate=new Date();renderCalendar()};
document.querySelector("#logout").onclick=async()=>{await api("api/logout",{method:"POST"});location.reload()};
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
document.querySelector("#saveSocialVariant").onclick=async()=>{const v=await api(`api/drafts/${state.draftId}/social-variants/${state.socialPlatform}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#socialTitle").value,text_content:document.querySelector("#socialText").value})});state.socialVariants=state.socialVariants.map(x=>x.platform===v.platform?v:x);showSocialVariant(v);toast("Версію збережено")};
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
