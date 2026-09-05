# -*- coding: utf-8 -*-

import random
import re
import secrets
import sqlite3
import string
import time

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


# =========================================================
# CONFIG
# =========================================================

TOKEN = "YOUR_BOT_TOKEN"
OWNER_ID = 123456789

DB_FILE = "moltaf_kid.db"

OWNER_MONEY = 10**100


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    wallet INTEGER NOT NULL DEFAULT 0,
    bank INTEGER NOT NULL DEFAULT 0,
    record INTEGER NOT NULL DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS serials (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
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
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0
)
""")

db.commit()


# =========================================================
# BASIC FUNCTIONS
# =========================================================

def owner(user_id):
    return user_id == OWNER_ID


def ensure_user(user):
    db.execute("""
        INSERT INTO users(user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or ""
    ))
    db.commit()


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def get_wallet(user_id):
    if owner(user_id):
        return OWNER_MONEY

    row = get_user(user_id)
    return row["wallet"] if row else 0


def get_bank(user_id):
    if owner(user_id):
        return OWNER_MONEY

    row = get_user(user_id)
    return row["bank"] if row else 0


def set_wallet(user_id, amount):
    if owner(user_id):
        return

    db.execute(
        "UPDATE users SET wallet=? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()
    update_record(user_id)


def add_wallet(user_id, amount):
    if owner(user_id):
        return

    db.execute(
        "UPDATE users SET wallet=wallet+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()
    update_record(user_id)


def add_bank(user_id, amount):
    if owner(user_id):
        return

    db.execute(
        "UPDATE users SET bank=bank+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()


def update_record(user_id):
    if owner(user_id):
        return

    db.execute("""
        UPDATE users
        SET record=wallet
        WHERE user_id=? AND wallet>record
    """, (user_id,))
    db.commit()


def fmt(number):
    return f"{int(number):,}"


def rank_of(user_id):
    if owner(user_id):
        return 1

    money = get_wallet(user_id)

    row = db.execute("""
        SELECT COUNT(*) AS amount
        FROM users
        WHERE wallet > ?
    """, (money,)).fetchone()

    return row["amount"] + 1


# =========================================================
# GROUP ACTIVE
# =========================================================

def group_active(chat_id):
    row = db.execute(
        "SELECT active FROM groups WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    return bool(row["active"]) if row else False


def set_group_active(chat_id, value):
    db.execute("""
        INSERT INTO groups(chat_id, active)
        VALUES (?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET active=excluded.active
    """, (chat_id, int(value)))

    db.commit()


# =========================================================
# MONEY PARSER
# =========================================================

UNITS = {
    "کا": 10**3,
    "میل": 10**6,
    "بیل": 10**9,
    "تیل": 10**12,
    "کیل": 10**15,
}


def clean(text):
    text = text.lower().strip()

    text = text.replace(",", "")
    text = text.replace("،", "")
    text = text.replace("_", "")

    text = text.replace("سکه", "")
    text = text.replace("تومان", "")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_amount(text):
    text = clean(text)

    m = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)\s*(کا|میل|بیل|تیل|کیل)?",
        text
    )

    if not m:
        raise ValueError

    number = float(m.group(1))
    unit = m.group(2)

    if unit:
        number *= UNITS[unit]

    if number <= 0 or number != int(number):
        raise ValueError

    return int(number)


def parse_bet(text, money):
    text = clean(text)

    if text in ("کل", "همه", "تمام"):
        amount = money

    elif text == "نصف":
        amount = money // 2

    elif text == "ثلث":
        amount = money // 3

    elif text == "خمس":
        amount = money // 5

    else:
        amount = parse_amount(text)

    if amount <= 0:
        raise ValueError

    return amount


# =========================================================
# BALANCE
# =========================================================

async def balance(update):
    user = update.effective_user
    ensure_user(user)

    row = get_user(user.id)

    current = get_wallet(user.id)

    if owner(user.id):
        record = OWNER_MONEY
    else:
        record = row["record"]

    rank = rank_of(user.id)

    await update.message.reply_text(
        f"موجودی اکانت شما = {fmt(current)} 💰\n\n"
        f"رکورد بیشترین موجودی شما = {fmt(record)} 💰\n\n"
        f"رتبه شما = {rank:,} 🎖"
    )


# =========================================================
# BANK
# =========================================================

async def show_bank(update):
    user = update.effective_user
    ensure_user(user)

    await update.message.reply_text(
        f"موجودی حساب بانکی شما = {fmt(get_bank(user.id))} 💰"
    )


async def deposit_bank(update, text):
    user = update.effective_user
    ensure_user(user)

    if owner(user.id):
        await update.message.reply_text(
            "حساب مالک نامحدود است 🗿"
        )
        return

    try:
        amount = parse_amount(text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ نامعتبر است ❌"
        )
        return

    if get_wallet(user.id) < amount:
        await update.message.reply_text(
            "موجودی کیف پول شما کافی نیست ❌"
        )
        return

    add_wallet(user.id, -amount)
    add_bank(user.id, amount)

    await update.message.reply_text(
        "مبلغ با موفقیت در بانک قرار گرفت ✅"
    )


async def withdraw_bank(update, text):
    user = update.effective_user
    ensure_user(user)

    if owner(user.id):
        await update.message.reply_text(
            "حساب مالک نامحدود است 🗿"
        )
        return

    try:
        amount = parse_amount(text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ نامعتبر است ❌"
        )
        return

    if get_bank(user.id) < amount:
        await update.message.reply_text(
            "موجودی حساب بانکی شما کافی نیست ❌"
        )
        return

    add_bank(user.id, -amount)
    add_wallet(user.id, amount)

    await update.message.reply_text(
        "مبلغ با موفقیت از بانک برداشت شد ✅"
    )


# =========================================================
# TRANSFER
# =========================================================

async def transfer(update, text):
    user = update.effective_user
    ensure_user(user)

    reply = update.message.reply_to_message

    if not reply:
        await update.message.reply_text(
            "برای انتقال باید روی پیام کاربر ریپلای کنی.\n\n"
            "مثال:\n"
            "انتقال 5 بیل"
        )
        return

    target = reply.from_user

    if target.id == user.id:
        await update.message.reply_text(
            "نمی‌توانی به خودت انتقال بدهی ❌"
        )
        return

    ensure_user(target)

    try:
        amount = parse_amount(text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ نامعتبر است ❌"
        )
        return

    before = get_wallet(user.id)

    if before < amount:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if not owner(user.id):
        add_wallet(user.id, -amount)

    add_wallet(target.id, amount)

    await update.message.reply_text(
        "انتقال بمب کوین با موفقیت انجام شد ✅\n\n"
        f"مقدار انتقال = {fmt(amount)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰\n\n"
        f"موجودی طرف مقابل = {fmt(get_wallet(target.id))} 💰"
    )


# =========================================================
# SERIAL
# =========================================================

def make_serial():
    chars = string.ascii_letters + string.digits

    return "".join(
        secrets.choice(chars)
        for _ in range(20)
    )


async def create_serial(update, text, context):
    user = update.effective_user
    ensure_user(user)

    try:
        amount = parse_amount(text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ سریال نامعتبر است ❌"
        )
        return

    if get_wallet(user.id) < amount:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if not owner(user.id):
        add_wallet(user.id, -amount)

    code = make_serial()

    db.execute("""
        INSERT INTO serials(
            code,
            amount,
            creator_id,
            used,
            created_at
        )
        VALUES (?, ?, ?, 0, ?)
    """, (
        code,
        amount,
        user.id,
        int(time.time())
    ))

    db.commit()

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                "سریال با موفقیت ساخته شد ✅\n\n"
                f"مقدار سریال = {fmt(amount)} 💰\n\n"
                f"کد سریال:\n{code}"
            )
        )

        await update.message.reply_text(
            "سریال ساخته شد و به پیوی شما ارسال شد ✅"
        )

    except Exception:
        db.execute(
            "DELETE FROM serials WHERE code=?",
            (code,)
        )
        db.commit()

        if not owner(user.id):
            add_wallet(user.id, amount)

        await update.message.reply_text(
            "نتونستم به پیوی شما پیام بدم ❌\n"
            "اول به بات خصوصی پیام بده."
        )


async def use_serial(update, code):
    user = update.effective_user
    ensure_user(user)

    code = code.strip()

    row = db.execute("""
        SELECT amount, used
        FROM serials
        WHERE code=?
    """, (code,)).fetchone()

    if not row:
        await update.message.reply_text(
            "سریال نامعتبر است ❌"
        )
        return

    if row["used"]:
        await update.message.reply_text(
            "این سریال قبلاً استفاده شده ❌"
        )
        return

    amount = row["amount"]

    db.execute("""
        UPDATE serials
        SET used=1
        WHERE code=?
    """, (code,))

    db.commit()

    add_wallet(user.id, amount)

    await update.message.reply_text(
        "سریال با موفقیت فعال شد ✅\n\n"
        f"مقدار دریافت‌شده = {fmt(amount)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
    )


# =========================================================
# MINERS
# =========================================================

def miner_rate(level):
    return 1000 * (2 ** (level - 1))


def miner_price(level):
    return 1_000_000 * (2 ** (level - 1))


async def buy_miner(update, count, level):
    user = update.effective_user
    ensure_user(user)

    try:
        count = int(count)
        level = int(level)
    except ValueError:
        await update.message.reply_text(
            "تعداد یا سطح ماینر نامعتبر است ❌"
        )
        return

    if count <= 0 or level <= 0:
        await update.message.reply_text(
            "تعداد و سطح باید بیشتر از صفر باشد ❌"
        )
        return

    if level > 100:
        await update.message.reply_text(
            "حداکثر سطح ماینر 100 است ❌"
        )
        return

    price = miner_price(level)
    total = price * count

    if get_wallet(user.id) < total:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if not owner(user.id):
        add_wallet(user.id, -total)

    now = int(time.time())

    db.executemany("""
        INSERT INTO miners(user_id, level, last_claim)
        VALUES (?, ?, ?)
    """, [
        (user.id, level, now)
        for _ in range(count)
    ])

    db.commit()

    await update.message.reply_text(
        "ماینر با موفقیت خریداری شد ✅\n\n"
        f"سطح = {level}\n"
        f"تعداد = {fmt(count)}\n"
        f"قیمت هر ماینر = {fmt(price)} 💰\n"
        f"هزینه کل = {fmt(total)} 💰\n\n"
        f"موجودی فعلی = {fmt(get_wallet(user.id))} 💰"
    )


async def claim_miner(update):
    user = update.effective_user
    ensure_user(user)

    rows = db.execute("""
        SELECT *
        FROM miners
        WHERE user_id=?
    """, (user.id,)).fetchall()

    if not rows:
        await update.message.reply_text(
            "شما ماینری ندارید ❌"
        )
        return

    now = int(time.time())
    total = 0

    for row in rows:
        seconds = max(
            0,
            now - row["last_claim"]
        )

        total += seconds * miner_rate(row["level"])

    db.execute(
        "DELETE FROM miners WHERE user_id=?",
        (user.id,)
    )

    db.commit()

    add_wallet(user.id, total)

    await update.message.reply_text(
        "برداشت ماینر با موفقیت انجام شد ✅\n\n"
        f"سکه تولیدشده = {fmt(total)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
    )


# =========================================================
# BET SYSTEM
# =========================================================

def remove_bet(user_id, amount):
    if get_wallet(user_id) < amount:
        return False

    if not owner(user_id):
        add_wallet(user_id, -amount)

    return True


def win(user_id, amount):
    add_wallet(user_id, amount * 2)


# =========================================================
# ROCK PAPER SCISSORS
# =========================================================

async def rps(update, choice, bet_text):
    user = update.effective_user
    ensure_user(user)

    choices = {
        "سنگ": "سنگ 🪨",
        "کاغذ": "کاغذ 📜",
        "قیچی": "قیچی ✂️"
    }

    try:
        amount = parse_bet(
            bet_text,
            get_wallet(user.id)
        )
    except ValueError:
        await update.message.reply_text(
            "مقدار شرط نامعتبر است ❌"
        )
        return

    before = get_wallet(user.id)

    if not remove_bet(user.id, amount):
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    bot_choice = random.choice(
        list(choices.keys())
    )

    if choice == bot_choice:
        add_wallet(user.id, amount)

        await update.message.reply_text(
            "مساوی شدید 🤝\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط = {fmt(amount)} 💰\n"
            f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
        )
        return

    win_game = (
        (choice == "سنگ" and bot_choice == "قیچی")
        or
        (choice == "کاغذ" and bot_choice == "سنگ")
        or
        (choice == "قیچی" and bot_choice == "کاغذ")
    )

    if win_game:
        win(user.id, amount)

        await update.message.reply_text(
            "شما برنده شدید ✅🥳\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما : {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما : {fmt(get_wallet(user.id))} 💰"
        )

    else:
        await update.message.reply_text(
            "شما باختید ❌\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما : {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما : {fmt(get_wallet(user.id))} 💰"
        )


# =========================================================
# COIN
# =========================================================

async def coin(update, choice, bet_text):
    user = update.effective_user
    ensure_user(user)

    try:
        amount = parse_bet(
            bet_text,
            get_wallet(user.id)
        )
    except ValueError:
        await update.message.reply_text(
            "مقدار شرط نامعتبر است ❌"
        )
        return

    before = get_wallet(user.id)

    if not remove_bet(user.id, amount):
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice(["شیر", "خط"])

    if choice == result:
        win(user.id, amount)

        await update.message.reply_text(
            "🥳✅ خوشبختانه بردی 🥳✅\n\n"
            f"حدس تو = {choice} 💡\n"
            f"سمت رو شده = {result} 🪙\n\n"
            f"مقدار سکه شرط = {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما = {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
        )

    else:
        await update.message.reply_text(
            "🙁❌ متاسفانه باختی ❌🙁\n\n"
            f"حدس تو = {choice} 💡\n"
            f"سمت رو شده = {result} 🪙\n\n"
            f"مقدار سکه شرط = {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما = {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
        )


# =========================================================
# RIGHT / LEFT
# =========================================================

async def right_left(update, choice, bet_text):
    user = update.effective_user
    ensure_user(user)

    try:
        amount = parse_bet(
            bet_text,
            get_wallet(user.id)
        )
    except ValueError:
        await update.message.reply_text(
            "مقدار شرط نامعتبر است ❌"
        )
        return

    before = get_wallet(user.id)

    if not remove_bet(user.id, amount):
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice(["راست", "چپ"])

    if choice == result:
        win(user.id, amount)

        await update.message.reply_text(
            "🥳✅ خوشبختانه برنده شدی 🥳✅\n\n"
            "╭✦───✧◈✧───✦╮\n"
            "     ✋️          🪸\n"
            "╰✦───✧◈✧───✦╯\n\n"
            f"حدس شما : دست {choice} ✨\n\n"
            f"مقدار شرط سکه = {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما = {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
        )

    else:
        await update.message.reply_text(
            "😔❌ متاسفانه باختی 😔❌\n\n"
            "╭✦───✧◈✧───✦╮\n"
            "     ✋️          🪻\n"
            "╰✦───✧◈✧───✦╯\n\n"
            f"حدس شما : دست {choice} ✨\n\n"
            f"مقدار شرط سکه = {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما = {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما = {fmt(get_wallet(user.id))} 💰"
        )


# =========================================================
# ODD / EVEN
# =========================================================

async def odd_even(update, choice, bet_text):
    user = update.effectiv
