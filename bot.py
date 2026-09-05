import random
import re
import secrets
import sqlite3
import string
import time

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


# =========================
# SETTINGS
# =========================

TOKEN = "توکن_واقعی_ربات_اینجا"
OWNER_ID = 123456789

DB_FILE = "moltaf_kid.db"
OWNER_MONEY = 10**100


# =========================
# DATABASE
# =========================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    wallet INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    record INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS serials (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    used INTEGER DEFAULT 0,
    created_at INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS miners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    last_claim INTEGER NOT NULL
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS groups_active (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER DEFAULT 0
)
""")

db.commit()


# =========================
# USERS
# =========================

def ensure_user(user):
    if not user:
        return

    db.execute(
        """
        INSERT INTO users
        (user_id, username, first_name, wallet, bank, record)
        VALUES (?, ?, ?, 0, 0, 0)
        ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        first_name=excluded.first_name
        """,
        (
            user.id,
            user.username or "",
            user.first_name or ""
        )
    )
    db.commit()


def get_wallet(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    row = db.execute(
        "SELECT wallet FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if row:
        return int(row["wallet"])

    return 0


def set_wallet(user_id, amount):
    if user_id == OWNER_ID:
        return

    db.execute(
        "UPDATE users SET wallet=? WHERE user_id=?",
        (max(0, int(amount)), user_id)
    )
    db.commit()


def add_wallet(user_id, amount):
    if user_id == OWNER_ID:
        return

    db.execute(
        "UPDATE users SET wallet=wallet+? WHERE user_id=?",
        (int(amount), user_id)
    )
    db.commit()


def get_bank(user_id):
    row = db.execute(
        "SELECT bank FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if row:
        return int(row["bank"])

    return 0


def add_bank(user_id, amount):
    db.execute(
        "UPDATE users SET bank=bank+? WHERE user_id=?",
        (int(amount), user_id)
    )
    db.commit()


def update_record(user_id):
    if user_id == OWNER_ID:
        return

    wallet = get_wallet(user_id)

    db.execute(
        """
        UPDATE users
        SET record=?
        WHERE user_id=?
        AND record < ?
        """,
        (wallet, user_id, wallet)
    )

    db.commit()


def money(amount):
    return f"{int(amount):,}"


# =========================
# RANK
# =========================

def get_rank(user_id):
    if user_id == OWNER_ID:
        return 1

    wallet = get_wallet(user_id)

    row = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE wallet > ?
        AND user_id != ?
        """,
        (wallet, OWNER_ID)
    ).fetchone()

    return int(row["c"]) + 2


# =========================
# GROUP ACTIVATION
# =========================

def group_active(chat_id):
    row = db.execute(
        "SELECT active FROM groups_active WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    return bool(row and row["active"])


def activate_group(chat_id):
    db.execute(
        """
        INSERT INTO groups_active(chat_id, active)
        VALUES (?, 1)
        ON CONFLICT(chat_id)
        DO UPDATE SET active=1
        """,
        (chat_id,)
    )
    db.commit()


# =========================
# MONEY PARSER
# =========================

UNITS = {
    "کا": 10**3,
    "میل": 10**6,
    "بیل": 10**9,
    "تیل": 10**12,
    "کیل": 10**15
}


def parse_money(text):
    text = text.strip().lower()
    text = text.replace(",", "")
    text = text.replace("٬", "")
    text = text.replace(" ", "")

    if text in ("کل", "همه"):
        return "ALL"

    if text == "نصف":
        return "HALF"

    if text == "خمس":
        return "FIFTH"

    if text == "ثلث":
        return "THIRD"

    match = re.fullmatch(
        r"(\d+)(?:\.(\d+))?(کا|میل|بیل|تیل|کیل)?",
        text
    )

    if not match:
        return None

    whole = int(match.group(1))
    decimal = match.group(2)
    unit = match.group(3)

    if not unit:
        if decimal:
            return int(float(text))
        return whole

    value = whole * UNITS[unit]

    if decimal:
        value += (
            int(decimal) * UNITS[unit]
            // (10 ** len(decimal))
        )

    return value


def resolve_amount(text, balance):
    value = parse_money(text)

    if value == "ALL":
        return balance

    if value == "HALF":
        return balance // 2

    if value == "FIFTH":
        return balance // 5

    if value == "THIRD":
        return balance // 3

    if isinstance(value, int):
        return value

    return None


# =========================
# BET
# =========================

def take_bet(user_id, amount):
    balance = get_wallet(user_id)

    if amount <= 0:
        return False, balance

    if user_id != OWNER_ID and balance < amount:
        return False, balance

    if user_id != OWNER_ID:
        set_wallet(user_id, balance - amount)

    return True, balance


def win_bet(user_id, amount):
    if user_id != OWNER_ID:
        add_wallet(user_id, amount * 2)

    return get_wallet(user_id)


# =========================
# BALANCE
# =========================

async def balance_command(update):
    user = update.effective_user
    ensure_user(user)

    wallet = get_wallet(user.id)

    if user.id == OWNER_ID:
        record = "نامحدود"
        rank = 1
    else:
        row = db.execute(
            "SELECT record FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        record = money(row["record"] if row else 0)
        rank = get_rank(user.id)

    text = (
        f"موجودی اکانت شما = {money(wallet)} 💰\n\n"
        f"رکورد بیشترین موجودی شما = {record} 💰\n\n"
        f"رتبه شما = {rank} 🎖"
    )

    await update.message.reply_text(text)


# =========================
# BANK
# =========================

async def bank_command(update):
    user = update.effective_user
    ensure_user(user)

    text = (
        "موجودی حساب بانکی شما = "
        f"{money(get_bank(user.id))} 💰"
    )

    await update.message.reply_text(text)


async def bank_deposit(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    amount = resolve_amount(amount_text, balance)

    if amount is None or amount <= 0:
        await update.message.reply_text("مقدار سکه اشتباهه ❌")
        return

    if user.id != OWNER_ID and balance < amount:
        await update.message.reply_text("موجودی شما کافی نیست ❌")
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - amount)

    add_bank(user.id, amount)

    text = (
        "واریز به بانک با موفقیت انجام شد ✅\n\n"
        f"مقدار واریز = {money(amount)} 💰\n\n"
        f"موجودی فعلی بانک = "
        f"{money(get_bank(user.id))} 💰"
    )

    await update.message.reply_text(text)


async def bank_withdraw(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    bank = get_bank(user.id)
    amount = resolve_amount(amount_text, bank)

    if amount is None or amount <= 0:
        await update.message.reply_text("مقدار سکه اشتباهه ❌")
        return

    if bank < amount:
        await update.message.reply_text(
            "موجودی حساب بانکی شما کافی نیست ❌"
        )
        return

    add_bank(user.id, -amount)

    if user.id != OWNER_ID:
        add_wallet(user.id, amount)

    update_record(user.id)

    text = (
        "برداشت از بانک با موفقیت انجام شد ✅\n\n"
        f"مقدار برداشت = {money(amount)} 💰\n\n"
        f"موجودی فعلی بانک = "
        f"{money(get_bank(user.id))} 💰"
    )

    await update.message.reply_text(text)


# =========================
# TRANSFER
# =========================

async def transfer_command(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    message = update.message

    if not message.reply_to_message:
        await message.reply_text(
            "برای انتقال سکه باید روی پیام طرف ریپلای کنی ❌"
        )
        return

    target = message.reply_to_message.from_user

    if not target:
        return

    if target.id == user.id:
        await message.reply_text(
            "نمیشه به خودت سکه انتقال بدی 😂"
        )
        return

    ensure_user(target)

    balance = get_wallet(user.id)
    amount = resolve_amount(amount_text, balance)

    if amount is None or amount <= 0:
        await message.reply_text("مقدار سکه اشتباهه ❌")
        return

    if user.id != OWNER_ID and balance < amount:
        await message.reply_text("موجودی شما کافی نیست ❌")
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - amount)

    add_wallet(target.id, amount)

    update_record(user.id)
    update_record(target.id)

    text = (
        "انتقال سکه با موفقیت انجام شد ✅\n\n"
        f"مقدار انتقال = {money(amount)} 💰\n\n"
        f"موجودی فعلی شما = "
        f"{money(get_wallet(user.id))} 💰\n\n"
        f"موجودی طرف مقابل = "
        f"{money(get_wallet(target.id))} 💰"
    )

    await message.reply_text(text)


# =========================
# SERIAL
# =========================

def make_serial():
    chars = string.ascii_letters + string.digits

    return "".join(
        secrets.choice(chars)
        for _ in range(20)
    )


async def create_serial(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    amount = resolve_amount(amount_text, balance)

    if amount is None or amount <= 0:
        await update.message.reply_text(
            "مقدار سریال اشتباهه ❌"
        )
        return

    if user.id != OWNER_ID and balance < amount:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    code = make_serial()

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - amount)

    db.execute(
        """
        INSERT INTO serials
        (code, amount, creator_id, used, created_at)
        VALUES (?, ?, ?, 0, ?)
        """,
        (
            code,
            amount,
            user.id,
            int(time.time())
        )
    )

    db.commit()

    text = (
        "سریال ساخته شد ✅\n\n"
        f"مقدار سریال = {money(amount)} 💰\n\n"
        "کد سریال:\n\n"
        f"{code}"
    )

    await update.message.reply_text(text)


async def use_serial(update, code):
    user = update.effective_user
    ensure_user(user)

    code = code.strip()

    row = db.execute(
        """
        SELECT *
        FROM serials
        WHERE code=?
        AND used=0
        """,
        (code,)
    ).fetchone()

    if not row:
        await update.message.reply_text(
            "این سریال نامعتبره یا قبلاً استفاده شده ❌"
        )
        return

    amount = int(row["amount"])

    db.execute(
        """
        UPDATE serials
        SET used=1
        WHERE code=?
        AND used=0
        """,
        (code,)
    )

    db.commit()

    add_wallet(user.id, amount)
    update_record(user.id)

    text = (
        "سریال با موفقیت فعال شد ✅\n\n"
        f"سکه دریافت‌شده = {money(amount)} 💰\n\n"
        f"موجودی فعلی شما = "
        f"{money(get_wallet(user.id))} 💰"
    )

    await update.message.reply_text(text)


# =========================
# MINERS
# =========================

def miner_price(level):
    return 1_000_000 * (2 ** (level - 1))


def miner_rate(level):
    return 1_000 * (2 ** (level - 1))


def miner_stats(user_id):
    rows = db.execute(
        "SELECT * FROM miners WHERE user_id=?",
        (user_id,)
    ).fetchall()

    now = int(time.time())
    total = 0

    for row in rows:
        elapsed = max(
            0,
            now - int(row["last_claim"])
        )

        total += (
            elapsed *
            miner_rate(int(row["level"]))
        )

    return rows, total


async def buy_miner(update, count, level):
    user = update.effective_user
    ensure_user(user)

    if count <= 0 or level <= 0:
        await update.message.reply_text(
            "تعداد یا سطح ماینر اشتباهه ❌"
        )
        return

    price = miner_price(level)
    total = price * count
    balance = get_wallet(user.id)

    if user.id != OWNER_ID and balance < total:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - total)

    now = int(time.time())

    for _ in range(count):
        db.execute(
            """
            INSERT INTO miners
            (user_id, level, last_claim)
            VALUES (?, ?, ?)
            """,
            (user.id, level, now)
        )

    db.commit()

    text = (
        "خرید ماینر با موفقیت انجام شد ✅\n\n"
        f"تعداد = {count} ماینر\n"
        f"سطح = {level}\n\n"
        f"قیمت هر ماینر = {money(price)} 💰\n"
        f"مبلغ پرداختی = {money(total)} 💰\n\n"
        f"تولید هر ماینر = "
        f"{money(miner_rate(level))} سکه در ثانیه 💰"
    )

    await update.message.reply_text(text)


async def claim_miner(update):
    user = update.effective_user
    ensure_user(user)

    rows, earned = miner_stats(user.id)

    if not rows:
        await update.message.reply_text(
            "شما هیچ ماینری ندارید ❌"
        )
        return

    count = len(rows)

    db.execute(
        "DELETE FROM miners WHERE user_id=?",
        (user.id,)
    )

    db.commit()

    if user.id != OWNER_ID:
        add_wallet(user.id, earned)

    update_record(user.id)

    text = (
        "برداشت ماینر با موفقیت انجام شد ✅\n\n"
        f"تعداد ماینر = {count}\n\n"
        f"سکه تولیدشده = {money(earned)} 💰\n\n"
        f"موجودی فعلی شما = "
        f"{money(get_wallet(user.id))} 💰"
    )

    await update.message.reply_text(text)


# =========================
# ROCK PAPER SCISSORS
# =========================

async def rps_game(update, choice, bet_text):
    user = update.effective_user
    ensure_user(user)

    choices = {
        "سنگ": "سنگ 🪨",
        "کاغذ": "کاغذ 📜",
        "قیچی": "قیچی ✂️"
    }

    balance = get_wallet(user.id)
    bet = resolve_amount(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text(
            "مقدار شرط اشتباهه ❌"
        )
        return

    ok, old_balance = take_bet(
        user.id,
        bet
    )

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    bot_choice = random.choice(
        list(choices.keys())
    )

    wins = {
        ("سنگ", "قیچی"),
        ("کاغذ", "سنگ"),
        ("قیچی", "کاغذ")
    }

    if choice == bot_choice:
        result = "tie"
    elif (choice, bot_choice) in wins:
        result = "win"
    else:
        result = "lose"

    if result == "win":

        current = win_bet(
            user.id,
            bet
        )

        text = (
            "شما برنده شدید ✅🥳\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    elif result == "lose":

        current = get_wallet(user.id)

        text = (
            "شما باختید ❌\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    else:

        if user.id != OWNER_ID:
            add_wallet(user.id, bet)

        current = get_wallet(user.id)

        text = (
            "مساوی شدید 😐\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    update_record(user.id)

    await update.message.reply_text(text)


# =========================
# COIN
# =========================

async def coin_game(update, guess, bet_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    bet = resolve_amount(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text(
            "مقدار شرط اشتباهه ❌"
        )
        return

    ok, old_balance = take_bet(
        user.id,
        bet
    )

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice([
        "شیر",
        "خط"
    ])

    if guess == result:

        current = win_bet(
            user.id,
            bet
        )

        text = (
            "🥳✅ خوشبختانه بردی 🥳✅\n\n"
            f"حدس تو = {guess}\n"
            f"سمت رو شده = {result}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    else:

        current = get_wallet(user.id)

        text = (
            "🙁❌ متاسفانه باختی ❌🙁\n\n"
            f"حدس تو = {guess}\n"
            f"سمت رو شده = {result}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    update_record(user.id)

    await update.message.reply_text(text)


# =========================
# RIGHT / LEFT
# =========================

async def right_left_game(update, guess, bet_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    bet = resolve_amount(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text(
            "مقدار شرط اشتباهه ❌"
        )
        return

    ok, old_balance = take_bet(
        user.id,
        bet
    )

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice([
        "راست",
        "چپ"
    ])

    if guess == result:

        current = win_bet(
            user.id,
            bet
        )

        text = (
            "🥳✅ خوشبختانه برنده شدی 🥳✅\n\n"
            "╭✦───✧◈✧───✦╮\n"
            "     ✋️          🪸\n"
            "╰✦───✧◈✧───✦╯\n\n"
            f"حدس تو = {guess}\n"
            f"نتیجه = {result}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    else:

        current = get_wallet(user.id)

        text = (
            "🙁❌ متاسفانه باختی ❌🙁\n\n"
            "╭✦───✧◈✧───✦╮\n"
            "     ✋️          🪸\n"
            "╰✦───✧◈✧───✦╯\n\n"
            f"حدس تو = {guess}\n"
            f"نتیجه = {result}\n\n"
            f"شرط = {money(bet)} 💰\n\n"
            f"موجودی قبلی = {money(old_balance)} 💰\n\n"
            f"موجودی فعلی = {money(current)} 💰"
        )

    update_record(user.id)

    await update.message.reply_text(text)


# =========================
# ODD / EVEN
# =========================

async def odd_even_game(update, gue
