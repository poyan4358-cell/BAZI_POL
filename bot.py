# =========================
# ماشین حساب
# =========================

async def calculator(update, context):

    expression = update.message.text.strip()

    # فقط کاراکترهای ریاضی مجاز
    allowed = "0123456789+-*/().% "

    if not all(char in allowed for char in expression):
        return

    try:
        result = eval(
            expression,
            {"__builtins__": {}},
            {}
        )

        await update.message.reply_text(
            f"🧮 جواب: {result}"
        )

    except ZeroDivisionError:
        await update.message.reply_text(
            "❌ تقسیم بر صفر ممکن نیست."
        )

    except Exception:
        await update.message.reply_text(
            "❌ عبارت ریاضی اشتباهه."
        )
