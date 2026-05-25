import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8653733851:AAEYRtSrWAxxE3pSLmCBxh6SjuRYzdzzrzs"
ADMIN_ID = 8167182526  # Твой Telegram ID
SUPPORT_USERNAME = "@username"

DNS_PRICE = 299
VPN_PRICE = 499
PAYMENT_DETAILS = "Переведите на карту Сбер: 4276 1234 5678 9012\nИван И."
# ===============================

# База данных
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    dns_purchases INTEGER DEFAULT 0,
    vpn_purchases INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pending_payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product TEXT,
    amount INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TEXT
)
""")
conn.commit()

def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user is None:
        cursor.execute("INSERT INTO users (user_id, dns_purchases, vpn_purchases) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
        return {"user_id": user_id, "dns_purchases": 0, "vpn_purchases": 0}
    return {"user_id": user[0], "dns_purchases": user[1] or 0, "vpn_purchases": user[2] or 0}

def add_purchase(user_id: int, product: str):
    if product == 'dns':
        cursor.execute("UPDATE users SET dns_purchases = dns_purchases + 1 WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("UPDATE users SET vpn_purchases = vpn_purchases + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def save_payment(user_id: int, product: str, amount: int):
    cursor.execute("INSERT INTO pending_payments (user_id, product, amount, created_at) VALUES (?, ?, ?, ?)",
                  (user_id, product, amount, datetime.now().isoformat()))
    conn.commit()
    return cursor.lastrowid

def get_all_payments():
    cursor.execute("SELECT payment_id, user_id, product, amount, status, created_at FROM pending_payments ORDER BY payment_id DESC")
    return cursor.fetchall()

def update_payment_status(payment_id: int, status: str):
    cursor.execute("UPDATE pending_payments SET status = ? WHERE payment_id = ?", (status, payment_id))
    conn.commit()

# ========== КЛАВИАТУРЫ ==========

main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🛒 Купить DNS"), KeyboardButton("🔐 Купить VPN")],
    [KeyboardButton("📊 Статистика"), KeyboardButton("🆘 Поддержка")]
], resize_keyboard=True)

admin_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("📋 Список оплат"), KeyboardButton("📊 Статистика бота")],
    [KeyboardButton("👥 Список пользователей"), KeyboardButton("🔙 Выйти из админки")]
], resize_keyboard=True)

# ========== ОБРАБОТЧИКИ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)
    
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "👋 **Админ-панель**\n\n"
            "Выберите действие:",
            reply_markup=admin_keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Привет! Я бот по продаже DNS и VPN.\n\n"
            f"💰 DNS - {DNS_PRICE} руб.\n"
            f"💰 VPN - {VPN_PRICE} руб.\n\n"
            "Выберите действие:",
            reply_markup=main_keyboard
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # Админ-меню
    if user_id == ADMIN_ID:
        if text == "📋 Список оплат":
            payments = get_all_payments()
            if not payments:
                await update.message.reply_text("📭 Нет оплат в ожидании")
                return
            
            msg = "📋 **Список оплат:**\n\n"
            for p in payments:
                msg += f"ID: {p[0]} | Пользователь: {p[1]} | {p[2].upper()} | {p[3]} руб. | {p[4]}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        
        elif text == "📊 Статистика бота":
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(dns_purchases) FROM users")
            total_dns = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(vpn_purchases) FROM users")
            total_vpn = cursor.fetchone()[0] or 0
            
            await update.message.reply_text(
                f"📊 **Статистика бота**\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"🌐 Продано DNS: {total_dns}\n"
                f"🔐 Продано VPN: {total_vpn}\n"
                f"💰 Выручка: {total_dns * DNS_PRICE + total_vpn * VPN_PRICE} руб."
            )
            return
        
        elif text == "👥 Список пользователей":
            cursor.execute("SELECT user_id, dns_purchases, vpn_purchases FROM users ORDER BY user_id")
            users = cursor.fetchall()
            if not users:
                await update.message.reply_text("📭 Нет пользователей")
                return
            
            msg = "👥 **Список пользователей:**\n\n"
            for u in users:
                msg += f"ID: {u[0]} | DNS: {u[1] or 0} | VPN: {u[2] or 0}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return
        
        elif text == "🔙 Выйти из админки":
            await update.message.reply_text(
                "👋 Вы вышли из админ-панели",
                reply_markup=main_keyboard
            )
            return
        
        # Если админ в режиме отправки ссылки
        if context.user_data.get('awaiting_link'):
            buyer_id = context.user_data['awaiting_link']
            product = context.user_data.get('product_for_link', 'vpn')
            link = text.strip()
            
            if not (link.startswith("https://t.me/") or link.startswith("t.me/")):
                await update.message.reply_text(
                    "❌ Это не похоже на ссылку Telegram!\n"
                    "Отправьте ссылку вида: https://t.me/+код_приглашения"
                )
                return
            
            try:
                product_name = "DNS" if product == 'dns' else "VPN"
                await context.bot.send_message(
                    buyer_id,
                    f"✅ **Оплата подтверждена!**\n\n"
                    f"📦 Товар: **{product_name}**\n\n"
                    f"🔗 **Ссылка для доступа:**\n{link}\n\n"
                    f"💡 Нажмите на ссылку и присоединитесь к каналу.\n\n"
                    f"📞 Поддержка: {SUPPORT_USERNAME}",
                    parse_mode="Markdown"
                )
                
                add_purchase(buyer_id, product)
                
                await update.message.reply_text(
                    f"✅ Ссылка отправлена пользователю {buyer_id}!\n"
                    f"📦 Товар: {product_name}\n"
                    f"🔗 Ссылка: {link}"
                )
                
                context.user_data['awaiting_link'] = False
                context.user_data['product_for_link'] = None
                
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка при отправке: {e}")
            return

    # Обычные пользователи
    if text == "🛒 Купить DNS":
        context.user_data.clear()
        context.user_data['selected_product'] = 'dns'
        context.user_data['waiting_for_payment'] = True
        await update.message.reply_text(
            f"🌐 **Покупка DNS**\n\n"
            f"💰 Цена: {DNS_PRICE} руб.\n\n"
            f"💳 Реквизиты оплаты:\n{PAYMENT_DETAILS}\n\n"
            f"📸 После оплаты пришлите скриншот или фото чека.",
            parse_mode="Markdown"
        )

    elif text == "🔐 Купить VPN":
        context.user_data.clear()
        context.user_data['selected_product'] = 'vpn'
        context.user_data['waiting_for_payment'] = True
        await update.message.reply_text(
            f"🔒 **Покупка VPN**\n\n"
            f"💰 Цена: {VPN_PRICE} руб.\n\n"
            f"💳 Реквизиты оплаты:\n{PAYMENT_DETAILS}\n\n"
            f"📸 После оплаты пришлите скриншот или фото чека.",
            parse_mode="Markdown"
        )

    elif text == "📊 Статистика":
        user = get_user(user_id)
        dns = user['dns_purchases'] or 0
        vpn = user['vpn_purchases'] or 0
        await update.message.reply_text(
            f"📊 **Ваша статистика:**\n\n"
            f"🌐 Куплено DNS: **{dns}** шт.\n"
            f"🔐 Куплено VPN: **{vpn}** шт.\n"
            f"📦 Всего покупок: **{dns + vpn}** шт."
        )

    elif text == "🆘 Поддержка":
        await update.message.reply_text(f"📞 Связь с поддержкой: {SUPPORT_USERNAME}")

    else:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_keyboard)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.user_data.get('waiting_for_payment'):
        await update.message.reply_text("❌ Сначала выберите товар через меню.")
        return
    
    product = context.user_data.get('selected_product')
    if not product:
        await update.message.reply_text("❌ Ошибка. Выберите товар заново.")
        return
    
    context.user_data['waiting_for_payment'] = False
    
    price = DNS_PRICE if product == 'dns' else VPN_PRICE
    product_name = "DNS" if product == 'dns' else "VPN"
    
    user = get_user(user_id)
    name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    
    info = (
        f"🆕 **НОВЫЙ ЧЕК!**\n\n"
        f"📦 Товар: **{product_name}**\n"
        f"💰 Сумма: **{price} руб.**\n"
        f"👤 Покупатель: {name}\n"
        f"🆔 ID: {user_id}\n"
        f"📊 DNS: {user['dns_purchases'] or 0} | VPN: {user['vpn_purchases'] or 0}"
    )
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok_{product}_{user_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
    ]])
    
    await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=info, reply_markup=keyboard)
    await update.message.reply_text("✅ Чек отправлен на проверку. Ожидайте.", reply_markup=main_keyboard)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        return
    
    if not context.user_data.get('waiting_for_payment'):
        await update.message.reply_text("❌ Сначала выберите товар через меню.")
        return
    
    product = context.user_data.get('selected_product')
    if not product:
        await update.message.reply_text("❌ Ошибка. Выберите товар заново.")
        return
    
    context.user_data['waiting_for_payment'] = False
    
    price = DNS_PRICE if product == 'dns' else VPN_PRICE
    product_name = "DNS" if product == 'dns' else "VPN"
    
    user = get_user(user_id)
    name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    
    info = (
        f"🆕 **НОВЫЙ ЧЕК!**\n\n"
        f"📦 Товар: **{product_name}**\n"
        f"💰 Сумма: **{price} руб.**\n"
        f"👤 Покупатель: {name}\n"
        f"🆔 ID: {user_id}\n"
        f"📊 DNS: {user['dns_purchases'] or 0} | VPN: {user['vpn_purchases'] or 0}"
    )
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok_{product}_{user_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
    ]])
    
    await context.bot.send_document(ADMIN_ID, update.message.document.file_id, caption=info, reply_markup=keyboard)
    await update.message.reply_text("✅ Чек отправлен на проверку. Ожидайте.", reply_markup=main_keyboard)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("ok_"):
        _, product, buyer_id = data.split("_")
        buyer_id = int(buyer_id)
        
        context.user_data['awaiting_link'] = buyer_id
        context.user_data['product_for_link'] = product
        
        await query.edit_message_caption(
            caption=query.message.caption + f"\n\n✅ ОПЛАЧЕНО\n\n📝 Теперь отправьте ссылку на приватный канал"
        )
        await context.bot.send_message(
            ADMIN_ID,
            f"🔗 **Отправьте ссылку на приватный канал**\n\n"
            f"🆔 ID покупателя: {buyer_id}\n"
            f"📦 Товар: {product.upper()}\n\n"
            f"💡 Просто напишите ссылку на канал (например: https://t.me/+код)\n"
            f"Пользователь сразу её получит!"
        )
    
    elif data.startswith("no_"):
        buyer_id = int(data[3:])
        try:
            await context.bot.send_message(buyer_id, "❌ Ваш чек отклонён. Свяжитесь с поддержкой.")
        except:
            pass
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ ОТКЛОНЕНО")

# ========== ЗАПУСК ==========
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("=" * 50)
    print("✅ Бот запущен!")
    print(f"👨‍💼 Админ ID: {ADMIN_ID}")
    print("📝 Как работать:")
    print("   1. Пользователь присылает чек")
    print("   2. Админ нажимает ✅ Подтвердить")
    print("   3. Админ отправляет ссылку на канал")
    print("   4. Пользователь получает ссылку")
    print("=" * 50)
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()