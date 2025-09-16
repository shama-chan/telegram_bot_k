import os
import asyncio
from telegram import Bot

# Читаем токен из переменной окружения
TOKEN = os.getenv("BOT_TOKEN")

# Твой channel_id (важно: без кавычек, как число!)
CHANNEL_ID = -1002936995160


async def main():
    if not TOKEN:
        raise ValueError("Переменная окружения BOT_TOKEN не задана!")

    bot = Bot(TOKEN)

    try:
        msg = await bot.send_message(CHANNEL_ID, "Тестовое сообщение от бота ✅")
        print("Успешно отправлено:", msg)
    except Exception as e:
        print("Ошибка при отправке:", e)


if __name__ == "__main__":
    asyncio.run(main())
