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

OWNER_ID = 8981018900

DB_FILE = "moltaf_kid.db"

OWNER_MONEY = 10**100


# =========================================================
# DATABASE CONNECTION
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
# USER
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


# =========================================================
# MONEY
# =========================================================

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
        "کواد": 10**18,
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
# GROUP SYSTEM
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

    if row:
        return bool(row["active"])

    return False


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

def get_miner(user_id):
    cur = db.cursor()

    cur.execute(
        "SELECT * FROM miners WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        return row

    return None


async def buy_miner(update, user_id, count, level):
    if count <= 0:
        await update.message.reply_text(
            "❌ تعداد ماینر درست نیست."
        )
        return

    if level < 1:
        level = 1

    price_per_miner = 1000000 * level
    total_price = count * price_per_miner

    if user_id != OWNER_ID:
        if not remove_money(user_id, total_price):
            await update.message.reply_text(
                f"❌ سکه کافی نداری.\n"
                f"💰 قیمت: {format_money(total_price)}"
            )
            return

    cur = db.cursor()

    row = get_miner(user_id)

    if row:
        old_level = row["level"]

        if level > old_level:
            new_level = level
        else:
            new_level = old_level

        cur.execute(
            """
            UPDATE miners
            SET count = count + ?, level = ?
            WHERE user_id = ?
            """,
            (count, new_level, user_id)
        )

    else:
        cur.execute(
            """
            INSERT INTO miners
            (user_id, count, level, last_claim)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, count, level, 0)
        )

    db.commit()

    await update.message.reply_text(
        f"⛏ {count} ماینر سطح {level} خریدی!\n"
        f"💰 هزینه: {format_money(total_price)}"
    )


async def claim_miner(update, user_id):
    row = get_miner(user_id)

    if not row or row["count"] <= 0:
        await update.message.reply_text(
            "❌ هنوز ماینری نداری."
        )
        return

    now = time.time()
    last_claim = row["last_claim"]

    cooldown = 3600

    if last_claim and now - last_claim < cooldown:
        remaining = int(
            cooldown - (now - last_claim)
        )

        minutes = remaining // 60
        seconds = remaining % 60

        await update.message.reply_text(
            f"⏳ هنوز وقت برداشت نرسیده.\n"
            f"🕐 {minutes} دقیقه و {seconds} ثانیه باقی مانده."
        )
        return

    reward_per_miner = 500000 * row["level"]
    reward = row["count"] * reward_per_miner

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
        f"⛏ تعداد: {row['count']}\n"
        f"⭐ سطح: {row['level']}\n"
        f"💰 دریافتی: {format_money(reward)}"
)
    # =========================================================
# GAME: ROCK PAPER SCISSORS
# =========================================================

async def play_rps(update, user_id, choice, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    choices = [
        "سنگ",
        "کاغذ",
        "قیچی"
    ]

    bot_choice = random.choice(choices)

    if bot_choice == choice:
        add_money(
            user_id,
            amount
        )

        await update.message.reply_text(
            f"🤖 انتخاب من: {bot_choice}\n"
            f"🤝 مساوی شد!\n"
            f"💰 سکه‌ات برگشت."
        )

        return

    win = (
        (choice == "سنگ" and bot_choice == "قیچی")
        or
        (choice == "کاغذ" and bot_choice == "سنگ")
        or
        (choice == "قیچی" and bot_choice == "کاغذ")
    )

    if win:
        reward = amount * 2

        add_money(
            user_id,
            reward
        )

        await update.message.reply_text(
            f"🤖 انتخاب من: {bot_choice}\n"
            f"🎉 بردی!\n"
            f"💰 دریافتی: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"🤖 انتخاب من: {bot_choice}\n"
            f"💀 باختی!\n"
            f"💸 از دست دادی: {format_money(amount)}"
        )


# =========================================================
# GAME: COIN
# =========================================================

async def play_coin(update, user_id, choice, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    bot_choice = random.choice([
        "شیر",
        "خط"
    ])

    if bot_choice == choice:
        reward = amount * 2

        add_money(
            user_id,
            reward
        )

        await update.message.reply_text(
            f"🪙 نتیجه: {bot_choice}\n"
            f"🎉 بردی!\n"
            f"💰 دریافتی: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"🪙 نتیجه: {bot_choice}\n"
            f"💀 باختی!\n"
            f"💸 از دست دادی: {format_money(amount)}"
        )


# =========================================================
# GAME: RIGHT / LEFT
# =========================================================

async def play_direction(update, user_id, choice, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    bot_choice = random.choice([
        "راست",
        "چپ"
    ])

    if bot_choice == choice:
        reward = amount * 2

        add_money(
            user_id,
            reward
        )

        await update.message.reply_text(
            f"🤖 انتخاب من: {bot_choice}\n"
            f"🎉 درست گفتی!\n"
            f"💰 دریافتی: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"🤖 انتخاب من: {bot_choice}\n"
            f"💀 اشتباه بود!\n"
            f"💸 از دست دادی: {format_money(amount)}"
    )
        # =========================================================
# GAME: EVEN / ODD
# =========================================================

async def play_even_odd(update, user_id, choice, amount):
    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    number = random.randint(
        1,
        100
    )

    result = (
        "زوج"
        if number % 2 == 0
        else "فرد"
    )

    if result == choice:
        reward = amount * 2

        add_money(
            user_id,
            reward
        )

        await update.message.reply_text(
            f"🎲 عدد: {number}\n"
            f"📌 نتیجه: {result}\n"
            f"🎉 بردی!\n"
            f"💰 دریافتی: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"🎲 عدد: {number}\n"
            f"📌 نتیجه: {result}\n"
            f"💀 باختی!\n"
            f"💸 از دست دادی: {format_money(amount)}"
        )


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
🤖 راهنمای ملتفت کید

💰 اقتصاد:

موجودی
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

🎮 بازی‌ها:

سنگ 5 میل
کاغذ 5 میل
قیچی 5 میل

شیر 5 میل
خط 5 میل

راست 5 میل
چپ 5 میل

زوج 5 میل
فرد 5 میل

👑 فعال‌سازی گروه:

فقط مالک:

فعال
"""
# =========================================================
# MESSAGE HANDLER - PART 1
# =========================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    text = text.strip()
    lower = text.lower()

    user = update.message.from_user
    user_id = user.id

    ensure_user(user_id)

    # -----------------------------------------------------
    # ACTIVATE GROUP
    # -----------------------------------------------------

    if lower == "فعال":

        if user_id != OWNER_ID:
            await update.message.reply_text(
                "❌ فقط مالک ربات می‌تونه گروه رو فعال کنه."
            )
            return

        if update.effective_chat.type == "private":
            await update.message.reply_text(
                "❌ این دستور برای گروه ساخته شده."
            )
            return

        activate_group(
            update.effective_chat.id
        )

        await update.message.reply_text(
            "✅ گروه فعال شد!\n"
            "🤖 ملتفت کید آماده‌ست."
        )

        return

    # -----------------------------------------------------
    # CHECK GROUP
    # -----------------------------------------------------

    if update.effective_chat.type != "private":

        if not group_is_active(
            update.effective_chat.id
        ):
            return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    if lower in [
        "موجودی",
        "پول",
        "سکه"
    ]:

        money = get_money(
            user_id
        )

        await update.message.reply_text(
            f"💰 موجودی تو:\n"
            f"{format_money(money)}"
        )

        return

    # -----------------------------------------------------
    # BANK
    # -----------------------------------------------------

    if lower == "بانک":

        await update.message.reply_text(
            f"🏦 موجودی بانک:\n"
            f"{format_money(get_bank(user_id))}"
        )

        return

    if lower.startswith("شارژ بانک "):

        amount_text = text[
            len("شارژ بانک "):
        ]

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار رو درست وارد کن."
            )
            return

        await bank_deposit(
            update,
            user_id,
            amount
        )

        return

    if lower.startswith("برداشت بانک "):

        amount_text = text[
            len("برداشت بانک "):
        ]

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار رو درست وارد کن."
            )
            return

        await bank_withdraw(
            update,
            user_id,
            amount
        )

        return

    # -----------------------------------------------------
    # TRANSFER
    # -----------------------------------------------------

    if lower.startswith("انتقال "):

        amount_text = text[
            len("انتقال "):
        ]

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار رو درست وارد کن."
            )
            return

        await transfer(
            update,
            user_id,
            amount
        )

        return
        # =========================================================
# MESSAGE HANDLER - PART 2
# =========================================================

    # -----------------------------------------------------
    # CREATE SERIAL
    # -----------------------------------------------------

    if lower.startswith("ساخت سریال "):

        amount_text = text[
            len("ساخت سریال "):
        ]

        amount = parse_amount(
            amount_text,
            user_id
        )

        if amount is None:
            await update.message.reply_text(
                "❌ مقدار رو درست وارد کن."
            )
            return

        await create_serial(
            update,
            user_id,
            amount
        )

        return

    # -----------------------------------------------------
    # USE SERIAL
    # -----------------------------------------------------

    if lower.startswith("سریال "):

        code = text[
            len("سریال "):
        ].strip()

        if not code:
            await update.message.reply_text(
                "❌ کد سریال رو وارد کن."
            )
            return

        await use_serial(
            update,
            user_id,
            code
        )

        return

    # -----------------------------------------------------
    # BUY MINER
    # -----------------------------------------------------

    if (
        lower.startswith("خرید ")
        and "ماینر" in lower
    ):

        parts = text.split()

        try:
            count = int(parts[1])

        except (
            ValueError,
            IndexError
        ):

            await update.message.reply_text(
                "❌ تعداد ماینر رو درست وارد کن."
            )

            return

        level = 1

        if "سطح" in parts:

            try:
                index = parts.index(
                    "سطح"
                )

                level = int(
                    parts[index + 1]
                )

            except (
                ValueError,
                IndexError
            ):

                await update.message.reply_text(
                    "❌ سطح ماینر درست نیست."
                )

                return

        await buy_miner(
            update,
            user_id,
            count,
            level
        )

        return

    # -----------------------------------------------------
    # CLAIM MINER
    # -----------------------------------------------------

    if lower == "برداشت ماینر":

        await claim_miner(
            update,
            user_id
        )

        return

    # -----------------------------------------------------
    # ROCK PAPER SCISSORS
    # -----------------------------------------------------

    for choice in [
        "سنگ",
        "کاغذ",
        "قیچی"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_rps(
                update,
                user_id,
                choice,
                amount
            )

            return
            # =========================================================
# MESSAGE HANDLER - PART 3
# =========================================================

    # -----------------------------------------------------
    # COIN GAME
    # -----------------------------------------------------

    for choice in [
        "شیر",
        "خط"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_coin(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # DIRECTION GAME
    # -----------------------------------------------------

    for choice in [
        "راست",
        "چپ"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_direction(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # EVEN / ODD GAME
    # -----------------------------------------------------

    for choice in [
        "زوج",
        "فرد"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_even_odd(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if lower in [
        "کمک",
        "راهنما",
        "help"
    ]:

        await update.message.reply_text(
            HELP_TEXT
        )

        return
        # =========================================================
# MESSAGE HANDLER - PART 3
# =========================================================

    # -----------------------------------------------------
    # COIN GAME
    # -----------------------------------------------------

    for choice in [
        "شیر",
        "خط"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_coin(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # DIRECTION GAME
    # -----------------------------------------------------

    for choice in [
        "راست",
        "چپ"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_direction(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # EVEN / ODD GAME
    # -----------------------------------------------------

    for choice in [
        "زوج",
        "فرد"
    ]:

        if lower.startswith(
            choice + " "
        ):

            amount_text = text[
                len(choice):
            ].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None:
                await update.message.reply_text(
                    "❌ مبلغ درست نیست."
                )
                return

            await play_even_odd(
                update,
                user_id,
                choice,
                amount
            )

            return

    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if lower in [
        "کمک",
        "راهنما",
        "help"
    ]:

        await update.message.reply_text(
            HELP_TEXT
        )

        return
        # =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    print("ERROR:", context.error)


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    print("TOKEN FOUND:", bool(TOKEN))

    if not TOKEN:
        print("❌ BOT_TOKEN پیدا نشد.")
        return

    print("BOT STARTING...")

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("🤖 ملتفت کید آنلاین شد!")

    app.run_polling()


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()
