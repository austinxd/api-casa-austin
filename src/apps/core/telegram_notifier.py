import os
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('apps')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

logger.debug(f"TELEGRAM_BOT_TOKEN: {TELEGRAM_BOT_TOKEN}")
logger.debug(f"CHAT_ID: {CHAT_ID}")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def run_async(func):
    """Runs the given async function using the event loop"""
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(func(*args, **kwargs))
        loop.close()
    return wrapper

@run_async
async def async_send_telegram_message(message):
    try:
        logger.debug("Enviando mensaje asincrónicamente a Telegram.")
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logger.debug("Mensaje enviado.")
    except TelegramError as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

def send_telegram_message(message):
    logger.debug(f"Preparando para enviar mensaje: {message}")
    executor = ThreadPoolExecutor()
    executor.submit(async_send_telegram_message, message)
    logger.debug("Mensaje enviado a través del executor.")
