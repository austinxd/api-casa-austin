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
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(func(*args, **kwargs))
            else:
                loop.run_until_complete(func(*args, **kwargs))
        except RuntimeError as e:
            logger.error(f"Error in event loop: {e}")
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(func(*args, **kwargs))
        except TelegramError as e:
            logger.error(f"Error enviando mensaje a Telegram: {e}")
    return wrapper

@run_async
async def async_send_telegram_message(message, image_url=None):
    try:
        logger.debug("Enviando mensaje asincrónicamente a Telegram.")
        if image_url:
            await bot.send_photo(chat_id=CHAT_ID, photo=image_url, caption=message)
        else:
            await bot.send_message(chat_id=CHAT_ID, text=message)
        logger.debug("Mensaje enviado.")
    except TelegramError as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

def send_telegram_message(message, image_url=None):
    logger.debug(f"Preparando para enviar mensaje: {message}")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(async_send_telegram_message(message, image_url))
        else:
            loop.run_until_complete(async_send_telegram_message(message, image_url))
    except RuntimeError as e:
        logger.error(f"Error in event loop: {e}")
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(async_send_telegram_message(message, image_url))
    logger.debug("Mensaje enviado a través del executor.")
