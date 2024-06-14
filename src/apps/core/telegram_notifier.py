import os
import asyncio
from telegram import Bot
from concurrent.futures import ThreadPoolExecutor

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = 'your-chat-id'  # Reemplaza esto con el ID del chat donde quieres recibir las notificaciones

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
    await bot.send_message(chat_id=CHAT_ID, text=message)

def send_telegram_message(message):
    executor = ThreadPoolExecutor()
    executor.submit(async_send_telegram_message, message)
