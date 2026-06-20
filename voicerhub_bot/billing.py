import json
import secrets
from datetime import datetime, timedelta, timezone

from telegram import Bot, LabeledPrice, Update

from voicerhub_bot.saas import SaasRepository


STAR_PLANS = {
    "start": {
        "code": "start",
        "name": "Start",
        "tagline": "Для невеликої команди та стабільного контент-ритму.",
        "stars": 399,
        "users": 3,
        "channels": 1,
        "publications": 30,
        "ai_budget": 8.0,
        "text_generations": 60,
        "image_generations": 30,
        "features": [
            "AI-теми, тексти та зображення",
            "Контент-календар і відкладена публікація",
            "Власні рубрики, шаблони та логотипи",
            "Telegram, Instagram і LinkedIn формати",
        ],
    },
    "growth": {
        "code": "growth",
        "name": "Growth",
        "tagline": "Для маркетингової команди, яка публікує регулярно.",
        "stars": 999,
        "users": 10,
        "channels": 1,
        "publications": 120,
        "ai_budget": 25.0,
        "text_generations": 250,
        "image_generations": 120,
        "popular": True,
        "features": [
            "Усе зі Start",
            "Серії постів і контент-плани на місяць",
            "250 текстових і 120 візуальних генерацій на місяць",
            "Аналітика використання за користувачами",
        ],
    },
    "scale": {
        "code": "scale",
        "name": "Scale",
        "tagline": "Для великого контент-виробництва та кількох команд.",
        "stars": 2199,
        "users": 30,
        "channels": 1,
        "publications": 300,
        "ai_budget": 60.0,
        "text_generations": 700,
        "image_generations": 300,
        "features": [
            "Усе з Growth",
            "До 300 публікацій на місяць",
            "Збільшений ліміт генерації зображень",
            "Пріоритетна підтримка",
        ],
    },
}


def public_plans() -> list[dict]:
    plans = []
    for plan in STAR_PLANS.values():
        public = dict(plan)
        public.pop("ai_budget", None)
        plans.append(public)
    return plans


class BillingService:
    def __init__(self, repository: SaasRepository, bot_token: str) -> None:
        self.repository = repository
        self.bot = Bot(bot_token)
        self.offset: int | None = None

    async def create_checkout(
        self,
        *,
        organization_id: int,
        user_id: int,
        plan_code: str,
    ) -> dict:
        plan = STAR_PLANS.get(plan_code)
        if plan is None:
            raise KeyError("Unknown plan")
        payload = f"cs:{organization_id}:{user_id}:{plan_code}:{secrets.token_hex(8)}"
        order = self.repository.create_billing_order(
            organization_id=organization_id,
            user_id=user_id,
            plan_code=plan_code,
            amount_stars=plan["stars"],
            payload=payload,
        )
        invoice_url = await self.bot.create_invoice_link(
            title=f"Content Studio · {plan['name']}",
            description=(
                f"Підписка на 30 днів: {plan['publications']} публікацій, "
                f"{plan['text_generations']} текстових і "
                f"{plan['image_generations']} image-генерацій, "
                f"до {plan['users']} користувачів."
            ),
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(plan["name"], plan["stars"])],
            provider_token="",
            subscription_period=timedelta(days=30),
        )
        return {**order, "invoice_url": invoice_url, "plan": dict(plan)}

    async def poll(self) -> None:
        updates = await self.bot.get_updates(
            offset=self.offset,
            timeout=2,
            allowed_updates=["message", "pre_checkout_query"],
        )
        for update in updates:
            self.offset = update.update_id + 1
            await self._handle_update(update)

    async def _handle_update(self, update: Update) -> None:
        if update.pre_checkout_query:
            query = update.pre_checkout_query
            order = self.repository.billing_order_by_payload(query.invoice_payload)
            valid = bool(
                order
                and query.currency == "XTR"
                and query.total_amount == order["amount_stars"]
                and order["status"] in {"pending", "paid"}
            )
            await self.bot.answer_pre_checkout_query(
                query.id,
                ok=valid,
                error_message=None if valid else "Рахунок недійсний або вже закритий.",
            )
            return

        message = update.effective_message
        if message is None:
            return
        if message.successful_payment:
            payment = message.successful_payment
            order = self.repository.billing_order_by_payload(payment.invoice_payload)
            if order is None:
                return
            plan = STAR_PLANS.get(order["plan_code"])
            if plan is None:
                return
            expiration = getattr(payment, "subscription_expiration_date", None)
            if expiration is None:
                expiration = datetime.now(timezone.utc) + timedelta(days=30)
            self.repository.complete_star_payment(
                order_id=order["id"],
                telegram_user_id=message.from_user.id if message.from_user else None,
                telegram_payment_charge_id=payment.telegram_payment_charge_id,
                amount_stars=payment.total_amount,
                plan=plan,
                expires_at=expiration,
                raw=json.dumps(payment.to_dict(), ensure_ascii=False, default=str),
            )
            await message.reply_text(
                f"Оплату отримано. Тариф {plan['name']} активовано до "
                f"{expiration.strftime('%d.%m.%Y')}."
            )
            return

        text = (message.text or "").split()[0].lower()
        if text == "/terms":
            await message.reply_text(
                "Content Studio надає цифровий доступ за передплатою на 30 днів. "
                "Оплата підтверджує згоду з лімітами обраного тарифу."
            )
        elif text in {"/support", "/paysupport"}:
            await message.reply_text(
                "Підтримка платежів Content Studio: напишіть @voicerhub."
            )
