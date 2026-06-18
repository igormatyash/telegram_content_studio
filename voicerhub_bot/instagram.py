import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from voicerhub_bot.config import Settings


class InstagramSetupError(RuntimeError):
    pass


class InstagramApiError(RuntimeError):
    def __init__(self, message: str, *, raw: dict | None = None) -> None:
        super().__init__(message)
        self.raw = raw or {}


@dataclass(frozen=True)
class InstagramAccount:
    access_token: str
    page_id: str
    page_name: str
    instagram_id: str
    username: str
    display_name: str
    account_type: str = "business"
    permissions: list[str] | None = None
    expires_at: str = ""


def instagram_configured(settings: Settings) -> bool:
    return bool(
        settings.instagram_enabled
        and settings.meta_app_id
        and settings.meta_app_secret
        and (settings.meta_redirect_uri or settings.public_app_url)
    )


def instagram_redirect_uri(settings: Settings) -> str:
    if settings.meta_redirect_uri:
        return settings.meta_redirect_uri
    base = settings.public_app_url.rstrip("/")
    if not base:
        raise InstagramSetupError(
            "PUBLIC_APP_URL або META_REDIRECT_URI потрібні для Instagram OAuth"
        )
    return f"{base}{settings.admin_base_path.rstrip('/')}/oauth/instagram/callback"


def instagram_scopes(settings: Settings) -> str:
    return ",".join(
        item.strip()
        for item in settings.meta_instagram_scopes.split(",")
        if item.strip()
    )


def instagram_connect_url(settings: Settings, state: str) -> str:
    if not instagram_configured(settings):
        raise InstagramSetupError("Instagram інтеграцію ще не налаштовано")
    query = urlencode(
        {
            "client_id": settings.meta_app_id,
            "redirect_uri": instagram_redirect_uri(settings),
            "state": state,
            "scope": instagram_scopes(settings),
            "response_type": "code",
        }
    )
    return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{query}"


def admin_public_url(settings: Settings, path: str) -> str:
    base = settings.public_app_url.rstrip("/")
    if not base:
        raise InstagramSetupError(
            "PUBLIC_APP_URL потрібен, щоб Meta могла отримати зображення."
        )
    admin_base = settings.admin_base_path.rstrip("/")
    if admin_base and not base.endswith(admin_base):
        base = f"{base}{admin_base}"
    return f"{base}/{path.lstrip('/')}"


def _secret(settings: Settings) -> bytes:
    return (
        settings.app_encryption_key
        or settings.privacy_hash_salt
        or settings.admin_password
        or settings.product_name
    ).encode()


def signed_media_token(
    settings: Settings,
    *,
    organization_id: int,
    draft_id: int,
    variant: str = "",
    expires_in: int = 20 * 60,
) -> tuple[int, str]:
    expires_at = int(time.time()) + expires_in
    payload = f"{organization_id}:{draft_id}:{variant}:{expires_at}"
    signature = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
    return expires_at, signature


def verify_media_signature(
    settings: Settings,
    *,
    organization_id: int,
    draft_id: int,
    variant: str,
    expires_at: int,
    signature: str,
) -> bool:
    if expires_at < int(time.time()):
        return False
    payload = f"{organization_id}:{draft_id}:{variant}:{expires_at}"
    expected = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class MetaInstagramClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = f"https://graph.facebook.com/{settings.meta_graph_version}"

    async def _get(self, path: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
        return self._json(response)

    async def _post(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/{path.lstrip('/')}", data=data)
        return self._json(response)

    def _json(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.is_error or "error" in payload:
            error = payload.get("error") or {}
            message = error.get("message") or response.text or "Meta API error"
            raise InstagramApiError(self.user_message(message), raw=payload)
        return payload

    @staticmethod
    def user_message(message: str) -> str:
        lowered = message.lower()
        if "permission" in lowered or "scope" in lowered:
            return "Meta не надала потрібні права для Instagram-публікації."
        if "media" in lowered or "image" in lowered:
            return "Meta не змогла отримати або обробити зображення для Instagram."
        if "token" in lowered or "session" in lowered:
            return "Instagram-сесія недійсна або потребує повторного підключення."
        return message[:500]

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return await self._get(
            "oauth/access_token",
            {
                "client_id": self.settings.meta_app_id,
                "client_secret": self.settings.meta_app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )

    async def long_lived_token(self, short_token: str) -> dict:
        return await self._get(
            "oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": self.settings.meta_app_id,
                "client_secret": self.settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )

    async def resolve_account(self, access_token: str) -> InstagramAccount:
        pages = await self._get(
            "me/accounts",
            {
                "access_token": access_token,
                "fields": (
                    "id,name,access_token,"
                    "instagram_business_account{id,username,name,profile_picture_url}"
                ),
            },
        )
        for page in pages.get("data", []):
            instagram = page.get("instagram_business_account") or {}
            if instagram.get("id"):
                return InstagramAccount(
                    access_token=page.get("access_token") or access_token,
                    page_id=str(page.get("id") or ""),
                    page_name=str(page.get("name") or ""),
                    instagram_id=str(instagram["id"]),
                    username=str(instagram.get("username") or ""),
                    display_name=str(instagram.get("name") or instagram.get("username") or ""),
                    permissions=instagram_scopes(self.settings).split(","),
                )
        raise InstagramApiError(
            "Не знайдено Instagram Business або Creator account, прив’язаний до Facebook Page.",
            raw=pages,
        )

    async def create_image_container(
        self,
        *,
        instagram_id: str,
        access_token: str,
        image_url: str,
        caption: str,
    ) -> str:
        payload = await self._post(
            f"{instagram_id}/media",
            {
                "access_token": access_token,
                "image_url": image_url,
                "caption": caption,
            },
        )
        return str(payload["id"])

    async def container_status(self, container_id: str, access_token: str) -> dict:
        return await self._get(
            container_id,
            {
                "access_token": access_token,
                "fields": "status_code,status",
            },
        )

    async def publish_container(
        self,
        *,
        instagram_id: str,
        access_token: str,
        container_id: str,
    ) -> str:
        payload = await self._post(
            f"{instagram_id}/media_publish",
            {
                "access_token": access_token,
                "creation_id": container_id,
            },
        )
        return str(payload["id"])

    async def permalink(self, media_id: str, access_token: str) -> str:
        payload = await self._get(
            media_id,
            {
                "access_token": access_token,
                "fields": "permalink",
            },
        )
        return str(payload.get("permalink") or "")
