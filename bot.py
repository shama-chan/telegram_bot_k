import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import os

# Читаем токен из переменной окружения
TOKEN = os.getenv("BOT_TOKEN")

# ID твоего канала
CHANNEL_ID = -1002936995160

# Хранилище заявок в памяти (пока без базы)
tickets = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# === Старт (регистрация) ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добро пожаловать! Введите ваше имя и фамилию:")
    context.user_data["step"] = "name"


# === Обработка шагов регистрации ===
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    text = update.message.text

    if step == "name":
        context.user_data["name"] = text
        await update.message.reply_text("Теперь введите место, где вы сидите в офисе:")
        context.user_data["step"] = "place"

    elif step == "place":
        context.user_data["place"] = text
        await update.message.reply_text("Регистрация завершена ✅\nНапишите описание вашей проблемы:")
        context.user_data["step"] = "problem"

    elif step == "problem":
        context.user_data["problem"] = text
        kb = [[
            InlineKeyboardButton("Прикрепить фото", callback_data="add_photo"),
            InlineKeyboardButton("Пропустить", callback_data="skip_photo")
        ]]
        await update.message.reply_text("Хотите прикрепить фото?", reply_markup=InlineKeyboardMarkup(kb))

    else:
        await update.message.reply_text("Не понял. Напишите /start чтобы начать заново.")



# === Фото ===
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")

    if step == "waiting_photo" and update.message.photo:
        try:
            # Берем самое большое фото
            photo = update.message.photo[-1]

            # Сохраняем именно file_id (а не file_path)
            context.user_data["photo_id"] = photo.file_id

            # Создаем тикет
            await create_ticket(update, context)

        except Exception as e:
            await update.message.reply_text(f"Ошибка при обработке фото: {e}")
    else:
        await update.message.reply_text("Ожидается фото. Напишите /start, чтобы начать заново.")


# === Обработка кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_photo":
        context.user_data["step"] = "waiting_photo"
        await query.edit_message_text("Отправьте фото вашей проблемы.")

    elif query.data == "skip_photo":
        await create_ticket(update, context)




# === Создание заявки ===
async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket_id = len(tickets) + 1
    tickets[ticket_id] = {
        "user": context.user_data["name"],
        "place": context.user_data["place"],
        "desc": context.user_data["problem"],
        "photo": context.user_data.get("photo_id"),
        "status": "Новая",
        "user_id": update.effective_user.id,
    }

    text = (f"🆕 Заявка #{ticket_id}\n"
            f"👤 {tickets[ticket_id]['user']}\n"
            f"🏢 {tickets[ticket_id]['place']}\n"
            f"💬 {tickets[ticket_id]['desc']}")

    # Кнопка "Перейти к заявке" = открыть чат с автором
    kb = [[
        InlineKeyboardButton("Перейти к заявке", url=f"tg://user?id={tickets[ticket_id]['user_id']}")
    ]]

    # Отправка в канал
    if tickets[ticket_id]["photo"]:
        await context.bot.send_photo(
            CHANNEL_ID,
            tickets[ticket_id]["photo"],
            caption=text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await context.bot.send_message(
            CHANNEL_ID,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    await update.message.reply_text(f"Заявка #{ticket_id} отправлена в канал ✅")
    context.user_data.clear()

# === Запуск ===
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
