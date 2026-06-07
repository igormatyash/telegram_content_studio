import asyncio
import logging
from pathlib import Path

from telegram import Bot

from voicerhub_bot.config import Settings, get_settings
from voicerhub_bot.saas import SaasRepository
from voicerhub_bot.storage import DraftRepository
from voicerhub_bot.worker import GenerationWorker


logger = logging.getLogger(__name__)


def _organization_dirs(settings: Settings, organization_id: int) -> tuple[Path, Path]:
    if organization_id == 1:
        return settings.generated_dir, settings.reference_dir
    root = settings.organizations_dir / str(organization_id)
    generated = root / "generated"
    references = root / "references"
    generated.mkdir(parents=True, exist_ok=True)
    references.mkdir(parents=True, exist_ok=True)
    return generated, references


def _organization_database(settings: Settings, organization_id: int) -> Path:
    if organization_id == 1:
        return settings.database_path
    root = settings.organizations_dir / str(organization_id)
    root.mkdir(parents=True, exist_ok=True)
    return root / "content.sqlite3"


def _telegram_settings(
    settings: Settings,
    saas: SaasRepository,
    organization_id: int,
) -> tuple[str, str]:
    try:
        connection = saas.telegram_connection(organization_id, include_token=True)
    except Exception:
        connection = {}
    token = connection.get("bot_token")
    channel = connection.get("channel_id")
    if organization_id == 1:
        token = token or settings.telegram_bot_token
        channel = channel or settings.telegram_channel
    return token or settings.telegram_bot_token, channel or ""


class SaaSWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.saas = SaasRepository(settings.database_path, settings.app_encryption_key)
        self.saas.ensure_legacy_organization(channel_id=settings.telegram_channel)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("SaaS worker tick failed")
            await asyncio.sleep(30)

    async def tick(self) -> None:
        for organization_id in self.saas.organization_ids():
            try:
                await self._tick_organization(organization_id)
            except Exception:
                logger.exception("Organization %s tick failed", organization_id)

    async def _tick_organization(self, organization_id: int) -> None:
        generated_dir, reference_dir = _organization_dirs(self.settings, organization_id)
        token, channel = _telegram_settings(self.settings, self.saas, organization_id)
        org_settings = self.settings.model_copy(
            update={
                "database_path": _organization_database(self.settings, organization_id),
                "generated_dir": generated_dir,
                "reference_dir": reference_dir,
                "telegram_bot_token": token,
                "telegram_channel": channel,
                "brand_logo_path": (
                    self.settings.brand_logo_path if organization_id == 1 else None
                ),
                "monthly_publications_limit": self.saas.get_organization(
                    organization_id
                )["monthly_publications"],
            }
        )
        repository = DraftRepository(org_settings.database_path)
        worker = GenerationWorker(org_settings, repository, Bot(token))
        await worker.tick()


async def run() -> None:
    worker = SaaSWorker(get_settings())
    await worker.run_forever()


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
