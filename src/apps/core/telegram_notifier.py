import os
import asyncio
from telegram import Bot

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = 'your-chat-id'  # Reemplaza esto con el ID del chat donde quieres recibir las notificaciones

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def async_send_telegram_message(message):
    await bot.send_message(chat_id=CHAT_ID, text=message)

def send_telegram_message(message):
    asyncio.run(async_send_telegram_message(message))
