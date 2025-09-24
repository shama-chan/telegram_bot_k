import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import os
import sqlite3

# === Инициализация базы ===
def init_db():
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        place TEXT,
        desc TEXT,
        photo_id TEXT,
        status TEXT,
        user_id INTEGER,
        username TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_ticket(data):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO tickets (user, place, desc, photo_id, status, user_id, username)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user"],
        data["place"],
        data["desc"],
        data.get("photo"),
        data["status"],
        data["user_id"],
        data["username"]
    ))
    conn.commit()
    ticket_id = cur.lastrowid
    conn.close()
    return ticket_id

def get_ticket(ticket_id):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("SELECT id, user, place, desc, photo_id, status, user_id, username FROM tickets WHERE id=?", (ticket_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user": row[1],
        "place": row[2],
        "desc": row[3],
        "photo": row[4],
        "status": row[5],
        "user_id": row[6],
        "username": row[7],
    }

def get_user_tickets(user_id, is_admin=False):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    if is_admin:
        cur.execute("SELECT id, status FROM tickets ORDER BY id DESC")
    else:
        cur.execute("SELECT id, status FROM tickets WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# === Читаем токен ===
TOKEN = os.getenv("BOT_TOKEN")

# ID твоего канала
CHANNEL_ID = -1003187110992

# Список админов (замени на реальные ID)
ADMINS = [5206699138]

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
            photo = update.message.photo[-1]
            context.user_data["photo_id"] = photo.file_id
            await create_ticket(update, context)
        except Exception:
            await update.message.reply_text(f"Ваша заявка принята, ожидайте ответа оператора ✅")
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

    elif query.data.startswith("ticket_"):
        tid = int(query.data.split("_")[1])
        t = get_ticket(tid)
        if not t:
            await query.edit_message_text("Тикет не найден.")
            return

        text = (f"🎫 Тикет #{tid}\n"
                f"👤 {t['user']}\n"
                f"🏢 {t['place']}\n"
                f"💬 {t['desc']}\n"
                f"📌 Статус: {t['status']}")
        await query.edit_message_text(text)


# === Создание заявки ===
async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket_id = save_ticket({
        "user": context.user_data["name"],
        "place": context.user_data["place"],
        "desc": context.user_data["problem"],
        "photo": context.user_data.get("photo_id"),
        "status": "Новая",
        "user_id": update.effective_user.id,
        "username": update.effective_user.username
    })

    t = get_ticket(ticket_id)
    text = (f"🆕 Заявка #{ticket_id}\n"
            f"👤 {t['user']}\n"
            f"🏢 {t['place']}\n"
            f"💬 {t['desc']}")

    # Кнопка "Перейти к заявке"
    if t["username"]:
        button_url = f"https://t.me/{t['username']}"
    else:
        button_url = f"tg://user?id={t['user_id']}"

    kb = [[InlineKeyboardButton("Перейти к заявке", url=button_url)]]

    if t["photo"]:
        await context.bot.send_photo(
            CHANNEL_ID,
            t["photo"],
            caption=text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await context.bot.send_message(
            CHANNEL_ID,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # Отправка копии админам
    for admin_id in ADMINS:
        if t["photo"]:
            msg = await context.bot.send_photo(admin_id, t["photo"], caption=text)
        else:
            msg = await context.bot.send_message(admin_id, text)

        context.chat_data[f"ticket_{msg.message_id}"] = ticket_id

    await update.message.reply_text(f"Заявка #{ticket_id} отправлена ✅")
    context.user_data.clear()


# === Ответ админа пользователю ===
async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return

    if not update.message.reply_to_message:
        return

    ticket_id = context.chat_data.get(f"ticket_{update.message.reply_to_message.message_id}")
    if not ticket_id:
        return

    t = get_ticket(ticket_id)
    if not t:
        return

    user_id = t["user_id"]
    text = f"✉️ Ответ от техподдержки:\n{update.message.text}"

    await context.bot.send_message(user_id, text)
    await update.message.reply_text("✅ Ответ отправлен пользователю")


# === Список тикетов ===
async def list_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMINS
    rows = get_user_tickets(user_id, is_admin)

    kb = []
    for tid, status in rows:
        kb.append([InlineKeyboardButton(f"🎫 Тикет #{tid} ({status})", callback_data=f"ticket_{tid}")])

    if not kb:
        await update.message.reply_text("У вас пока нет тикетов.")
        return

    await update.message.reply_text("Ваши тикеты:", reply_markup=InlineKeyboardMarkup(kb))


# === Установка меню команд ===
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать регистрацию"),
        BotCommand("tickets", "Мои заявки")
    ])


# === Запуск ===
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.post_init = set_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tickets", list_tickets))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.REPLY, admin_reply))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
