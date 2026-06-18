import asyncio
import html
import re
from pathlib import Path

from voicerhub_bot.config import Settings
from voicerhub_bot.instagram import (
    InstagramApiError,
    MetaInstagramClient,
    admin_public_url,
    signed_media_token,
)
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.storage import TenantRepository


def instagram_caption(draft: dict, variant: dict | None) -> str:
    if variant:
        title = str(variant.get("title") or draft.get("title") or "").strip()
        text = str(variant.get("text_content") or "").strip()
        hashtags = variant.get("hashtags") or []
        tags = " ".join(
            tag if str(tag).startswith("#") else f"#{tag}"
            for tag in hashtags
            if str(tag).strip()
        )
        return "\n\n".join(part for part in (title, text, tags) if part)[:2200]
    caption = re.sub(r"<br\s*/?>", "\n", str(draft.get("caption_html") or ""), flags=re.I)
    caption = re.sub(r"<[^>]+>", "", caption)
    return html.unescape(caption).strip()[:2200]


class InstagramPublisher:
    def __init__(
        self,
        *,
        settings: Settings,
        saas: SaasRepository,
        tenants: TenantRepository,
        client: MetaInstagramClient | None = None,
    ) -> None:
        self.settings = settings
        self.saas = saas
        self.tenants = tenants
        self.client = client or MetaInstagramClient(settings)

    def media_url(
        self,
        *,
        organization_id: int,
        draft_id: int,
        variant: str = "",
    ) -> str:
        expires_at, signature = signed_media_token(
            self.settings,
            organization_id=organization_id,
            draft_id=draft_id,
            variant=variant,
        )
        suffix = f"?org={organization_id}&variant={variant}&exp={expires_at}&sig={signature}"
        return admin_public_url(self.settings, f"media/instagram/{draft_id}{suffix}")

    async def publish_job(self, job_id: int) -> dict:
        job = self.saas.update_social_publish_job(
            job_id,
            status="publishing",
            error="",
            increment_attempts=True,
        )
        try:
            return await self._publish(job)
        except Exception as exc:
            message = str(exc)
            self.saas.update_social_publish_job(job_id, status="failed", error=message)
            if job.get("connection_id"):
                self.saas.set_social_connection_error(int(job["connection_id"]), message)
            raise

    async def _publish(self, job: dict) -> dict:
        organization_id = int(job["organization_id"])
        repository = self.tenants.for_organization(organization_id)
        draft = repository.draft_record(int(job["draft_id"]))
        connection = self.saas.social_connection_by_platform(
            organization_id,
            "instagram",
            include_token=True,
            active_only=True,
        )
        variant = None
        variant_name = ""
        try:
            variant = repository.get_social_variant(int(job["draft_id"]), "instagram")
            variant_name = "instagram"
        except KeyError:
            variant = None
        image_path = Path(
            (variant or {}).get("image_path")
            or draft.get("image_path")
            or ""
        )
        if not image_path.is_file():
            raise InstagramApiError("Для Instagram потрібне готове зображення.")
        image_url = self.media_url(
            organization_id=organization_id,
            draft_id=int(job["draft_id"]),
            variant=variant_name,
        )
        container_id = await self.client.create_image_container(
            instagram_id=str(connection["external_account_id"]),
            access_token=str(connection["access_token"]),
            image_url=image_url,
            caption=instagram_caption(draft, variant),
        )
        self.saas.update_social_publish_job(
            int(job["id"]),
            provider_container_id=container_id,
        )
        status = {}
        status_code = ""
        for _ in range(6):
            status = await self.client.container_status(
                container_id,
                str(connection["access_token"]),
            )
            status_code = str(status.get("status_code") or "").upper()
            if status_code in {"", "FINISHED", "PUBLISHED"}:
                break
            if status_code in {"ERROR", "EXPIRED"}:
                break
            await asyncio.sleep(2)
        if status_code and status_code not in {"FINISHED", "PUBLISHED"}:
            raise InstagramApiError(
                f"Meta ще не підготувала контейнер Instagram: {status_code}",
                raw=status,
            )
        media_id = await self.client.publish_container(
            instagram_id=str(connection["external_account_id"]),
            access_token=str(connection["access_token"]),
            container_id=container_id,
        )
        permalink = await self.client.permalink(media_id, str(connection["access_token"]))
        return self.saas.update_social_publish_job(
            int(job["id"]),
            status="published",
            provider_media_id=media_id,
            permalink=permalink,
            error="",
            published=True,
        )

    def create_job_for_draft(
        self,
        *,
        organization_id: int,
        draft_id: int,
        scheduled_at: str | None,
        status: str,
        created_by_user_id: int | None,
    ) -> dict:
        repository = self.tenants.for_organization(organization_id)
        draft = repository.draft_record(draft_id)
        if not draft.get("image_path"):
            raise InstagramApiError("Для Instagram потрібне готове зображення.")
        connection = self.saas.social_connection_by_platform(
            organization_id,
            "instagram",
            include_token=False,
            active_only=True,
        )
        variant_id = None
        try:
            variant_id = int(repository.get_social_variant(draft_id, "instagram")["id"])
        except KeyError:
            variant_id = None
        return self.saas.create_social_publish_job(
            organization_id=organization_id,
            draft_id=draft_id,
            platform="instagram",
            connection_id=int(connection["id"]),
            variant_id=variant_id,
            media_kind="feed_image",
            scheduled_at=scheduled_at,
            status=status,
            created_by_user_id=created_by_user_id,
        )
