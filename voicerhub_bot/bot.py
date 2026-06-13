import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from voicerhub_bot.config import Settings
from voicerhub_bot.content import ContentGenerator
from voicerhub_bot.images import ImageGenerator
from voicerhub_bot.models import Product
from voicerhub_bot.rendering import render_caption
from voicerhub_bot.storage import DraftRepository


logger = logging.getLogger(__name__)


class EditorialBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = DraftRepository(settings.database_path)
        self.content = ContentGenerator(settings.openai_api_key, settings.openai_text_model)
        self.images = ImageGenerator(
            settings.openai_api_key,
            settings.openai_image_model,
            settings.generated_dir,
            settings.brand_logo_path,
        )

    def build_application(self) -> Application:
        application = Application.builder().token(self.settings.telegram_bot_token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("id", self.show_id))
        application.add_handler(CommandHandler("draft", self.create_draft))
        application.add_handler(CommandHandler("preview", self.preview))
        application.add_handler(CommandHandler("jobs", self.jobs))
        application.add_handler(CallbackQueryHandler(self.handle_action, pattern=r"^(publish|redo):\d+$"))
        application.add_error_handler(self.handle_error)
        return application

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._authorized(update):
            return
        await update.effective_message.reply_text(
            "Редактор VoicerHub готовий.\n\n"
            "<code>/draft tony тема</code>\n"
            "<code>/draft voicer тема</code>\n"
            "<code>/draft general тема</code>",
            parse_mode=ParseMode.HTML,
        )

    async def show_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        await update.effective_message.reply_text(f"Ваш Telegram user ID: {user_id}")

    async def create_draft(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._authorized(update):
            return
        if len(context.args) < 2:
            await update.effective_message.reply_text(
                "Формат: /draft tony|voicer|general тема поста"
            )
            return

        try:
            product = Product(context.args[0].lower())
        except ValueError:
            await update.effective_message.reply_text("Продукт: tony, voicer або general.")
            return

        topic = " ".join(context.args[1:]).strip()
        job = self.repository.create_job(topic, product.value, update.effective_chat.id)
        await update.effective_message.reply_text(
            f"Завдання #{job.id} поставлено в чергу Batch.\n"
            "Я повідомлю, коли текст і зображення будуть готові."
        )

    async def preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._authorized(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Формат: /preview номер_чернетки")
            return
        try:
            await self._send_preview(
                update.effective_chat.id,
                context,
                int(context.args[0]),
            )
        except (KeyError, FileNotFoundError):
            await update.effective_message.reply_text("Чернетку не знайдено або вона ще не готова.")

    async def jobs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._authorized(update):
            return
        dashboard = self.repository.dashboard()
        counts = dashboard["job_counts"]
        text = "\n".join(f"{status}: {count}" for status, count in sorted(counts.items()))
        await update.effective_message.reply_text(text or "Завдань поки немає.")

    async def handle_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        if not await self._authorized(update):
            return

        action, raw_draft_id = query.data.split(":", 1)
        draft_id = int(raw_draft_id)
        draft = self.repository.get(draft_id)

        if action == "publish":
            if draft.status != "draft":
                await query.edit_message_reply_markup(reply_markup=None)
                await query.message.reply_text("Цю чернетку вже опубліковано.")
                return
            with Path(draft.image_path).open("rb") as image:
                await context.bot.send_photo(
                    chat_id=self.settings.telegram_channel,
                    photo=image,
                    caption=draft.caption_html,
                    parse_mode=ParseMode.HTML,
                )
            self.repository.mark_published(draft_id)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"Опубліковано в {self.settings.telegram_channel}.")
            return

        if action == "redo":
            job = self.repository.create_job(
                f"{draft.topic}. Створи суттєво інший ракурс і композицію.",
                draft.product,
                query.message.chat_id,
            )
            await query.message.reply_text(f"Нова версія поставлена в Batch як завдання #{job.id}.")

    async def _generate_draft(
        self,
        topic: str,
        product: Product,
        feedback: str | None = None,
    ):
        post = None
        caption = ""
        for attempt in range(2):
            retry_feedback = feedback
            if attempt:
                retry_feedback = (
                    f"{feedback or ''} The previous caption was too long. "
                    "Make this version substantially shorter."
                ).strip()
            post = await self.content.generate(
                topic,
                product,
                self.repository.recent_titles(),
                retry_feedback,
            )
            try:
                caption = render_caption(post)
                break
            except ValueError:
                if attempt == 1:
                    raise

        if post is None:
            raise RuntimeError("Post generation returned no result.")
        image_path = await self.images.generate(post.visual_title, post.image_prompt)
        return self.repository.create(
            topic=topic,
            product=post.product.value,
            title=post.title,
            visual_title=post.visual_title,
            caption_html=caption,
            image_prompt=post.image_prompt,
            image_path=str(image_path),
        )

    async def _send_preview(
        self,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        draft_id: int,
    ) -> None:
        draft = self.repository.get(draft_id)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Опублікувати", callback_data=f"publish:{draft.id}"),
                    InlineKeyboardButton("Інша версія", callback_data=f"redo:{draft.id}"),
                ]
            ]
        )
        with Path(draft.image_path).open("rb") as image:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=draft.caption_html,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    async def _authorized(self, update: Update) -> bool:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id in self.settings.admin_ids:
            return True
        if update.effective_message:
            await update.effective_message.reply_text(
                "Немає доступу. Надішліть /id і додайте цей ID до ADMIN_USER_IDS."
            )
        elif update.callback_query:
            await update.callback_query.answer("Немає доступу.", show_alert=True)
        return False

    async def handle_error(
        self,
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        logger.exception("Unhandled Telegram error", exc_info=context.error)
