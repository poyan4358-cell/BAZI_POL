import os
import re
import random
import string
import sqlite3
import time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# تنظیمات
# =========================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

DB = "bazi_pol.db"

# =========================
# واحدهای پول
# =========================

UNITS = {
    "میل": 10**6,
    "میلیون": 10**6,
    "m": 10**6,

    "بیل": 10**9,
    "میلیارد": 10**9,
    "b": 10**9,

    "تیل": 10**12,
    "تریلیون": 10**12,
    "t": 10**12,

    "کیل": 10**15,
    "quadrillion": 10**15,

    "دیل": 10**18,
    "quintillion": 10**18,
}

# =========================
# دیتابیس
# =========================

conn = sqlite3.connect(DB, check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    wallet INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    highest INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS serials (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    used INTEGER DEFAULT 0,
    used_by INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS miners (
    user_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    count INTEGER DEFAULT 0,
    income INTEGER DEFAULT 0,
    last_update REAL,
    PRIMARY KEY(user_id, level)
)
""")

conn.commit()


# =========================
# ابزارها
# =========================

def fa_to_en(text):
    return str(text).translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹",
            "0123456789"
        )
    )


def fmt(number):
    return f"{int(number):,}"


def get_user(user):
    cur.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user.id,)
    )
    row = cur.fetchone()

    if not row:
        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or ""
        ))
        conn.commit()

        cur.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user.id,)
        )
        row = cur.fetchone()

    return row


def update_highest(user_id):
    cur.execute("""
        UPDATE users
        SET highest = MAX(highest, wallet)
        WHERE user_id = ?
    """, (user_id,))
    conn.commit()


def add_wallet(user_id, amount):
    cur.execute("""
        UPDATE users
        SET wallet = wallet + ?
        WHERE user_id = ?
    """, (amount, user_id))
    conn.commit()
    update_highest(user_id)


def remove_wallet(user_id, amount):
    cur.execute("""
        UPDATE users
        SET wallet = wallet - ?
        WHERE user_id = ?
    """, (amount, user_id))
    conn.commit()


def parse_amount(text):
    text = fa_to_en(text).strip().lower()

    text = text.replace("،", ",")
    text = text.replace("تومان", "")
    text = text.replace("سکه", "")
    text = text.strip()

    pattern = r"^\s*([\d,]+(?:\.\d+)?)\s*([a-zA-Zآ-ی]+)?\s*$"
    match = re.match(pattern, text)

    if not match:
        return None

    number_text = match.group(1).replace(",", "")
    unit = match.group(2)

    try:
        number = float(number_text)
    except ValueError:
        return None

    if number <= 0:
        return None

    multiplier = 1

    if unit:
        unit = unit.strip()

        if unit not in UNITS:
            return None

        multiplier = UNITS[unit]

    return int(number * multiplier)


def get_amount_from_game(text):
    parts = text.strip().split(maxsplit=1)

    if len(parts) < 2:
        return None

    return parse_amount(parts[1])


async def is_admin(update):
    chat = update.effective_chat

    if not chat or chat.type == "private":
        return False

    member = await chat.get_member(
        update.effective_user.id
    )

    return member.status in (
        "administrator",
        "creator"
    )


async def is_owner(update):
    chat = update.effective_chat

    if not chat or chat.type == "private":
        return False

    member = await chat.get_member(
        update.effective_user.id
    )

    return member.status == "creator"


def group_active(chat_id):
    cur.execute(
        "SELECT active FROM groups WHERE chat_id = ?",
        (chat_id,)
    )

    row = cur.fetchone()

    return bool(row and row["active"])


def set_group_active(chat_id, active):
    cur.execute("""
        INSERT INTO groups(chat_id, active)
        VALUES (?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET active = excluded.active
    """, (
        chat_id,
        int(active)
    ))

    conn.commit()


async def ensure_active(update):
    chat = update.effective_chat

    if chat.type == "private":
        return True

    if not group_active(chat.id):
        await update.message.reply_text(
            "⛔ بات هنوز فعال نشده.\n\n"
            "ادمین گروه باید بنویسه:\n"
            "فعال"
        )
        return False

    return True


# =========================
# شروع
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user)

    await update.message.reply_text(
        "💰 به بات پولمون خوش اومدی!\n\n"
        "بات رو به گروه اضافه کن و داخل گروه بنویس:\n"
        "فعال\n\n"
        "📖 راهنما"
    )


# =========================
# فعال / غیرفعال
# =========================

async def activation(update, context):
    if update.effective_chat.type == "private":
        return

    text = update.message.text.strip()

    if text == "فعال":

        if not await is_admin(update):
            await update.message.reply_text(
                "⛔ فقط ادمین گروه می‌تونه بات رو فعال کنه."
            )
            return

        set_group_active(
            update.effective_chat.id,
            True
        )

        await update.message.reply_text(
            "بات فعال شد ✅\n\n"
            "💰 بازی شروع شد!"
        )

    elif text in ("غیرفعال", "غیر فعال"):

        if not await is_admin(update):
            await update.message.reply_text(
                "⛔ فقط ادمین گروه می‌تونه بات رو غیرفعال کنه."
            )
            return

        set_group_active(
            update.effective_chat.id,
            False
        )

        await update.message.reply_text(
            "بات غیرفعال شد ⛔"
        )


# =========================
# راهنما
# =========================

async def help_command(update, context):
    if not await ensure_active(update):
        return

    await update.message.reply_text(
        "📚 راهنمای بات پولمون\n\n"

        "💰 اقتصاد:\n"
        "موجودی\n"
        "واریز 10 میل\n"
        "برداشت 10 میل\n"
        "انتقال 10 میل (با Reply)\n\n"

        "🎮 بازی‌ها:\n"
        "سنگ 10 میل\n"
        "کاغذ 10 میل\n"
        "قیچی 10 میل\n"
        "شیر 10 میل\n"
        "خط 10 میل\n"
        "راست 10 میل\n"
        "چپ 10 میل\n\n"

        "🏆 رتبه‌بندی:\n"
        "ثروتمندان\n\n"

        "🎫 سریال:\n"
        "ساخت سریال 20 بیل\n\n"

        "⛏ ماینر:\n"
        "ماینر\n\n"

        "برای شروع، موجودی خودت رو ببین:"
        "\nموجودی"
    )


# =========================
# موجودی
# =========================

async def balance(update, context):
    if not await ensure_active(update):
        return

    user = get_user(update.effective_user)

    await update.message.reply_text(
        f"👤 {user['first_name']}\n\n"
        f"🪙 کیف پول:\n"
        f"{fmt(user['wallet'])}\n\n"
        f"🏦 بانک:\n"
        f"{fmt(user['bank'])}\n\n"
        f"📈 بیشترین موجودی:\n"
        f"{fmt(user['highest'])}\n\n"
        f"🏆 برد: {user['wins']}\n"
        f"💀 باخت: {user['losses']}"
    )


# =========================
# بانک
# =========================

async def bank(update, context):
    if not await ensure_active(update):
        return

    text = update.message.text.strip()

    if text.startswith("واریز "):

        amount = parse_amount(
            text[6:]
        )

        if not amount:
            await update.message.reply_text(
                "❌ مقدار اشتباهه.\n"
                "مثال:\n"
                "واریز 10 میل"
            )
            return

        user = get_user(update.effective_user)

        if user["wallet"] < amount:
            await update.message.reply_text(
                "❌ موجودی کیف پولت کافی نیست."
            )
            return

        remove_wallet(
            user["user_id"],
            amount
        )

        cur.execute("""
            UPDATE users
            SET bank = bank + ?
            WHERE user_id = ?
        """, (
            amount,
            user["user_id"]
        ))

        conn.commit()

        await update.message.reply_text(
            f"🏦 واریز انجام شد.\n"
            f"💰 مبلغ: {fmt(amount)}"
        )

    elif text.startswith("برداشت "):

        amount = parse_amount(
            text[7:]
        )

        if not amount:
            await update.message.reply_text(
                "❌ مقدار اشتباهه.\n"
                "مثال:\n"
                "برداشت 10 میل"
            )
            return

        user = get_user(update.effective_user)

        if user["bank"] < amount:
            await update.message.reply_text(
                "❌ موجودی بانک کافی نیست."
            )
            return

        cur.execute("""
            UPDATE users
            SET bank = bank - ?,
                wallet = wallet + ?
            WHERE user_id = ?
        """, (
            amount,
            amount,
            user["user_id"]
        ))

        conn.commit()

        update_highest(
            user["user_id"]
        )

        await update.message.reply_text(
            f"🏦 برداشت انجام شد.\n"
            f"💰 مبلغ: {fmt(amount)}"
        )


# =========================
# انتقال
# =========================

async def transfer(update, context):
    if not await ensure_active(update):
        return

    message = update.message

    if not message.reply_to_message:
        await message.reply_text(
            "❌ روی پیام طرف Reply کن.\n\n"
            "مثال:\n"
            "انتقال 500 بیل"
        )
        return

    receiver = message.reply_to_message.from_user

    if receiver.is_bot:
        await message.reply_text(
            "❌ نمی‌تونی به ربات پول بدی."
        )
        return

    sender = get_user(
        update.effective_user
    )

    if sender["user_id"] == receiver.id:
        await message.reply_text(
            "😂 انتقال به خودت که معنی نداره."
        )
        return

    amount = parse_amount(
        message.text.replace(
            "انتقال",
            "",
            1
        ).strip()
    )

    if not amount:
        await message.reply_text(
            "❌ مثال:\n"
            "انتقال 500 بیل"
        )
        return

    owner = await is_owner(update)

    if not owner and sender["wallet"] < amount:
        await message.reply_text(
            "❌ موجودی کیف پولت کافی نیست."
        )
        return

    get_user(receiver)

    if not owner:
        remove_wallet(
            sender["user_id"],
            amount
        )

    add_wallet(
        receiver.id,
        amount
    )

    await update.message.reply_text(
        "💸 انتقال انجام شد!\n\n"
        f"👤 فرستنده: {sender['first_name']}\n"
        f"👤 گیرنده: {receiver.first_name}\n"
        f"💰 مبلغ: {fmt(amount)}"
    )


# =========================
# سنگ کاغذ قیچی
# =========================

async def rps(update, context, choice):
    if not await ensure_active(update):
        return

    amount = get_amount_from_game(
        update.message.text
    )

    if not amount:
        await update.message.reply_text(
            f"❌ مثال:\n{choice} 4 میل"
        )
        return

    user = get_user(
        update.effective_user
    )

    owner = await is_owner(update)

    if not owner and user["wallet"] < amount:
        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    bot_choice = random.choice([
        "سنگ",
        "کاغذ",
        "قیچی"
    ])

    if choice == bot_choice:
        result = "draw"

    elif (
        (choice == "سنگ" and bot_choice == "قیچی")
        or
        (choice == "کاغذ" and bot_choice == "سنگ")
        or
        (choice == "قیچی" and bot_choice == "کاغذ")
    ):
        result = "win"

    else:
        result = "lose"

    before = user["wallet"]

    if not owner:

        if result == "win":

            add_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET wins = wins + 1
                WHERE user_id = ?
            """, (user["user_id"],))

        elif result == "lose":

            remove_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET losses = losses + 1
                WHERE user_id = ?
            """, (user["user_id"],))

        conn.commit()

    if result == "win":
        title = "🎉 بردی!"
        after = before + amount

    elif result == "lose":
        title = "💀 باختی!"
        after = before - amount

    else:
        title = "🤝 مساوی شد!"
        after = before

    await update.message.reply_text(
        f"🎮 سنگ کاغذ قیچی\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 انتخاب بات: {bot_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {fmt(amount)}\n\n"
        f"🪙 قبل: {fmt(before)}\n"
        f"🪙 بعد: {fmt(after)}"
    )


# =========================
# راست چپ
# =========================

async def right_left(update, context, choice):
    if not await ensure_active(update):
        return

    amount = get_amount_from_game(
        update.message.text
    )

    if not amount:
        await update.message.reply_text(
            f"❌ مثال:\n{choice} 10 میل"
        )
        return

    user = get_user(
        update.effective_user
    )

    owner = await is_owner(update)

    if not owner and user["wallet"] < amount:
        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    bot_choice = random.choice([
        "راست",
        "چپ"
    ])

    before = user["wallet"]

    if choice == bot_choice:

        if not owner:
            add_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET wins = wins + 1
                WHERE user_id = ?
            """, (user["user_id"],))

            conn.commit()

        title = "🎉 بردی!"
        after = before + amount

    else:

        if not owner:
            remove_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET losses = losses + 1
                WHERE user_id = ?
            """, (user["user_id"],))

            conn.commit()

        title = "💀 باختی!"
        after = before - amount

    await update.message.reply_text(
        f"↔️ راست چپ\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 انتخاب بات: {bot_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {fmt(amount)}\n\n"
        f"🪙 قبل: {fmt(before)}\n"
        f"🪙 بعد: {fmt(after)}"
    )


# =========================
# شیر خط
# =========================

async def coin_game(update, context, choice):
    if not await ensure_active(update):
        return

    amount = get_amount_from_game(
        update.message.text
    )

    if not amount:
        await update.message.reply_text(
            f"❌ مثال:\n{choice} 50 میل"
        )
        return

    user = get_user(
        update.effective_user
    )

    owner = await is_owner(update)

    if not owner and user["wallet"] < amount:
        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    bot_choice = random.choice([
        "شیر",
        "خط"
    ])

    before = user["wallet"]

    if choice == bot_choice:

        if not owner:
            add_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET wins = wins + 1
                WHERE user_id = ?
            """, (user["user_id"],))

            conn.commit()

        title = "🎉 بردی!"
        after = before + amount

    else:

        if not owner:
            remove_wallet(
                user["user_id"],
                amount
            )

            cur.execute("""
                UPDATE users
                SET losses = losses + 1
                WHERE user_id = ?
            """, (user["user_id"],))

            conn.commit()

        title = "💀 باختی!"
        after = before - amount

    await update.message.reply_text(
        f"🪙 شیر یا خط\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 نتیجه: {bot_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {fmt(amount)}\n\n"
        f"🪙 قبل: {fmt(before)}\n"
        f"🪙 بعد: {fmt(after)}"
    )


# =========================
# سریال
# =========================

def generate_serial():

    chars = string.ascii_letters + string.digits

    while True:

        code = "".join(
            random.choices(
                chars,
                k=20
            )
        )

        cur.execute(
            "SELECT code FROM serials WHERE code = ?",
            (code,)
        )

        if not cur.fetchone():
            return code


async def create_serial(update, context):

    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "❌ ساخت سریال باید داخل گروه انجام بشه."
        )
        return

    if not await is_owner(update):
        await update.message.reply_text(
            "⛔ فقط مالک گروه می‌تونه سریال بسازه."
        )
        return

    amount = parse_amount(
        update.message.text.replace(
            "ساخت سریال",
            "",
            1
        ).strip()
    )

    if not amount:
        await update.message.reply_text(
            "❌ مثال:\n"
            "ساخت سریال 20 بیل"
        )
        return

    code = generate_serial()

    cur.execute("""
        INSERT INTO serials(code, amount)
        VALUES (?, ?)
    """, (
        code,
        amount
    ))

    conn.commit()

    try:

        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                "🎫 سریال جدید ساخته شد!\n\n"
                f"💰 ارزش: {fmt(amount)}\n"
                f"🔐 سریال:\n{code}"
            )
        )

        await update.message.reply_text(
            "✅ سریال ساخته شد و در پیویت ارسال شد."
        )

    except Exception:

        await update.message.reply_text(
            "⚠️ سریال ساخته شد، ولی نتونستم "
            "به پیویت پیام بدم.\n"
            "اول بات رو در پیوی Start کن."
        )


async def redeem_serial(update, context):

    if not await ensure_active(update):
        return

    text = update.message.text.strip()

    if len(text) != 20:
        return

    if not re.fullmatch(
        r"[A-Za-z0-9]{20}",
        text
    ):
        return

    cur.execute("""
        SELECT * FROM serials
        WHERE code = ? AND used = 0
    """, (text,))

    serial = cur.fetchone()

    if not serial:
        return

    user = get_user(
        update.effective_user
    )

    add_wallet(
        user["user_id"],
        serial["amount"]
    )

    cur.execute("""
        UPDATE serials
        SET used = 1,
            used_by = ?
        WHERE code = ?
    """, (
 
