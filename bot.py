import os
import sqlite3
import random
import string
import time

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

# آیدی عددی صاحب ربات را اینجا بگذار
OWNER_ID = 8981018900

DB_FILE = "moltaf_kid.db"

# موجودی نامحدود صاحب ربات
OWNER_MONEY = 10**100


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_db():
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            money INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY,
            amount INTEGER NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS miners (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_claim REAL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups_active (
            chat_id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 0
        )
    """)

    db.commit()


# =========================================================
# USERS / MONEY
# =========================================================

def ensure_user(user_id):
    if user_id == OWNER_ID:
        return

    cur = db.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO users
        (user_id, money, bank)
        VALUES (?, 0, 0)
        """,
        (user_id,)
    )

    db.commit()


def get_money(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    cur = db.cursor()

    cur.execute(
        "SELECT money FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        return row["money"]

    return 0


def get_bank(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    cur = db.cursor()

    cur.execute(
        "SELECT bank FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        return row["bank"]

    return 0


def add_money(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users
        SET money = money + ?
        WHERE user_id = ?
        """,
        (amount, user_id)
    )

    db.commit()


def remove_money(user_id, amount):
    if user_id == OWNER_ID:
        return True

    ensure_user(user_id)

    if get_money(user_id) < amount:
        return False

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users
        SET money = money - ?
        WHERE user_id = ?
        """,
        (amount, user_id)
    )

    db.commit()

    return True


def add_bank(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users
        SET bank = bank + ?
        WHERE user_id = ?
        """,
        (amount, user_id)
    )

    db.commit()


def remove_bank(user_id, amount):
    if user_id == OWNER_ID:
        return True

    ensure_user(user_id)

    if get_bank(user_id) < amount:
        return False

    cur = db.cursor()

    cur.execute(
        """
        UPDATE users
        SET bank = bank - ?
        WHERE user_id = ?
        """,
        (amount, user_id)
    )

    db.commit()

    return True


# =========================================================
# AMOUNT PARSER
# =========================================================

def parse_amount(text, user_id):
    text = text.strip().lower()

    money = get_money(user_id)

    if text in ["کل", "همه", "همش"]:
        return money

    if text == "نصف":
        return money // 2

    if text == "خمس":
        return money // 5

    if text == "ثلث":
        return money // 3

    multipliers = {
        "کا": 10**3,
        "هزار": 10**3,

        "میل": 10**6,
        "میلیون": 10**6,

        "بیل": 10**9,
        "میلیارد": 10**9,

        "تیل": 10**12,
        "تریلیون": 10**12,

        "کیل": 10**15,

        "کواد": 10**18
    }

    parts = text.replace(",", "").split()

    if len(parts) == 1:
        try:
            return int(parts[0])
        except ValueError:
            return None

    try:
        number = int(parts[0])
        unit = parts[1]

        if unit in multipliers:
            return number * multipliers[unit]

    except (ValueError, IndexError):
        pass

    return None


# =========================================================
# FORMAT MONEY
# =========================================================

def format_money(amount):
    if amount >= 10**18:
        return f"{amount / 10**18:.2f} کواد سکه"

    if amount >= 10**15:
        return f"{amount / 10**15:.2f} کیل سکه"

    if amount >= 10**12:
        return f"{amount / 10**12:.2f} تیل سکه"

    if amount >= 10**9:
        return f"{amount / 10**9:.2f} بیل سکه"

    if amount >= 10**6:
        return f"{amount / 10**6:.2f} میل سکه"

    if amount >= 10**3:
        return f"{amount / 10**3:.2f} کا سکه"

    return f"{amount:,} سکه"


# =========================================================
# GROUP
# =========================================================

def group_is_active(chat_id):
    cur = db.cursor()

    cur.execute(
        """
        SELECT active
        FROM groups_active
        WHERE chat_id = ?
        """,
        (chat_id,)
    )

    row = cur.fetchone()

    return bool(row["active"]) if row else False


def activate_group(chat_id):
    cur = db.cursor()

    cur.execute(
        """
        INSERT INTO groups_active
        (chat_id, active)
        VALUES (?, 1)
        ON CONFLICT(chat_id)
        DO UPDATE SET active = 1
        """,
        (chat_id,)
    )

    db.commit()


# =========================================================
# BANK
# =========================================================

async def bank_deposit(update, user_id, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مقدار درست وارد کن."
        )
        return

    if user_id != OWNER_ID:
        if not remove_money(user_id, amount):
            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )
            return

    add_bank(user_id, amount)

    await update.message.reply_text(
        f"🏦 {format_money(amount)} به بانک منتقل شد."
    )


async def bank_withdraw(update, user_id, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مقدار درست وارد کن."
        )
        return

    if not remove_bank(user_id, amount):
        await update.message.reply_text(
            "❌ موجودی بانک کافی نیست."
        )
        return

    add_money(user_id, amount)

    await update.message.reply_text(
        f"💳 {format_money(amount)} از بانک برداشت شد."
    )


# =========================================================
# TRANSFER
# =========================================================

async def transfer(update, user_id, amount):
    reply = update.message.reply_to_message

    if not reply:
        await update.message.reply_text(
            "❌ باید روی پیام شخص ریپلای کنی."
        )
        return

    target = reply.from_user

    if target.id == user_id:
        await update.message.reply_text(
            "😂 به خودت نمیشه انتقال داد."
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ مقدار درست نیست."
        )
        return

    if user_id != OWNER_ID:
        if not remove_money(user_id, amount):
            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )
            return

    add_money(target.id, amount)

    await update.message.reply_text(
        f"💸 انتقال انجام شد!\n\n"
        f"👤 گیرنده: {target.first_name}\n"
        f"💰 مبلغ: {format_money(amount)}"
    )


# =========================================================
# SERIAL
# =========================================================

async def create_serial(update, user_id, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if user_id != OWNER_ID:
        if not remove_money(user_id, amount):
            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )
            return

    while True:
        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=20
            )
        )

        cur = db.cursor()

        cur.execute(
            "SELECT code FROM serials WHERE code = ?",
            (code,)
        )

        if not cur.fetchone():
            break

    cur.execute(
        """
        INSERT INTO serials
        (code, amount, used)
        VALUES (?, ?, 0)
        """,
        (code, amount)
    )

    db.commit()

    await update.message.reply_text(
        f"🎟 سریال ساخته شد!\n\n"
        f"{code}\n\n"
        f"💰 ارزش: {format_money(amount)}"
    )


async def use_serial(update, user_id, code):
    code = code.upper()

    cur = db.cursor()

    cur.execute(
        "SELECT * FROM serials WHERE code = ?",
        (code,)
    )

    row = cur.fetchone()

    if not row:
        await update.message.reply_text(
            "❌ سریال پیدا نشد."
        )
        return

    if row["used"]:
        await update.message.reply_text(
            "❌ این سریال قبلاً استفاده شده."
        )
        return

    amount = row["amount"]

    cur.execute(
        """
        UPDATE serials
        SET used = 1
        WHERE code = ?
        """,
        (code,)
    )

    db.commit()

    add_money(user_id, amount)

    await update.message.reply_text(
        f"🎉 سریال فعال شد!\n\n"
        f"💰 دریافت کردی: {format_money(amount)}"
    )


# =========================================================
# MINER
# =========================================================

def get_miner_data(user_id):
    cur = db.cursor()

    cur.execute(
        "SELECT * FROM miners WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        now = time.time()

        cur.execute(
            """
            INSERT INTO miners
            (user_id, count, level, last_claim)
            VALUES (?, 0, 1, ?)
            """,
            (user_id, now)
        )

        db.commit()

        return {
            "count": 0,
            "level": 1,
            "last_claim": now
        }

    return {
        "count": row["count"],
        "level": row["level"],
        "last_claim": row["last_claim"]
    }


async def buy_miner(update, user_id, count, level):
    price_each = 1_000_000 * (2 ** (level - 1))
    total = price_each * count

    if user_id != OWNER_ID:
        if not remove_money(user_id, total):
            await update.message.reply_text(
                f"❌ سکه کافی نداری.\n\n"
                f"💰 قیمت: {format_money(total)}"
            )
            return

    data = get_miner_data(user_id)

    new_count = data["count"] + count

    cur = db.cursor()

    cur.execute(
        """
        UPDATE miners
        SET count = ?,
            level = ?
        WHERE user_id = ?
        """,
        (new_count, level, user_id)
    )

    db.commit()

    await update.message.reply_text(
        f"⛏ ماینر خریداری شد!\n\n"
        f"🔢 تعداد: {count}\n"
        f"⭐ سطح: {level}\n"
        f"💰 هزینه: {format_money(total)}"
    )


async def claim_miner(update, user_id):
    data = get_miner_data(user_id)

    count = data["count"]
    level = data["level"]
    last_claim = data["last_claim"]

    if count <= 0:
        await update.message.reply_text(
            "⛏ هنوز ماینری نداری."
        )
        return

    now = time.time()

    seconds = int(now - last_claim)

    if seconds <= 0:
        await update.message.reply_text(
            "⏳ هنوز چیزی برای برداشت جمع نشده."
        )
        return

    rate = 1000 * level
    reward = seconds * count * rate

    cur = db.cursor()

    cur.execute(
        """
        UPDATE miners
        SET last_claim = ?
        WHERE user_id = ?
        """,
        (now, user_id)
    )

    db.commit()

    add_money(user_id, reward)

    await update.message.reply_text(
        f"⛏ برداشت ماینر انجام شد!\n\n"
        f"⏱ زمان: {seconds} ثانیه\n"
        f"💰 دریافت: {format_money(reward)}"
    )


# =========================================================
# GAMES
# =========================================================

async def play_game(update, user_id, amount, win, result_text):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مقدار شرط درست نیست."
        )
        return

    if user_id != OWNER_ID:
        if get_money(user_id) < amount:
            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )
            return

        remove_money(user_id, amount)

    if win:
        reward = amount * 2

        add_money(user_id, reward)

        await update.message.reply_text(
            f"{result_text}\n\n"
            f"🎉 بردی!\n"
            f"💰 جایزه: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"{result_text}\n\n"
            f"💀 باختی!\n"
            f"💸 مبلغ از دست رفته: {format_money(amount)}"
        )


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
╭━━━━━━━ ✦ ملتفت کید ✦ ━━━━━━━╮

💰 اقتصاد:

موجودی
بالانس
سکه

🏦 بانک:

بانک
شارژ بانک 10 میل
برداشت بانک 5 میل

💸 انتقال:

روی پیام شخص ریپلای کن:

انتقال 5 میل

🎟 سریال:

ساخت سریال 10 میل
سریال CODE

⛏ ماینر:

خرید 5 ماینر
خرید 5 ماینر سطح 2
برداشت ماینر

🎮 بازی:

سنگ 5 میل
کاغذ 5 میل
قیچی 5 میل

شیر 5 میل
خط 5 میل

راست 5 میل
چپ 5 میل

زوج 5 میل
فرد 5 میل

⚙️ مدیریت:

فعال

━━━━━━━━━━━━━━━━━━━━

💰 واحد اقتصاد: سکه

╰━━━━━━━ ✦ ملتفت کید ✦ ━━━━━━━╯
"""


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    user = update.effective_user

    if not user:
        return

    user_id = user.id

    chat = update.effective_chat

    ensure_user(user_id)

    # فعال کردن گروه
    if text == "فعال":
        if user_id != OWNER_ID:
            return

        if chat.type in ["group", "supergroup"]:
            activate_group(chat.id)

        await update.message.reply_text(
            "ربات فعال شد ✅\n"
            "ملتفت کید هستم، سر گرمتون میکنم 🗿"
        )

        return

    # در گروه باید فعال شده باشد
    if chat.type in ["group", "supergroup"]:
        if not group_is_active(chat.id):
            return

    # راهنما
    if text in ["راهنما", "کمک", "/help"]:
        await update.message.reply_text(HELP_TEXT)
        return

    # موجودی
    if text in ["موجودی", "بالانس", "سکه"]:
        money = get_money(user_id)

        await update.message.reply_text(
            f"💰 موجودی تو:\n\n"
            f"{format_money(money)}"
        )

        return

    # بانک
    if text in [
        "بانک",
        "موجودی بانک",
        "موجودی حساب بانکی",
        "موجودی کارت"
    ]:
        bank = get_bank(user_id)

        await update.message.reply_text(
            f"🏦 موجودی بانک:\n\n"
            f"{format_money(bank)}"
        )

        return

    # شارژ بانک
    if text.startswith("شارژ بانک "):
        amount_text = text[len("شارژ بانک "):].strip()

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار درست وارد کن."
            )
            return

        await bank_deposit(
            update,
            user_id,
            amount
        )

        return

    # برداشت بانک
    if text.startswith("برداشت بانک "):
        amount_text = text[len("برداشت بانک "):].strip()

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار درست وارد کن."
            )
            return

        await bank_withdraw(
            update,
            user_id,
            amount
        )

        return

    # انتقال
    if text.startswith("انتقال "):
        amount_text = text[len("انتقال "):].strip()

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار انتقال درست نیست."
            )
            return

        await transfer(
            update,
            user_id,
            amount
        )

        return

    # ساخت سریال
    if text.startswith("ساخت سریال "):
        amount_text = text[len("ساخت سریال "):].strip()

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مبلغ سریال درست نیست."
            )
            return

        await create_serial(
            update,
            user_id,
            amount
        )

        return

    # استفاده از سریال
    if text.startswith("سریال "):
        code = text[len("سریال "):].strip()

        await use_serial(
            update,
            user_id,
            code
        )

        return

    # خرید ماینر
    if text.startswith("خرید ") and "ماینر" in text:
        parts = text.split()

        try:
            count = int(parts[1])
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ تعداد ماینر درست نیست."
            )
            return

        level = 1

        if "سطح" in parts:
            try:
                index = parts.index("سطح")
                level = int(parts[index + 1])
            except (ValueError, IndexError):
                await update.message.reply_text(
                    "❌ سطح ماینر درست نیست."
                )
                return

        if count <= 0:
            await update.message.reply_text(
                "❌ تعداد درست نیست."
            )
            return

        if level < 1 or level > 100:
            await update.message.reply_text(
                "❌ سطح باید بین 1 تا 100 باشد."
            )
            return

        await buy_miner(
            update,
            user_id,
            count,
            level
        )

        return

    # برداشت ماینر
    if text == "برداشت ماینر":
        await claim_miner(
            update,
            user_id
        )
        return

    # سنگ کاغذ قیچی
    choices = [
        "سنگ",
        "کاغذ",
        "قیچی"
    ]

    for choice in choices:
        if text.startswith(choice + " "):
            amount_text = text[
                len(choice) + 1:
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مقدار شرط درست نیست."
                )
                return

            bot_choice = random.choice(choices)

          
