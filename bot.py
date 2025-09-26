import logging
import os
import sqlite3
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------- Конфигурация -----------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден! Задай его через переменные окружения.")

CHANNEL_ID = -1003187110992  # свой channel id

DB_PATH = "bot_final.db"

# ----------------- Логирование -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ----------------- Инициализация БД -----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        username TEXT,
        full_name TEXT,
        place TEXT
    )
    """
    )

    cur.execute(
        """
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        description TEXT,
        photo_id TEXT,
        status TEXT,
        channel_msg_id INTEGER,
        created_at TEXT,
        assigned_to TEXT
    )
    """
    )

    conn.commit()
    conn.close()


# ----------------- Работа с БД -----------------
def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, full_name, place FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "username": row[1], "full_name": row[2], "place": row[3]}


def save_user(user_id, username, full_name, place):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (user_id, username, full_name, place) VALUES (?, ?, ?, ?)",
        (user_id, username, full_name, place),
    )
    conn.commit()
    conn.close()


def save_ticket_to_db(user_id, description, photo_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO tickets (user_id, description, photo_id, status, channel_msg_id, created_at, assigned_to) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, description, photo_id, "Активный", None, created_at, None),
    )
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def update_ticket_channel_msg_id(ticket_id, channel_msg_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET channel_msg_id=? WHERE id=?", (channel_msg_id, ticket_id))
    conn.commit()
    conn.close()


def set_ticket_status(ticket_id, status):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))
    conn.commit()
    conn.close()


def set_ticket_assignee(ticket_id, assignee):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET assigned_to=? WHERE id=?", (assignee, ticket_id))
    conn.commit()
    conn.close()


def get_ticket(ticket_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, description, photo_id, status, channel_msg_id, created_at, assigned_to FROM tickets WHERE id=?",
        (ticket_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "description": row[2],
        "photo": row[3],
        "status": row[4],
        "channel_msg_id": row[5],
        "created_at": row[6],
        "assigned_to": row[7],
    }


def get_user_tickets(user_id, limit=5):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, description, status, created_at FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def close_previous_active_tickets_in_db(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, channel_msg_id, photo_id FROM tickets WHERE user_id=? AND status='Активный'", (user_id,))
    rows = cur.fetchall()
    for (tid, channel_msg_id, photo_id) in rows:
        cur.execute("UPDATE tickets SET status='Закрытый' WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return rows


# ----------------- UI: Reply Keyboard -----------------
def main_menu_kb():
    kb = [
        [KeyboardButton("🆕 Создать тикет")],
        [KeyboardButton("📂 Мои тикеты"), KeyboardButton("📖 FAQ")],
        [KeyboardButton("⚙️ Изменить данные")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# ----------------- Хендлеры -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text("Добро пожаловать обратно! Вы в главном меню:", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("Привет! Давай зарегистрируем тебя.\nНапиши *Имя и Фамилию*:", parse_mode="Markdown")
        context.user_data["step"] = "get_full_name"


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    step = context.user_data.get("step")

    if step == "get_full_name":
        context.user_data["full_name"] = text.strip()
        context.user_data["step"] = "get_place"
        await update.message.reply_text("Отлично. Теперь напиши, где ты сидишь (этаж, кабинет и т.д.):")
        return

    if step == "get_place":
        place = text.strip()
        full_name = context.user_data.get("full_name")
        save_user(
            update.effective_user.id,
            update.effective_user.username,
            full_name,
            place,
        )
        context.user_data.clear()
        await update.message.reply_text(f"✅ Регистрация завершена!\n\n👤 {full_name}\n📍 {place}", reply_markup=main_menu_kb())
        return

    if text == "🆕 Создать тикет":
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Ты не зарегистрирован. Напиши /start чтобы пройти регистрацию.")
            return
        await update.message.reply_text("Опиши проблему (несколько строк). Если нужно — потом отправишь фото.")
        context.user_data["step"] = "ticket_description"
        return

    if step == "ticket_description":
        description = text.strip()
        context.user_data["ticket_description"] = description

        kb = [
            [InlineKeyboardButton("📎 Прикрепить фото", callback_data="add_photo")],
            [InlineKeyboardButton("⏭️ Без фото", callback_data="skip_photo")],
        ]
        await update.message.reply_text("Хотите прикрепить фото?", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data["step"] = "ticket_ask_photo"
        return

    if text == "📂 Мои тикеты":
        rows = get_user_tickets(update.effective_user.id, limit=5)
        if not rows:
            await update.message.reply_text("У вас пока нет тикетов.", reply_markup=main_menu_kb())
            return
        text_out = "📂 Ваши последние 5 тикетов:\n\n"
        for r in rows:
            tid, desc, status, created = r
            text_out += f"#{tid} | {created}\n📌 {status}\n📝 {desc[:120]}{'...' if len(desc) > 120 else ''}\n\n"
        await update.message.reply_text(text_out, reply_markup=main_menu_kb())
        return

    if text == "📖 FAQ":
        await faq_files(update, context)
        return

    if text == "⚙️ Изменить данные":
        await update.message.reply_text("Введи новое *Имя и Фамилию*:", parse_mode="Markdown")
        context.user_data["step"] = "get_full_name"
        return

    await update.message.reply_text("Я не понял. Используй кнопки меню ниже.", reply_markup=main_menu_kb())


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step == "waiting_photo" and update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["ticket_photo_id"] = photo_file_id
        await create_ticket_from_userdata(update, context)
    else:
        await update.message.reply_text("Фото принято, но бот не ожидал фото. Нажми 'Создать тикет'.")


# ----------------- Callback кнопки -----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "add_photo":
        context.user_data["step"] = "waiting_photo"
        await query.edit_message_text("Отправь фото (можно одно). После фото тикет будет создан.")
        return

    if data == "skip_photo":
        await query.edit_message_text("Создаём тикет без фото...")
        await create_ticket_from_userdata(query, context)
        return

    # Взятие заявки
    if data.startswith("assign_"):
        tid = int(data.split("_", 1)[1])
        t = get_ticket(tid)
        if not t:
            await query.edit_message_text("Тикет не найден.")
            return

        if t.get("assigned_to"):
            await query.answer("Этот тикет уже взят другим админом.", show_alert=True)
            return

        admin = query.from_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name
        set_ticket_assignee(tid, admin_name)
        set_ticket_status(tid, "В работе")

        u = get_user(t["user_id"])
        user_name_display = u["full_name"] if u else f"User {t['user_id']}"
        user_link = f"https://t.me/{u['username']}" if u and u["username"] else f"tg://user?id={u['user_id']}"

        new_text = (f"🎫 Тикет #{tid}\n"
                    f"👤 {user_name_display}\n"
                    f"💬 {t['description']}\n"
                    f"📌 Статус: В работе\n"
                    f"🤝 Взял: {admin_name}")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить взятие", callback_data=f"unassign_{tid}")],
            [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{tid}")]
        ])

        if t["photo"]:
            await context.bot.edit_message_caption(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], caption=new_text, reply_markup=kb)
        else:
            await context.bot.edit_message_text(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], text=new_text, reply_markup=kb)

        # Личное сообщение админу
        try:
            if u and u["username"]:
                user_link = f"https://t.me/{u['username']}"
            else:
                user_link = f"tg://user?id={u['user_id']}"

            kb_private = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Открыть чат с коллегой", url=user_link)]
            ])

            await context.bot.send_message(
                admin.id,
                f"✅ Вы взяли заявку #{tid}\nНажмите кнопку ниже, чтобы открыть чат с клиентом:",
                reply_markup=kb_private
    )
        except Exception as e:
            logger.error(f"Не удалось отправить ЛС админу: {e}")

    # Отмена взятия
    if data.startswith("unassign_"):
        tid = int(data.split("_", 1)[1])
        t = get_ticket(tid)
        if not t:
            await query.edit_message_text("Тикет не найден.")
            return

        admin = query.from_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name

        if t.get("assigned_to") != admin_name:
            await query.answer("Вы не брали этот тикет.", show_alert=True)
            return

        set_ticket_assignee(tid, None)
        set_ticket_status(tid, "Активный")

        u = get_user(t["user_id"])
        user_name_display = u["full_name"] if u else f"User {t['user_id']}"

        new_text = (f"🎫 Тикет #{tid}\n"
                    f"👤 {user_name_display}\n"
                    f"💬 {t['description']}\n"
                    f"📌 Статус: Активный")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Взять заявку", callback_data=f"assign_{tid}")],
            [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{tid}")]
        ])

        if t["photo"]:
            await context.bot.edit_message_caption(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], caption=new_text, reply_markup=kb)
        else:
            await context.bot.edit_message_text(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], text=new_text, reply_markup=kb)
        return

    # Закрытие тикета
    if data.startswith("close_"):
        tid = int(data.split("_", 1)[1])
        t = get_ticket(tid)
        if not t:
            await query.edit_message_text("Тикет не найден.")
            return

        set_ticket_status(tid, "Закрытый")
        admin = query.from_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name

        u = get_user(t["user_id"])
        user_name_display = u["full_name"] if u else f"User {t['user_id']}"

        new_text = (f"🎫 Тикет #{tid}\n"
                    f"👤 {user_name_display}\n"
                    f"💬 {t['description']}\n"
                    f"📌 Статус: Закрыт админом {admin_name}")

        try:
            if t["photo"]:
                await context.bot.edit_message_caption(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], caption=new_text)
            else:
                await context.bot.edit_message_text(chat_id=CHANNEL_ID, message_id=t["channel_msg_id"], text=new_text)
        except Exception as e:
            logger.error(f"Не удалось обновить сообщение в канале: {e}")

        try:
            await context.bot.send_message(t["user_id"], f"❌ Ваш тикет #{tid} был закрыт администратором {admin_name}.")
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {t['user_id']}: {e}")

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return


# ----------------- Создание тикета -----------------
async def create_ticket_from_userdata(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update_or_query, Update):
        message = update_or_query.message
        user_obj = update_or_query.effective_user
    else:
        message = update_or_query.message
        user_obj = update_or_query.from_user

    user = get_user(user_obj.id)
    if not user:
        await message.reply_text("Ошибка: пользователь не найден в базе. Напиши /start.")
        return

    description = context.user_data.get("ticket_description", "")
    photo_id = context.user_data.get("ticket_photo_id")

    prev_rows = close_previous_active_tickets_in_db(user_obj.id)
    for tid, channel_msg_id, prev_photo_id in prev_rows:
        try:
            old_ticket = get_ticket(tid)
            if not old_ticket:
                continue
            u = get_user(old_ticket["user_id"])
            user_name_display = u["full_name"] if u else f"User {old_ticket['user_id']}"
            text_old = (f"🎫 Тикет #{tid}\n"
                        f"👤 {user_name_display}\n"
                        f"💬 {old_ticket['description']}\n"
                        f"📌 Статус: Закрыт (создан новый тикет)")
            if old_ticket["photo"]:
                await context.bot.edit_message_caption(chat_id=CHANNEL_ID, message_id=old_ticket["channel_msg_id"], caption=text_old)
            else:
                await context.bot.edit_message_text(chat_id=CHANNEL_ID, message_id=old_ticket["channel_msg_id"], text=text_old)
        except Exception as e:
            logger.error(f"Не удалось обновить старый тикет #{tid} в канале: {e}")

    ticket_id = save_ticket_to_db(user_obj.id, description, photo_id)

    text = (f"🆕 Заявка #{ticket_id}\n"
            f"👤 {user['full_name']}\n"
            f"🏢 {user['place']}\n"
            f"💬 {description}\n"
            f"📌 Статус: Активный")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 Взять заявку", callback_data=f"assign_{ticket_id}")],
        [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{ticket_id}")]
    ])

    try:
        if photo_id:
            sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photo_id, caption=text, reply_markup=kb)
        else:
            sent = await context.bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=kb)
        channel_msg_id = sent.message_id
        update_ticket_channel_msg_id(ticket_id, channel_msg_id)
    except Exception as e:
        logger.error(f"Не удалось отправить тикет в канал: {e}")
        await message.reply_text("Произошла ошибка при отправке тикета в канал. Тикет создан локально.", reply_markup=main_menu_kb())
        context.user_data.clear()
        return

    try:
        await message.reply_text(f"✅ Тикет #{ticket_id} создан и отправлен в канал. Ожидайте ответа оператора.", reply_markup=main_menu_kb())
    except Exception:
        pass

    context.user_data.clear()


# ----------------- FAQ -----------------
async def faq_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = ["Как_поменять_пароль_или_что_делать_если_заблокирована_учетная_запись.pdf", "ПОДКЛЮЧЕНИЕ_К_ТВ_КРУГЛЫЙ_ЗАЛ_1_1.pdf", "Создание_заявки_через_шаблон_формы.pdf", "Что надо вводить в FORTIK.pdf"]

    sent_any = False
    for f in files:
        if os.path.exists(f):
            try:
                with open(f, "rb") as doc:
                    await update.message.reply_document(document=doc, caption=os.path.basename(f))
                    sent_any = True
            except Exception as e:
                logger.error(f"Ошибка отправки {f}: {e}")
        else:
            logger.info(f"Файл не найден: {f}")

    if not sent_any:
        await update.message.reply_text("❌ FAQ файлы пока недоступны.")


async def set_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать / показать меню"),
    ])


# ----------------- Запуск приложения -----------------
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.post_init = set_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
