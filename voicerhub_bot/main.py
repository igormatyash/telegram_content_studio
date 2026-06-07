import asyncio
import logging

from voicerhub_bot.bot import EditorialBot
from voicerhub_bot.config import get_settings
from voicerhub_bot.worker import GenerationWorker


async def run() -> None:
    settings = get_settings()
    editorial = EditorialBot(settings)
    application = editorial.build_application()
    worker = GenerationWorker(settings, editorial.repository, application.bot)

    async with application:
        await application.start()
        await application.updater.start_polling(allowed_updates=["message", "callback_query"])
        worker_task = asyncio.create_task(worker.run_forever())
        try:
            await asyncio.Event().wait()
        finally:
            worker_task.cancel()
            await application.updater.stop()
            await application.stop()


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
