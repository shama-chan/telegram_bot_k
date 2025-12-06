import logging
import os
import sqlite3
from datetime import datetime, timezone
from telegram import ReplyKeyboardRemove



from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, Message, User
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

# ================== Конфигурация ==================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден! Задай его через переменные окружения.")

CHANNEL_ID_ENV = os.getenv("CHANNEL_ID")
if not CHANNEL_ID_ENV:
    raise ValueError("CHANNEL_ID не найден! Задай его через переменные окружения.")
CHANNEL_ID = int(CHANNEL_ID_ENV)

DB_PATH = "bot_final.db"

STATUS_ACTIVE = "Активный"
STATUS_IN_PROGRESS = "В работе"
STATUS_CLOSED = "Закрыт"

# ================== Логирование ===================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ================== Инициализация БД ===============
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER,
            user_id INTEGER,
            stars INTEGER,
            comment TEXT,
            created_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


# ================== Время ==========================
def human_time(ts: str) -> str:
    """
    Переводит ISO8601 в локальное время 'DD.MM.YYYY HH:MM'.
    Если без tz — считаем, что это UTC.
    """
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ts


# ================== Работа с БД ====================
def db_conn():
    return sqlite3.connect(DB_PATH)

def get_user(user_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, full_name, place FROM users WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "username": row[1], "full_name": row[2], "place": row[3]}

def save_user(user_id, username, full_name, place):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, username, full_name, place)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          username=excluded.username,
          full_name=excluded.full_name,
          place=excluded.place
        """,
        (user_id, username, full_name, place),
    )
    conn.commit()
    conn.close()

def save_ticket_to_db(user_id, description, photo_id):
    conn = db_conn()
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        INSERT INTO tickets
          (user_id, description, photo_id, status, channel_msg_id, created_at, assigned_to)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, description, photo_id, STATUS_ACTIVE, None, created_at, None),
    )
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id

def update_ticket_channel_msg_id(ticket_id, channel_msg_id):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET channel_msg_id=? WHERE id=?", (channel_msg_id, ticket_id))
    conn.commit()
    conn.close()

def set_ticket_status(ticket_id, status):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))
    conn.commit()
    conn.close()

def set_ticket_assignee(ticket_id, assignee_or_none):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET assigned_to=? WHERE id=?", (assignee_or_none, ticket_id))
    conn.commit()
    conn.close()

def get_ticket(ticket_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, description, photo_id, status, channel_msg_id, created_at, assigned_to
        FROM tickets WHERE id=?
        """,
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
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, description, status, created_at
        FROM tickets WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def close_previous_active_tickets_in_db(user_id: int):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, channel_msg_id, photo_id FROM tickets WHERE user_id=? AND status=?",
        (user_id, STATUS_ACTIVE),
    )
    rows = cur.fetchall()
    for (tid, _channel_msg_id, _photo_id) in rows:
        cur.execute("UPDATE tickets SET status=? WHERE id=?", (STATUS_CLOSED, tid))
    conn.commit()
    conn.close()
    return rows


# ================== Рендер карточки =================
def render_ticket_text(t: dict, u: dict | None, *, with_feedback: bool = False, stars: int | None = None, comment: str | None = None) -> str:
    """
    Собирает HTML-текст для карточки тикета.
    """
    user_name = (u["full_name"] if u else f"User {t['user_id']}") if t else "—"
    created_h = human_time(t["created_at"]) if t and t.get("created_at") else "—"
    assigned = t.get("assigned_to") if t else None

    base = (
        f"📂 <b>Тикет #{t['id']}</b>\n"
        f"👤 {user_name}\n"
        f"🕒 {created_h}\n"
        f"📝 {t['description']}\n"
    )

    if t["status"] == STATUS_ACTIVE:
        status_line = f"📌 <b>Статус:</b> {STATUS_ACTIVE}"
    elif t["status"] == STATUS_IN_PROGRESS:
        status_line = f"📌 <b>Статус:</b> {STATUS_IN_PROGRESS}\n🤝 <b>Взял:</b> {assigned}"
    else:  # закрыт
        status_line = f"📌 <b>Статус:</b> {STATUS_CLOSED} ✅" + (f"\n👨‍💻 <b>Админ:</b> {assigned}" if assigned else "")

    text = base + status_line

    if with_feedback and stars:
        stars_display = "⭐️" * int(stars)
        text += (
            f"\n\n📈 <b>Оценка:</b> {stars_display}\n"
            f"💬 <b>Отзыв:</b> {comment or '—'}"
        )

    return text


# ================== UI: клавиатура =================
def main_menu_kb():
    kb = [
        [KeyboardButton("🆕 Создать тикет")],
        [KeyboardButton("📂 Мои тикеты"), KeyboardButton("📖 FAQ")],
        [KeyboardButton("⚙️ Изменить данные")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# ================== Хендлеры =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            "Добро пожаловать обратно! Вы в главном меню:",
            reply_markup=main_menu_kb(),
        )
    else:
        await update.message.reply_text(
            "Привет! Давайте зарегистрируем вас.\nНапишите *Имя и Фамилию*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data["step"] = "get_full_name"


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    step = context.user_data.get("step")

    # 🔹 Защита от случайных кнопок во время регистрации или редактирования
    if step in {"get_full_name", "get_place", "edit_full_name", "edit_place"}:
        if text in {"🆕 Создать тикет", "📂 Мои тикеты", "📖 FAQ", "⚙️ Изменить данные"}:
            await update.message.reply_text(
                "❗ Пожалуйста, завершите ввод данных перед использованием меню."
            )
            return


    # --- стадия отзыва ---
    if step == "feedback_comment":
        if text in {"🆕 Создать тикет", "📂 Мои тикеты", "📖 FAQ", "⚙️ Изменить данные"}:
            await update.message.reply_text("❗ Сначала напишите отзыв текстом 👇")
            return

        tid = context.user_data.get("feedback_ticket")
        stars = context.user_data.get("feedback_stars")
        if not (tid and stars):
            context.user_data.clear()
            await update.message.reply_text("Что-то сломалось. Начните заново, пожалуйста.", reply_markup=main_menu_kb())
            return

        conn = db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO feedback (ticket_id, user_id, stars, comment, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tid, update.effective_user.id, stars, text, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        await update.message.reply_text("Спасибо за отзыв! 🙏", reply_markup=main_menu_kb())

        # Обновляем исходную карточку тикета в канале (добавляем оценку и отзыв)
        t = get_ticket(tid)
        u = get_user(t["user_id"]) if t else None
        new_text = render_ticket_text(t, u, with_feedback=True, stars=int(stars), comment=text)
        try:
            await safe_edit_channel_message(context, t, new_text, reply_markup=None)
        except Exception as e:
            logger.error(f"Не удалось обновить карточку тикета #{tid} с отзывом: {e}")

        context.user_data.clear()
        return

    # --- регистрация ---
    if step == "get_full_name":
        context.user_data["full_name"] = text
        context.user_data["step"] = "get_place"
        await update.message.reply_text("Отлично. Теперь напишите, где вы сидите (этаж, кабинет и т.д.):")
        return

    if step == "get_place":
        place = text
        full_name = context.user_data.get("full_name")
        save_user(
            update.effective_user.id,
            update.effective_user.username,
            full_name,
            place,
        )
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Регистрация завершена!\n\n👤 {full_name}\n📍 {place}",
            reply_markup=main_menu_kb(),
        )
        return

    # --- кнопки меню ---
    if text == "🆕 Создать тикет":
        user = get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Ты не зарегистрирован. Напиши /start чтобы пройти регистрацию.")
            return
        await update.message.reply_text("Опишите проблему (несколько строк). Можно будет прикрепить фото.")
        context.user_data["step"] = "ticket_description"
        return

    if text == "📂 Мои тикеты":
        rows = get_user_tickets(update.effective_user.id, limit=5)
        if not rows:
            await update.message.reply_text("У вас пока нет тикетов.", reply_markup=main_menu_kb())
            return
        text_out = "📂 Ваши последние 5 тикетов:\n\n"
        for r in rows:
            tid, desc, status, created = r
            created_h = human_time(created)
            short = (desc or "")[:120]
            text_out += (
                f"#{tid} | {created_h}\n"
                f"📌 {status}\n"
                f"📝 {short}{'...' if len(desc or '') > 120 else ''}\n\n"
            )
        await update.message.reply_text(text_out, reply_markup=main_menu_kb())
        return

    if text == "📖 FAQ":
        await faq_files(update, context)
        return

    if text == "⚙️ Изменить данные":
        context.user_data["step"] = "edit_full_name"
        await update.message.reply_text("Введите новое *Имя и Фамилию*:", parse_mode="Markdown")
        return

    if step == "edit_full_name":
        context.user_data["new_full_name"] = text
        context.user_data["step"] = "edit_place"
        await update.message.reply_text("Теперь введите новое место (этаж, кабинет и т.д.):")
        return

    if step == "edit_place":
        new_place = text
        new_full_name = context.user_data.get("new_full_name")
        if not new_full_name:
            context.user_data.clear()
            await update.message.reply_text("Ошибка: имя не указано. Повторите через 'Изменить данные'.")
            return

        save_user(
            update.effective_user.id,
            update.effective_user.username,
            new_full_name,
            new_place,
        )
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Данные обновлены!\n\n👤 {new_full_name}\n📍 {new_place}",
            reply_markup=main_menu_kb(),
        )
        return

    if step == "ticket_description":
        description = text
        context.user_data["ticket_description"] = description
        kb = [
            [InlineKeyboardButton("📎 Прикрепить фото", callback_data="add_photo")],
            [InlineKeyboardButton("⏭️ Без фото", callback_data="skip_photo")],
        ]
        await update.message.reply_text("Хотите прикрепить фото?", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data["step"] = "ticket_ask_photo"
        return

    # --- fallback ---
    await update.message.reply_text("Бот не понял. Используйте кнопки ниже.", reply_markup=main_menu_kb())


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step == "waiting_photo" and update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data["ticket_photo_id"] = photo_file_id
        await create_ticket_from_userdata(update.message, context)
    else:
        await update.message.reply_text("Фото получено, но я не ожидал фото. Нажмите 'Создать тикет'.")


# ================== Callback-кнопки =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    # загрузка фото
    if data == "add_photo":
        context.user_data["step"] = "waiting_photo"
        await query.edit_message_text("Отправьте фото. После фото тикет будет создан.")
        return

    if data == "skip_photo":
        await query.edit_message_text("Создаём тикет без фото…")
        await create_ticket_from_userdata(query.from_user, context)  # важно: берем не message, а from_user
        return

    # взять заявку
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
        set_ticket_status(tid, STATUS_IN_PROGRESS)
        t = get_ticket(tid)  # обновлённые данные
        new_text = render_ticket_text(t, get_user(t["user_id"]), with_feedback=False)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отменить взятие", callback_data=f"unassign_{tid}")],
            [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{tid}")]
        ])
        await safe_edit_channel_message(context, t, new_text, kb)

        # личка админу — открыть чат с пользователем
        try:
            u = get_user(t["user_id"])
            if u and u.get("username"):
                user_link = f"https://t.me/{u['username']}"
            else:
                user_link = f"tg://user?id={u['user_id']}" if u else None

            if user_link:
                kb_private = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Открыть чат с пользователем", url=user_link)]])
                await context.bot.send_message(
                    admin.id,
                    f"✅ Вы взяли заявку #{tid}. Нажмите кнопку ниже, чтобы открыть чат:",
                    reply_markup=kb_private,
                )
        except Exception as e:
            logger.error(f"Не удалось отправить ЛС админу: {e}")
        return

    # отменить взятие
    if data.startswith("unassign_"):
        tid = int(data.split("_", 1)[1])
        t = get_ticket(tid)
        if not t:
            await query.edit_message_text("Тикет не найден.")
            return

        admin = query.from_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name

        if (t.get("assigned_to") or "") != admin_name:
            await query.answer("Вы не брали этот тикет.", show_alert=True)
            return

        set_ticket_assignee(tid, None)
        set_ticket_status(tid, STATUS_ACTIVE)
        t = get_ticket(tid)
        new_text = render_ticket_text(t, get_user(t["user_id"]), with_feedback=False)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Взять заявку", callback_data=f"assign_{tid}")],
            [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{tid}")]
        ])
        await safe_edit_channel_message(context, t, new_text, kb)
        return

    # закрыть тикет
    if data.startswith("close_"):
        tid = int(data.split("_", 1)[1])
        set_ticket_status(tid, STATUS_CLOSED)
        # сохраняем админа, если его ещё нет
        t_tmp = get_ticket(tid)
        admin = query.from_user
        admin_name = f"@{admin.username}" if admin.username else admin.full_name
        if not t_tmp.get("assigned_to"):
            set_ticket_assignee(tid, admin_name)

        t = get_ticket(tid)
        new_text = render_ticket_text(t, get_user(t["user_id"]), with_feedback=False)
        await safe_edit_channel_message(context, t, new_text, None)

        # уведомить пользователя и запросить оценку
        try:
            await context.bot.send_message(
                t["user_id"],
                f"✅ Ваш тикет #{tid} был закрыт администратором {admin_name}."
            )
            kb_feedback = InlineKeyboardMarkup([[
                InlineKeyboardButton("1⭐️", callback_data=f"rate_{tid}_1"),
                InlineKeyboardButton("2⭐️", callback_data=f"rate_{tid}_2"),
                InlineKeyboardButton("3⭐️", callback_data=f"rate_{tid}_3"),
                InlineKeyboardButton("4⭐️", callback_data=f"rate_{tid}_4"),
                InlineKeyboardButton("5⭐️", callback_data=f"rate_{tid}_5"),
            ]])
            await context.bot.send_message(
                t["user_id"],
                f"🙏 Пожалуйста, оцените работу по тикету #{tid}:",
                reply_markup=kb_feedback,
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {t['user_id']}: {e}")
        return

    # выбор звёзд
    if data.startswith("rate_"):
        try:
            _, tid_str, stars_str = data.split("_")
            tid = int(tid_str)
            stars = int(stars_str)
        except Exception:
            await query.edit_message_text("Некорректная оценка.")
            return

        context.user_data["step"] = "feedback_comment"
        context.user_data["feedback_ticket"] = tid
        context.user_data["feedback_stars"] = stars

        await query.edit_message_text(f"Вы поставили {stars}⭐️.\nТеперь оставьте короткий отзыв текстом:")
        return


# ================== Вспомогательное =================
async def safe_edit_channel_message(context: ContextTypes.DEFAULT_TYPE, ticket: dict, new_text: str, reply_markup: InlineKeyboardMarkup | None):
    """
    Аккуратно обновляет сообщение в канале в зависимости от того, есть ли фото (caption) или нет (text).
    """
    try:
        if ticket.get("photo"):
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=ticket["channel_msg_id"],
                caption=new_text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=ticket["channel_msg_id"],
                text=new_text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"Не удалось обновить сообщение в канале (ticket #{ticket['id']}): {e}")


# ================== Создание тикета =================
async def create_ticket_from_userdata(source, context: ContextTypes.DEFAULT_TYPE):
    """
    source: telegram.Message (когда пришло фото) ИЛИ telegram.User (когда нажали 'Без фото').
    """
    # куда отвечать
    if isinstance(source, Message):
        user_obj = source.from_user
        async def reply(text, **kw): return await source.reply_text(text, **kw)
    elif isinstance(source, User):
        user_obj = source
        async def reply(text, **kw): return await context.bot.send_message(chat_id=user_obj.id, text=text, **kw)
    else:
        logger.error(f"create_ticket_from_userdata: неподдерживаемый тип {type(source)}")
        return

    user = get_user(user_obj.id)
    if not user:
        await reply("Ошибка: пользователь не найден в базе. Напиши /start.")
        return

    description = context.user_data.get("ticket_description", "") or ""
    photo_id = context.user_data.get("ticket_photo_id")

    # закрываем старые активные тикеты
    prev_rows = close_previous_active_tickets_in_db(user_obj.id)
    for tid, _channel_msg_id, _prev_photo_id in prev_rows:
        try:
            old_ticket = get_ticket(tid)
            if not old_ticket:
                continue
            u = get_user(old_ticket["user_id"])
            text_old = render_ticket_text(old_ticket, u, with_feedback=False)
            await safe_edit_channel_message(context, old_ticket, text_old, None)
        except Exception as e:
            logger.error(f"Не удалось обновить старый тикет #{tid} в канале: {e}")

    # создаём новый тикет
    ticket_id = save_ticket_to_db(user_obj.id, description, photo_id)
    t = get_ticket(ticket_id)
    text = render_ticket_text(t, user, with_feedback=False)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 Взять заявку", callback_data=f"assign_{ticket_id}")],
        [InlineKeyboardButton("✅ Закрыть тикет", callback_data=f"close_{ticket_id}")]
    ])

    try:
        if photo_id:
            sent = await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photo_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            sent = await context.bot.send_message(chat_id=CHANNEL_ID, text=text, reply_markup=kb, parse_mode="HTML")
        update_ticket_channel_msg_id(ticket_id, sent.message_id)
    except Exception as e:
        logger.error(f"Не удалось отправить тикет в канал: {e}")
        await reply("Произошла ошибка при отправке тикета в канал. Тикет создан локально.", reply_markup=main_menu_kb())
        context.user_data.clear()
        return

    await reply(
        f"✅ Тикет #{ticket_id} создан и отправлен в канал. Ожидайте ответа оператора.",
        reply_markup=main_menu_kb(),
    )

    # сброс шага создания
    for key in ("step", "ticket_description", "ticket_photo_id"):
        context.user_data.pop(key, None)


# ================== FAQ ============================
async def faq_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = [
        "Как_поменять_пароль_или_что_делать_если_заблокирована_учетная_запись.pdf",
        "ПОДКЛЮЧЕНИЕ_К_ТВ_КРУГЛЫЙ_ЗАЛ_1_1.pdf",
        "Создание_заявки_через_шаблон_формы.pdf",
        "Что надо вводить в FORTIK.pdf",
    ]

    sent_any = False
    for f in files:
        if os.path.exists(f):
            try:
                with open(f, "rb") as doc:
                    await update.message.reply_document(document=doc)
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


# ================== Запуск =========================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.post_init = set_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен в режиме polling...")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


