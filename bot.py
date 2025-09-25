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
        username TEXT,
        channel_msg_id INTEGER
    )
    """)
    conn.commit()
    conn.close()


def save_ticket(data):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET status='Закрытый' WHERE user_id=? AND status='Активный'", (data["user_id"],))
    cur.execute("""
    INSERT INTO tickets (user, place, desc, photo_id, status, user_id, username, channel_msg_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["user"],
        data["place"],
        data["desc"],
        data.get("photo"),
        data["status"],
        data["user_id"],
        data["username"],
        None
    ))
    conn.commit()
    ticket_id = cur.lastrowid
    conn.close()
    return ticket_id


def update_channel_msg_id(ticket_id, msg_id):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET channel_msg_id=? WHERE id=?", (msg_id, ticket_id))
    conn.commit()
    conn.close()


def get_ticket(ticket_id):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user, place, desc, photo_id, status, user_id, username, channel_msg_id
        FROM tickets WHERE id=?
    """, (ticket_id,))
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
        "channel_msg_id": row[8],
    }


def get_user_tickets(user_id, is_admin=False):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    if is_admin:
        cur.execute("SELECT id, status FROM tickets ORDER BY id DESC")
    else:
        cur.execute("SELECT id, status FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def set_ticket_status(ticket_id, status):
    conn = sqlite3.connect("tickets.db")
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))
    conn.commit()
    conn.close()


# === Читаем токен ===
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = -1003187110992

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# === Старт ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добро пожаловать! Введите ваше имя и фамилию:")
    context.user_data["step"] = "name"


# === Обработка шагов ===
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
    if context.user_data.get("step") == "waiting_photo" and update.message.photo:
        context.user_data["photo_id"] = update.message.photo[-1].file_id
        await create_ticket(update, context)
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
        await query.edit_message_text("Вы выбрали: без фото")
        await create_ticket(update, context)

    elif query.data.startswith("close_"):
        tid = int(query.data.split("_")[1])
        t = get_ticket(tid)
        if not t:
            return

        set_ticket_status(tid, "Закрытый")

        # кто закрыл тикет
        admin = update.effective_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name

        text = (f"🎫 Тикет #{tid}\n"
                f"👤 {t['user']}\n"
                f"🏢 {t['place']}\n"
                f"💬 {t['desc']}\n"
                f"📌 Статус: Закрыт админом {admin_name}")

        try:
            if t["photo"]:
                await context.bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=t["channel_msg_id"],
                    caption=text
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=t["channel_msg_id"],
                    text=text
                )
        except Exception as e:
            logger.error(f"Ошибка обновления сообщения тикета {tid}: {e}")

        # уведомление пользователю
        try:
            await context.bot.send_message(
                t["user_id"],
                f"❌ Ваш тикет #{tid} был закрыт администратором {admin_name}."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {t['user_id']}: {e}")

    elif query.data.startswith("ticket_"):
        tid = int(query.data.split("_")[1])
        t = get_ticket(tid)
        if not t:
            return
        text = (f"🎫 Тикет #{tid}\n"
                f"👤 {t['user']}\n"
                f"🏢 {t['place']}\n"
                f"💬 {t['desc']}\n"
                f"📌 Статус: {t['status']}")
        kb = []
        if t["status"] == "Активный":
            kb.append([InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{tid}")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb) if kb else None)


# === Создание тикета ===
async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # закрываем старые тикеты
    old_tickets = get_user_tickets(user_id, is_admin=True)
    for tid, status in old_tickets:
        t = get_ticket(tid)
        if t and t["status"] == "Активный" and t["channel_msg_id"]:
            set_ticket_status(tid, "Закрытый")
            text_old = (f"🎫 Тикет #{tid}\n"
                        f"👤 {t['user']}\n"
                        f"🏢 {t['place']}\n"
                        f"💬 {t['desc']}\n"
                        f"📌 Статус: Закрыт автоматически (новый тикет создан)")
            try:
                if t["photo"]:
                    await context.bot.edit_message_caption(
                        chat_id=CHANNEL_ID,
                        message_id=t["channel_msg_id"],
                        caption=text_old
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=t["channel_msg_id"],
                        text=text_old
                    )
            except Exception as e:
                logger.error(f"Не удалось обновить старый тикет {tid}: {e}")

    ticket_id = save_ticket({
        "user": context.user_data["name"],
        "place": context.user_data["place"],
        "desc": context.user_data["problem"],
        "photo": context.user_data.get("photo_id"),
        "status": "Активный",
        "user_id": user_id,
        "username": update.effective_user.username
    })

    t = get_ticket(ticket_id)
    text = (f"🆕 Заявка #{ticket_id}\n"
            f"👤 {t['user']}\n"
            f"🏢 {t['place']}\n"
            f"💬 {t['desc']}\n"
            f"📌 Статус: {t['status']}")

    await update.effective_message.reply_text(f"Заявка #{ticket_id} отправлена ✅ Ожидайте ответа оператора.")

    button_url = f"https://t.me/{t['username']}" if t["username"] else f"tg://user?id={t['user_id']}"
    kb = [
        [InlineKeyboardButton("Перейти к заявке", url=button_url)],
        [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{t['id']}")]
    ]

    if t["photo"]:
        msg = await context.bot.send_photo(
            CHANNEL_ID,
            t["photo"],
            caption=text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        msg = await context.bot.send_message(
            CHANNEL_ID,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    update_channel_msg_id(ticket_id, msg.message_id)
    context.user_data.clear()


# === Список тикетов ===
async def list_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = get_user_tickets(user_id, is_admin=False)
    kb = []
    for tid, status in rows:
        kb.append([InlineKeyboardButton(f"🎫 Тикет #{tid} ({status})", callback_data=f"ticket_{tid}")])
    if not kb:
        await update.message.reply_text("У вас пока нет тикетов.")
        return
    await update.message.reply_text("Ваши тикеты:", reply_markup=InlineKeyboardMarkup(kb))


# === FAQ ===
async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = ["file1.pdf", "file2.pdf"]
    for f in files:
        try:
            with open(f, "rb") as doc:
                await update.message.reply_document(document=doc, caption=f"📄 {os.path.basename(f)}")
        except Exception as e:
            logger.error(f"Не удалось отправить {f}: {e}")


# === Команды ===
async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать регистрацию"),
        BotCommand("tickets", "Мои заявки"),
        BotCommand("faq", "Часто задаваемые вопросы (PDF)")
    ])


# === Запуск ===
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.post_init = set_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tickets", list_tickets))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
