import os
import re
import random
import string
import sqlite3
import time
from contextlib import closing

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

DB_FILE = os.getenv("DB_FILE", "bazi_pol.db")

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row


def db_execute(query, params=(), fetchone=False, fetchall=False):
    with closing(db.cursor()) as cur:
        cur.execute(query, params)

        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()
        else:
            result = None

        db.commit()
        return result


def init_db():
    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            wallet INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0,
            highest INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 0
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY,
            amount INTEGER NOT NULL,
            used INTEGER DEFAULT 0,
            used_by INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db_execute("""
        CREATE TABLE IF NOT EXISTS miners (
            user_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            count INTEGER DEFAULT 0,
            income INTEGER DEFAULT 0,
            last_update REAL DEFAULT 0,
            PRIMARY KEY(user_id, level)
        )
    """)


# =========================================================
# MONEY
# =========================================================

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

    "دیل": 10**18,
}


def fa_to_en(text):
    return str(text).translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹",
            "0123456789"
        )
    )


def money(number):
    return f"{int(number):,}"


def parse_amount(text):
    text = fa_to_en(text).strip().lower()

    text = text.replace("،", ",")
    text = text.replace("تومان", "")
    text = text.replace("سکه", "")
    text = text.strip()

    match = re.fullmatch(
        r"([\d,]+(?:\.\d+)?)\s*([a-zA-Zآ-ی]+)?",
        text
    )

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
        if unit not in UNITS:
            return None

        multiplier = UNITS[unit]

    return int(number * multiplier)


# =========================================================
# USERS
# =========================================================

def ensure_user(user):
    row = db_execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user.id,),
        fetchone=True
    )

    if row is None:
        db_execute("""
            INSERT INTO users
            (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or ""
        ))

    else:
        db_execute("""
            UPDATE users
            SET username = ?, first_name = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "",
            user.id
        ))

    return get_user(user.id)


def get_user(user_id):
    return db_execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
        fetchone=True
    )


def set_wallet(user_id, amount):
    db_execute("""
        UPDATE users
        SET wallet = ?
        WHERE user_id = ?
    """, (int(amount), user_id))

    update_highest(user_id)


def add_wallet(user_id, amount):
    db_execute("""
        UPDATE users
        SET wallet = wallet + ?
        WHERE user_id = ?
    """, (int(amount), user_id))

    update_highest(user_id)


def remove_wallet(user_id, amount):
    db_execute("""
        UPDATE users
        SET wallet = wallet - ?
        WHERE user_id = ?
    """, (int(amount), user_id))


def update_highest(user_id):
    db_execute("""
        UPDATE users
        SET highest =
            CASE
                WHEN wallet > highest THEN wallet
                ELSE highest
            END
        WHERE user_id = ?
    """, (user_id,))


def add_win(user_id):
    db_execute("""
        UPDATE users
        SET wins = wins + 1,
            games = games + 1
        WHERE user_id = ?
    """, (user_id,))


def add_loss(user_id):
    db_execute("""
        UPDATE users
        SET losses = losses + 1,
            games = games + 1
        WHERE user_id = ?
    """, (user_id,))


def add_game(user_id):
    db_execute("""
        UPDATE users
        SET games = games + 1
        WHERE user_id = ?
    """, (user_id,))


# =========================================================
# GROUP
# =========================================================

def is_group(chat):
    return chat and chat.type in (
        "group",
        "supergroup"
    )


def group_active(chat_id):
    row = db_execute("""
        SELECT active
        FROM groups
        WHERE chat_id = ?
    """, (chat_id,), fetchone=True)

    return bool(row and row["active"])


def set_group_active(chat_id, active):
    db_execute("""
        INSERT INTO groups(chat_id, active)
        VALUES (?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET active = excluded.active
    """, (chat_id, int(active)))


async def is_admin(update):
    if not is_group(update.effective_chat):
        return False

    member = await update.effective_chat.get_member(
        update.effective_user.id
    )

    return member.status in (
        "administrator",
        "creator"
    )


async def is_owner(update):
    if not is_group(update.effective_chat):
        return False

    member = await update.effective_chat.get_member(
        update.effective_user.id
    )

    return member.status == "creator"


async def require_active(update):
    if not is_group(update.effective_chat):
        return True

    if not group_active(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ بات فعاله نیست.\n\n"
            "ادمین گروه بنویسه:\n"
            "فعال"
        )
        return False

    return True


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)

    await update.message.reply_text(
        "💰 به بات پولمون خوش اومدی!\n\n"
        "🎮 بازی‌های موجود:\n"
        "🪨 سنگ کاغذ قیچی\n"
        "↔️ راست چپ\n"
        "🪙 شیر خط\n\n"
        "📖 راهنما"
    )


# =========================================================
# ACTIVATION
# =========================================================

async def activation(update, context):
    text = update.message.text.strip()

    if not is_group(update.effective_chat):
        await update.message.reply_text(
            "❌ این دستور باید داخل گروه استفاده بشه."
        )
        return

    if not await is_admin(update):
        await update.message.reply_text(
            "⛔ فقط ادمین گروه می‌تونه این کارو انجام بده."
        )
        return

    if text == "فعال":
        set_group_active(update.effective_chat.id, True)

        await update.message.reply_text(
            "بات فعال شد✅\n\n"
            "🎮 بازی شروع شد!"
        )

    elif text == "غیر فعال":
        set_group_active(update.effective_chat.id, False)

        await update.message.reply_text(
            "بات غیرفعال شد⛔"
        )


# =========================================================
# BALANCE
# =========================================================

async def balance(update, context):
    if not await require_active(update):
        return

    user = ensure_user(update.effective_user)

    await update.message.reply_text(
        "💰 موجودی\n\n"
        f"👤 {user['first_name']}\n\n"
        f"🪙 کیف پول:\n"
        f"{money(user['wallet'])}\n\n"
        f"🏦 بانک:\n"
        f"{money(user['bank'])}\n\n"
        f"📈 بیشترین موجودی:\n"
        f"{money(user['highest'])}\n\n"
        f"🏆 برد: {user['wins']}\n"
        f"💀 باخت: {user['losses']}\n"
        f"🎮 تعداد بازی: {user['games']}"
    )


# =========================================================
# BANK
# =========================================================

async def bank_handler(update, context):
    if not await require_active(update):
        return

    text = fa_to_en(update.message.text).strip()

    if text.startswith("واریز "):
        amount = parse_amount(
            text[len("واریز "):]
        )

        if not amount:
            await update.message.reply_text(
                "❌ مقدار اشتباهه.\n"
                "مثال:\n"
                "واریز 10 میل"
            )
            return

        user = ensure_user(update.effective_user)

        if user["wallet"] < amount:
            await update.message.reply_text(
                "❌ موجودی کیف پولت کافی نیست."
            )
            return

        db_execute("""
            UPDATE users
            SET wallet = wallet - ?,
                bank = bank + ?
            WHERE user_id = ?
        """, (
            amount,
            amount,
            user["user_id"]
        ))

        await update.message.reply_text(
            "🏦 واریز انجام شد!\n\n"
            f"💰 مبلغ: {money(amount)}\n"
            f"🪙 کیف پول جدید: "
            f"{money(user['wallet'] - amount)}\n"
            f"🏦 بانک جدید: "
            f"{money(user['bank'] + amount)}"
        )

    elif text.startswith("برداشت "):
        amount = parse_amount(
            text[len("برداشت "):]
        )

        if not amount:
            await update.message.reply_text(
                "❌ مقدار اشتباهه.\n"
                "مثال:\n"
                "برداشت 10 میل"
            )
            return

        user = ensure_user(update.effective_user)

        if user["bank"] < amount:
            await update.message.reply_text(
                "❌ موجودی بانک کافی نیست."
            )
            return

        db_execute("""
            UPDATE users
            SET bank = bank - ?,
                wallet = wallet + ?
            WHERE user_id = ?
        """, (
            amount,
            amount,
            user["user_id"]
        ))

        update_highest(user["user_id"])

        await update.message.reply_text(
            "🏦 برداشت انجام شد!\n\n"
            f"💰 مبلغ: {money(amount)}\n"
            f"🪙 کیف پول جدید: "
            f"{money(user['wallet'] + amount)}\n"
            f"🏦 بانک جدید: "
            f"{money(user['bank'] - amount)}"
        )


# =========================================================
# TRANSFER
# =========================================================

async def transfer(update, context):
    if not await require_active(update):
        return

    message = update.message

    if not message.reply_to_message:
        await message.reply_text(
            "❌ باید روی پیام شخص موردنظر Reply کنی.\n\n"
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

    sender = ensure_user(update.effective_user)
    ensure_user(receiver)

    if sender["user_id"] == receiver.id:
        await message.reply_text(
            "😂 انتقال به خودت که معنی نداره."
        )
        return

    amount = parse_amount(
        message.text.replace("انتقال", "", 1).strip()
    )

    if not amount:
        await message.reply_text(
            "❌ مقدار انتقال اشتباهه.\n"
            "مثال:\n"
            "انتقال 500 بیل"
        )
        return

    owner = await is_owner(update)

    if not owner and sender["wallet"] < amount:
        await message.reply_text(
            "❌ موجودی کیف پولت کافی نیست."
        )
        return

    if owner:
        before_sender = sender["wallet"]
        add_wallet(receiver.id, amount)

    else:
        before_sender = sender["wallet"]
        remove_wallet(sender["user_id"], amount)
        add_wallet(receiver.id, amount)

    receiver_after = get_user(receiver.id)

    await update.message.reply_text(
        "💸 انتقال انجام شد!\n\n"
        f"👤 فرستنده: {sender['first_name']}\n"
        f"👤 گیرنده: {receiver.first_name}\n"
        f"💰 مبلغ: {money(amount)}\n\n"
        f"🪙 موجودی فرستنده قبل: "
        f"{money(before_sender)}\n"
        f"🪙 موجودی فرستنده بعد: "
        f"{money(before_sender if owner else before_sender - amount)}\n\n"
        f"🪙 موجودی گیرنده بعد: "
        f"{money(receiver_after['wallet'])}"
    )


# =========================================================
# GAME HELPERS
# =========================================================

def game_amount(text):
    parts = text.strip().split(maxsplit=1)

    if len(parts) != 2:
        return None

    return parse_amount(parts[1])


async def prepare_game(update, amount):
    user = ensure_user(update.effective_user)

    if not amount:
        await update.message.reply_text(
            "❌ مبلغ بازی رو درست وارد کن."
        )
        return None

    owner = await is_owner(update)

    if not owner and user["wallet"] < amount:
        await update.message.reply_text(
            "❌ موجودی کیف پولت کافی نیست."
        )
        return None

    return user, owner


# =========================================================
# ROCK PAPER SCISSORS
# =========================================================

async def rps(update, context, choice):
    if not await require_active(update):
        return

    amount = game_amount(update.message.text)

    result = await prepare_game(update, amount)

    if not result:
        return

    user, owner = result

    bot_choice = random.choice([
        "سنگ",
        "کاغذ",
        "قیچی"
    ])

    if choice == bot_choice:
        outcome = "draw"

    elif (
        (choice == "سنگ" and bot_choice == "قیچی")
        or
        (choice == "کاغذ" and bot_choice == "سنگ")
        or
        (choice == "قیچی" and bot_choice == "کاغذ")
    ):
        outcome = "win"

    else:
        outcome = "lose"

    before = user["wallet"]

    if outcome == "win":
        if not owner:
            add_wallet(user["user_id"], amount)

        add_win(user["user_id"])

        title = "🎉 بردی!"
        after = before + amount

    elif outcome == "lose":
        if not owner:
            remove_wallet(user["user_id"], amount)

        add_loss(user["user_id"])

        title = "💀 باختی!"
        after = before - amount

    else:
        add_game(user["user_id"])

        title = "🤝 مساوی شد!"
        after = before

    await update.message.reply_text(
        "🎮 سنگ کاغذ قیچی\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 انتخاب بات: {bot_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {money(amount)}\n\n"
        f"🪙 قبل: {money(before)}\n"
        f"🪙 بعد: {money(after)}"
    )


# =========================================================
# RIGHT LEFT
# =========================================================

async def right_left(update, context, choice):
    if not await require_active(update):
        return

    amount = game_amount(update.message.text)

    result = await prepare_game(update, amount)

    if not result:
        return

    user, owner = result

    bot_choice = random.choice([
        "راست",
        "چپ"
    ])

    before = user["wallet"]

    if choice == bot_choice:
        if not owner:
            add_wallet(user["user_id"], amount)

        add_win(user["user_id"])

        title = "🎉 بردی!"
        after = before + amount

    else:
        if not owner:
            remove_wallet(user["user_id"], amount)

        add_loss(user["user_id"])

        title = "💀 باختی!"
        after = before - amount

    await update.message.reply_text(
        "↔️ راست چپ\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 انتخاب بات: {bot_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {money(amount)}\n\n"
        f"🪙 قبل: {money(before)}\n"
        f"🪙 بعد: {money(after)}"
    )


# =========================================================
# COIN
# =========================================================

async def coin_game(update, context, choice):
    if not await require_active(update):
        return

    amount = game_amount(update.message.text)

    result = await prepare_game(update, amount)

    if not result:
        return

    user, owner = result

    result_choice = random.choice([
        "شیر",
        "خط"
    ])

    before = user["wallet"]

    if choice == result_choice:
        if not owner:
            add_wallet(user["user_id"], amount)

        add_win(user["user_id"])

        title = "🎉 بردی!"
        after = before + amount

    else:
        if not owner:
            remove_wallet(user["user_id"], amount)

        add_loss(user["user_id"])

        title = "💀 باختی!"
        after = before - amount

    await update.message.reply_text(
        "🪙 شیر یا خط\n\n"
        f"👤 انتخاب تو: {choice}\n"
        f"🤖 نتیجه: {result_choice}\n\n"
        f"{title}\n"
        f"💰 مبلغ: {money(amount)}\n\n"
        f"🪙 قبل: {money(before)}\n"
        f"🪙 بعد: {money(after)}"
    )


# =========================================================
# SERIAL
# =========================================================

SERIAL_CHARS = string.ascii_letters + string.digits


def generate_serial():
    while True:
        code = "".join(
            random.choices(
                SERIAL_CHARS,
                k=20
            )
        )

        exists = db_execute(
            "SELECT code FROM serials WHERE code = ?",
            (code,),
            fetchone=True
        )

        if not exists:
            return code


async def create_serial(update, context):
    if not is_group(update.effective_chat):
        await update.message.reply_text(
            "❌ این دستور باید داخل گروه باشه."
        )
        return

    if not await is_owner(update):
        await update.message.reply_text(
            "⛔ فقط مالک گروه می‌تونه سریال بسازه."
        )
        return

    amount = parse_amount(
        update.message.text
        .replace("ساخت سریال", "", 1)
        .strip()
    )

    if not amount:
        await update.message.reply_text(
            "❌ مثال:\n"
            "ساخت سریال 20 بیل"
        )
        return

    code = generate_serial()

    db_execute("""
        INSERT INTO serials(code, amount)
        VALUES (?, ?)
    """, (code, amount))

    try:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=(
                "🎫 سریال ساخته شد!\n\n"
                f"💰 ارزش: {money(amount)}\n\n"
                f"🔐 کد:\n{code}"
            )
        )

        await update.message.
