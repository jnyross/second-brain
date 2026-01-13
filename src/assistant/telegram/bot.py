import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from assistant.config import settings
from assistant.services.heartbeat import start_heartbeat, stop_heartbeat
from assistant.telegram.handlers import setup_handlers

logger = logging.getLogger(__name__)


class SecondBrainBot:
    def __init__(self, token: str | None = None):
        self.token = token or settings.telegram_bot_token
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self.dp = Dispatcher()
        setup_handlers(self.dp)

    async def start(self) -> None:
        logger.info("Starting Second Brain bot...")
        # Start UptimeRobot heartbeat monitoring (if configured)
        await start_heartbeat()
        try:
            await self.dp.start_polling(self.bot)
        finally:
            await stop_heartbeat()
            await self.bot.session.close()

    async def stop(self) -> None:
        await self.dp.stop_polling()
        await self.bot.session.close()

    async def send_message(self, chat_id: int | str, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)

    async def send_briefing(self, chat_id: int | str, briefing: str) -> None:
        await self.send_message(chat_id, briefing)
