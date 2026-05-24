import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8438942183:AAFv3fE6kqaEBfRvp5bMvKm6emeeQIRtu44"
ADMIN_ID = 8167182526  # Твой Telegram ID
SUPPORT_USERNAME = "@belausn"

# Цены
DNS_PRICE = 150
VPN_PRICE = 200

# Реквизиты
PAYMENT_DETAILS = "Переведите на карту т банк: 2200700586011735."
# ===============================

# Подключение к базе данных
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

# Создаём таблицу пользователей
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    dns_purchases INTEGER DEFAULT 0,
    vpn_purchases INTEGER DEFAULT 0
)
""")

# Таблица промокодов
cursor.execute("""
CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    discount_type TEXT,
    discount_value INTEGER,
    expires_at TEXT,
    max_uses INTEGER,
    used_count INTEGER DEFAULT 0
)
""")

# Таблица использованных промокодов пользователями
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_promocodes (
    user_id INTEGER,
    code TEXT,
    used_at TEXT,
    FOREIGN KEY (code) REFERENCES promocodes(code)
)
""")

# Проверяем и добавляем колонки, если их нет
cursor.execute("PRAGMA table_info(users)")
columns = [col[1] for col in cursor.fetchall()]
if 'dns_purchases' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN dns_purchases INTEGER DEFAULT 0")
if 'vpn_purchases' not in columns:
    cursor.execute("ALTER TABLE users ADD COLUMN vpn_purchases INTEGER DEFAULT 0")

conn.commit()


def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user is None:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return {"user_id": user_id, "dns_purchases": 0, "vpn_purchases": 0}
    return {"user_id": user[0], "dns_purchases": user[1], "vpn_purchases": user[2]}


def add_dns_purchase(user_id: int):
    cursor.execute("UPDATE users SET dns_purchases = dns_purchases + 1 WHERE user_id = ?", (user_id,))
    conn.commit()


def add_vpn_purchase(user_id: int):
    cursor.execute("UPDATE users SET vpn_purchases = vpn_purchases + 1 WHERE user_id = ?", (user_id,))
    conn.commit()


# Функции для работы с промокодами
def create_promocode(code: str, discount_type: str, discount_value: int, expires_days: int = 30, max_uses: int = 1):
    expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()
    cursor.execute("""
        INSERT OR REPLACE INTO promocodes (code, discount_type, discount_value, expires_at, max_uses)
        VALUES (?, ?, ?, ?, ?)
    """, (code, discount_type, discount_value, expires_at, max_uses))
    conn.commit()


def validate_promocode(user_id: int, code: str):
    cursor.execute("SELECT discount_type, discount_value, expires_at, max_uses, used_count FROM promocodes WHERE code = ?", (code,))
    promo = cursor.fetchone()
    if not promo:
        return None, "❌ Промокод не найден"
    
    discount_type, discount_value, expires_at, max_uses, used_count = promo
    
    if datetime.now() > datetime.fromisoformat(expires_at):
        return None, "❌ Срок действия промокода истек"
    
    if used_count >= max_uses:
        return None, "❌ Лимит использований промокода исчерпан"
    
    cursor.execute("SELECT 1 FROM user_promocodes WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        return None, "❌ Вы уже использовали этот промокод"
    
    return {"discount_type": discount_type, "discount_value": discount_value}, None


def apply_promocode(user_id: int, code: str):
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO user_promocodes (user_id, code, used_at) VALUES (?, ?, ?)", 
                   (user_id, code, datetime.now().isoformat()))
    conn.commit()


def calculate_price(original_price: int, discount_type: str, discount_value: int):
    if discount_type == "percent":
        return max(0, original_price - int(original_price * discount_value / 100))
    elif discount_type == "fixed":
        return max(0, original_price - discount_value)
    elif discount_type in ["free_dns", "free_vpn"]:
        return 0
    return original_price


# Главное меню
main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🛒 Купить DNS"), KeyboardButton("🔐 Купить VPN")],
    [KeyboardButton("🎟 Промокод"), KeyboardButton("📊 Статистика")],
    [KeyboardButton("🆘 Поддержка")]
], resize_keyboard=True)


# ========== /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    get_user(update.effective_user.id)
    await update.message.reply_text(
        "Привет! 👋\nЯ бот по продаже приватных DNS и VPN.\nВыберите действие:",
        reply_markup=main_keyboard
    )


# ========== СОЗДАНИЕ ПРОМОКОДА (только для админа) ==========
async def create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return
    
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "📝 Использование:\n"
            "/create_promo <код> <тип> <значение> <дней> [лимит]\n\n"
            "Типы:\n"
            "• percent - процентная скидка\n"
            "• fixed - фиксированная скидка (в рублях)\n"
            "• free_dns - бесплатный DNS\n"
            "• free_vpn - бесплатный VPN\n\n"
            "Примеры:\n"
            "/create_promo SUMMER10 percent 10 30 100\n"
            "/create_promo WELCOME fixed 50 7 50\n"
            "/create_promo FREEDNS free_dns 0 14 1"
        )
        return
    
    code = args[0].upper()
    discount_type = args[1]
    discount_value = int(args[2])
    expires_days = int(args[3])
    max_uses = int(args[4]) if len(args) > 4 else 1
    
    create_promocode(code, discount_type, discount_value, expires_days, max_uses)
    
    await update.message.reply_text(
        f"✅ Промокод создан!\n\n"
        f"📝 Код: {code}\n"
        f"🎁 Тип: {discount_type}\n"
        f"💰 Значение: {discount_value if discount_type in ['percent', 'fixed'] else 'бесплатно'}\n"
        f"⏰ Дней: {expires_days}\n"
        f"🔢 Лимит: {max_uses}"
    )


# ========== АКТИВАЦИЯ ПРОМОКОДА ==========
async def process_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, code: str):
    result, error = validate_promocode(user_id, code)
    
    if error:
        await update.message.reply_text(error, reply_markup=main_keyboard)
        context.user_data['awaiting_promo'] = False
        context.user_data['selected_product'] = None
        return False, None
    
    context.user_data['active_promo'] = {
        'code': code,
        'discount_type': result['discount_type'],
        'discount_value': result['discount_value']
    }
    
    product = context.user_data.get('selected_product')
    discount_type = result['discount_type']
    discount_value = result['discount_value']
    
    # Отправляем уведомление админу
    name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    
    if discount_type == "percent":
        discount_text = f"скидку {discount_value}%"
        admin_notify = f"🎟 АКТИВАЦИЯ ПРОМОКОДА\n\nКод: {code}\nПользователь: {name}\nID: {user_id}\nТип: процентная скидка {discount_value}%"
    elif discount_type == "fixed":
        discount_text = f"скидку {discount_value} руб."
        admin_notify = f"🎟 АКТИВАЦИЯ ПРОМОКОДА\n\nКод: {code}\nПользователь: {name}\nID: {user_id}\nТип: фиксированная скидка {discount_value} руб."
    elif discount_type == "free_dns":
        discount_text = "бесплатный DNS"
        admin_notify = f"🎟 АКТИВАЦИЯ ПРОМОКОДА\n\nКод: {code}\nПользователь: {name}\nID: {user_id}\nТип: БЕСПЛАТНЫЙ DNS"
    elif discount_type == "free_vpn":
        discount_text = "бесплатный VPN"
        admin_notify = f"🎟 АКТИВАЦИЯ ПРОМОКОДА\n\nКод: {code}\nПользователь: {name}\nID: {user_id}\nТип: БЕСПЛАТНЫЙ VPN"
    else:
        discount_text = "скидку"
        admin_notify = f"🎟 АКТИВАЦИЯ ПРОМОКОДА\n\nКод: {code}\nПользователь: {name}\nID: {user_id}"
    
    await context.bot.send_message(ADMIN_ID, admin_notify)
    
    if product == 'dns':
        original_price = DNS_PRICE
        final_price = calculate_price(original_price, discount_type, discount_value)
        
        if final_price == 0:
            await update.message.reply_text(
                f"🎉 ПОЗДРАВЛЯЮ!\n\n"
                f"✅ Промокод {code} успешно активирован!\n\n"
                f"🎁 Вы получили {discount_text}!\n"
                f"🌐 DNS теперь стоит 0 руб. (БЕСПЛАТНО!)\n\n"
                f"📸 Просто отправьте любой скриншот как подтверждение, и админ выдаст вам доступ."
            )
        else:
            saved = original_price - final_price
            await update.message.reply_text(
                f"🎉 ПОЗДРАВЛЯЮ!\n\n"
                f"✅ Промокод {code} успешно активирован!\n\n"
                f"🎁 Вы получили {discount_text}!\n"
                f"💰 Экономия: {saved} руб.\n"
                f"🌐 Цена DNS со скидкой: {final_price} руб. (было {original_price} руб.)\n\n"
                f"💳 Оплатите {final_price} руб. по реквизитам:\n{PAYMENT_DETAILS}\n\n"
                f"📸 После оплаты пришлите скриншот или фото чека."
            )
        
        context.user_data['discounted_price'] = final_price
        context.user_data['waiting'] = True
        return True, final_price
        
    elif product == 'vpn':
        original_price = VPN_PRICE
        final_price = calculate_price(original_price, discount_type, discount_value)
        
        if final_price == 0:
            await update.message.reply_text(
                f"🎉 ПОЗДРАВЛЯЮ!\n\n"
                f"✅ Промокод {code} успешно активирован!\n\n"
                f"🎁 Вы получили {discount_text}!\n"
                f"🔐 VPN теперь стоит 0 руб. (БЕСПЛАТНО!)\n\n"
                f"📸 Просто отправьте любой скриншот как подтверждение, и админ выдаст вам доступ."
            )
        else:
            saved = original_price - final_price
            await update.message.reply_text(
                f"🎉 ПОЗДРАВЛЯЮ!\n\n"
                f"✅ Промокод {code} успешно активирован!\n\n"
                f"🎁 Вы получили {discount_text}!\n"
                f"💰 Экономия: {saved} руб.\n"
                f"🔐 Цена VPN со скидкой: {final_price} руб. (было {original_price} руб.)\n\n"
                f"💳 Оплатите {final_price} руб. по реквизитам:\n{PAYMENT_DETAILS}\n\n"
                f"📸 После оплаты пришлите скриншот или фото чека."
            )
        
        context.user_data['discounted_price'] = final_price
        context.user_data['waiting'] = True
        return True, final_price
    
    return False, None


# ========== ТЕКСТОВЫЕ СООБЩЕНИЯ ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "/cancel":
        if context.user_data.get('awaiting_promo'):
            context.user_data['awaiting_promo'] = False
            context.user_data['selected_product'] = None
            await update.message.reply_text("❌ Активация промокода отменена.", reply_markup=main_keyboard)
        return

    if user_id == ADMIN_ID and 'admin_send_to' in context.user_data:
        await update.message.reply_text("❌ Отправьте файл как ДОКУМЕНТ, а не текстом.")
        return

    if text == "🛒 Купить DNS":
        context.user_data.clear()
        context.user_data['selected_product'] = 'dns'
        context.user_data['awaiting_promo'] = False
        context.user_data['waiting'] = False
        
        await update.message.reply_text(
            f"🌐 Покупка DNS\n\n"
            f"💰 Цена: {DNS_PRICE} руб.\n\n"
            f"🎟 Есть промокод? Нажмите кнопку Промокод и введите код.\n"
            f"💳 Если промокода нет, оплатите {DNS_PRICE} руб.:\n\n{PAYMENT_DETAILS}\n\n"
            f"📸 После оплаты пришлите сюда скриншот или фото чека."
        )

    elif text == "🔐 Купить VPN":
        context.user_data.clear()
        context.user_data['selected_product'] = 'vpn'
        context.user_data['awaiting_promo'] = False
        context.user_data['waiting'] = False
        
        await update.message.reply_text(
            f"🔒 Покупка VPN\n\n"
            f"💰 Цена: {VPN_PRICE} руб.\n\n"
            f"🎟 Есть промокод? Нажмите кнопку Промокод и введите код.\n"
            f"💳 Если промокода нет, оплатите {VPN_PRICE} руб.:\n\n{PAYMENT_DETAILS}\n\n"
            f"📸 После оплаты пришлите сюда скриншот или фото чека."
        )

    elif text == "🎟 Промокод":
        if context.user_data.get('selected_product') is None:
            await update.message.reply_text(
                "❌ Сначала выберите товар для покупки!\n\n"
                "Нажмите:\n"
                "• 🛒 Купить DNS\n"
                "• 🔐 Купить VPN",
                reply_markup=main_keyboard
            )
            return
        
        context.user_data['awaiting_promo'] = True
        await update.message.reply_text(
            "🎟 Активация промокода\n\n"
            "Введите код промокода.\n"
            "Пример: SUMMER10\n\n"
            "Чтобы отменить, отправьте /cancel"
        )
        return

    elif text == "📊 Статистика":
        context.user_data['awaiting_promo'] = False
        context.user_data['waiting'] = False
        user = get_user(user_id)
        await update.message.reply_text(
            f"📊 Ваша статистика:\n\n"
            f"🌐 Куплено DNS: {user['dns_purchases']} шт.\n"
            f"🔐 Куплено VPN: {user['vpn_purchases']} шт.\n"
            f"📦 Всего покупок: {user['dns_purchases'] + user['vpn_purchases']} шт."
        )

    elif text == "🆘 Поддержка":
        context.user_data['awaiting_promo'] = False
        context.user_data['waiting'] = False
        await update.message.reply_text(f"📞 Связь с поддержкой: {SUPPORT_USERNAME}")

    elif context.user_data.get('awaiting_promo'):
        promo_code = text.strip().upper()
        context.user_data['awaiting_promo'] = False
        success, _ = await process_promo_code(update, context, user_id, promo_code)
        if not success:
            context.user_data['selected_product'] = None

    elif context.user_data.get('waiting'):
        await update.message.reply_text("❌ Пожалуйста, пришлите фото или скриншот чека.")

    else:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_keyboard)


# ========== ФОТО (ЧЕКИ) ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID and 'admin_send_to' in context.user_data:
        await update.message.reply_text("❌ Отправьте файл как ДОКУМЕНТ, а не как фото!")
        return

    if not context.user_data.get('waiting'):
        await update.message.reply_text("Сейчас я не ожидаю чек.\nВыберите товар в меню.")
        return

    # Бесплатная выдача
    if context.user_data.get('discounted_price') == 0:
        context.user_data['waiting'] = False
        product = context.user_data.get('selected_product', 'неизвестный товар')
        product_name = "DNS" if product == 'dns' else "VPN"
        
        user = get_user(user_id)
        name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        info = (
            f"🎁 БЕСПЛАТНАЯ ВЫДАЧА!\n\n"
            f"📦 Товар: {product_name}\n"
            f"💰 Цена: 0 руб. (по промокоду)\n"
            f"👤 Покупатель: {name}\n"
            f"🆔 ID: {user_id}\n"
            f"📊 DNS: {user['dns_purchases']} | VPN: {user['vpn_purchases']}"
        )
        
        promo = context.user_data.get('active_promo')
        if promo:
            info += f"\n🎟 Промокод: {promo['code']}"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Выдать бесплатно", callback_data=f"free_{product}_{user_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
            ]
        ])
        
        context.user_data['pending_promo'] = promo
        await context.bot.send_message(ADMIN_ID, info, reply_markup=keyboard)
        await update.message.reply_text("✅ Запрос на бесплатный товар отправлен админу. Ожидайте.", reply_markup=main_keyboard)
        return

    context.user_data['waiting'] = False
    product = context.user_data.get('selected_product', 'неизвестный товар')
    product_name = "DNS" if product == 'dns' else "VPN"
    
    promo = context.user_data.get('active_promo')
    if promo:
        original_price = DNS_PRICE if product == 'dns' else VPN_PRICE
        final_price = calculate_price(original_price, promo['discount_type'], promo['discount_value'])
        discount_info = f"\n🎟 Промокод: {promo['code']} (скидка {promo['discount_value']}{'%' if promo['discount_type'] == 'percent' else ' руб.'})"
    else:
        final_price = DNS_PRICE if product == 'dns' else VPN_PRICE
        discount_info = ""

    user = get_user(user_id)
    name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name

    info = (
        f"🆕 НОВЫЙ ЧЕК!\n\n"
        f"📦 Товар: {product_name}\n"
        f"💰 Цена: {final_price} руб.{discount_info}\n"
        f"👤 Покупатель: {name}\n"
        f"🆔 ID: {user_id}\n"
        f"📊 DNS: {user['dns_purchases']} | VPN: {user['vpn_purchases']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok_{product}_{user_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
        ]
    ])

    context.user_data['pending_promo'] = promo
    await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=info, reply_markup=keyboard)
    await update.message.reply_text("✅ Чек отправлен на проверку. Ожидайте.", reply_markup=main_keyboard)


# ========== ДОКУМЕНТЫ ==========
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID and 'admin_send_to' in context.user_data:
        buyer_id = context.user_data['admin_send_to']
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name or "config.conf"

        try:
            await context.bot.send_document(
                chat_id=buyer_id,
                document=file_id,
                caption=f"✅ Ваша оплата подтверждена! Вот ваш файл: {file_name}\nСпасибо за покупку!",
                filename=file_name
            )
            await update.message.reply_text(f"✅ Файл отправлен покупателю (ID: {buyer_id})!")

            product = context.user_data.get('admin_product', 'dns')
            if product == 'dns':
                add_dns_purchase(buyer_id)
            else:
                add_vpn_purchase(buyer_id)

            promo = context.user_data.get('pending_promo')
            if promo:
                apply_promocode(buyer_id, promo['code'])

            del context.user_data['admin_send_to']
            del context.user_data['admin_product']
            if 'pending_promo' in context.user_data:
                del context.user_data['pending_promo']
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при отправке: {e}")
        return

    if not context.user_data.get('waiting'):
        await update.message.reply_text("Сейчас я не ожидаю чек.\nВыберите товар в меню.")
        return

    # Бесплатная выдача
    if context.user_data.get('discounted_price') == 0:
        context.user_data['waiting'] = False
        product = context.user_data.get('selected_product', 'неизвестный товар')
        product_name = "DNS" if product == 'dns' else "VPN"
        
        user = get_user(user_id)
        name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        info = (
            f"🎁 БЕСПЛАТНАЯ ВЫДАЧА!\n\n"
            f"📦 Товар: {product_name}\n"
            f"💰 Цена: 0 руб. (по промокоду)\n"
            f"👤 Покупатель: {name}\n"
            f"🆔 ID: {user_id}\n"
            f"📊 DNS: {user['dns_purchases']} | VPN: {user['vpn_purchases']}"
        )
        
        promo = context.user_data.get('active_promo')
        if promo:
            info += f"\n🎟 Промокод: {promo['code']}"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Выдать бесплатно", callback_data=f"free_{product}_{user_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
            ]
        ])
        
        context.user_data['pending_promo'] = promo
        await context.bot.send_message(ADMIN_ID, info, reply_markup=keyboard)
        await update.message.reply_text("✅ Запрос на бесплатный товар отправлен админу. Ожидайте.", reply_markup=main_keyboard)
        return

    context.user_data['waiting'] = False
    product = context.user_data.get('selected_product', 'неизвестный товар')
    product_name = "DNS" if product == 'dns' else "VPN"
    
    promo = context.user_data.get('active_promo')
    if promo:
        original_price = DNS_PRICE if product == 'dns' else VPN_PRICE
        final_price = calculate_price(original_price, promo['discount_type'], promo['discount_value'])
        discount_info = f"\n🎟 Промокод: {promo['code']} (скидка {promo['discount_value']}{'%' if promo['discount_type'] == 'percent' else ' руб.'})"
    else:
        final_price = DNS_PRICE if product == 'dns' else VPN_PRICE
        discount_info = ""

    user = get_user(user_id)
    name = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name

    info = (
        f"🆕 НОВЫЙ ЧЕК!\n\n"
        f"📦 Товар: {product_name}\n"
        f"💰 Цена: {final_price} руб.{discount_info}\n"
        f"👤 Покупатель: {name}\n"
        f"🆔 ID: {user_id}\n"
        f"📊 DNS: {user['dns_purchases']} | VPN: {user['vpn_purchases']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok_{product}_{user_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"no_{user_id}")
        ]
    ])

    context.user_data['pending_promo'] = promo
    await context.bot.send_document(ADMIN_ID, update.message.document.file_id, caption=info, reply_markup=keyboard)
    await update.message.reply_text("✅ Чек отправлен на проверку. Ожидайте.", reply_markup=main_keyboard)


# ========== ОБРАБОТКА КНОПОК АДМИНА ==========
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("ok_"):
        parts = data.split("_")
        product = parts[1]
        buyer_id = int(parts[2])
        product_name = "DNS" if product == 'dns' else "VPN"

        context.user_data['admin_send_to'] = buyer_id
        context.user_data['admin_product'] = product

        await query.edit_message_caption(caption=query.message.caption + f"\n\n⏳ Отправьте файл {product_name} для покупателя")
        await context.bot.send_message(
            ADMIN_ID,
            f"📂 Отправьте ФАЙЛ (как документ) для покупателя.\n"
            f"🆔 ID: {buyer_id}\n"
            f"📦 Товар: {product_name}"
        )

    elif data.startswith("free_"):
        parts = data.split("_")
        product = parts[1]
        buyer_id = int(parts[2])
        product_name = "DNS" if product == 'dns' else "VPN"

        promo = context.user_data.get('pending_promo')
        if promo:
            apply_promocode(buyer_id, promo['code'])

        context.user_data['admin_send_to'] = buyer_id
        context.user_data['admin_product'] = product

        await query.edit_message_text(text=query.message.text + f"\n\n⏳ Отправьте файл {product_name} для покупателя (бесплатная выдача)")
        await context.bot.send_message(
            ADMIN_ID,
            f"📂 Отправьте ФАЙЛ (как документ) для покупателя.\n"
            f"🆔 ID: {buyer_id}\n"
            f"📦 Товар: {product_name} (БЕСПЛАТНО ПО ПРОМОКОДУ)"
        )

    elif data.startswith("no_"):
        buyer_id = int(data[3:])
        try:
            await context.bot.send_message(buyer_id, "❌ Чек отклонён. Свяжитесь с поддержкой.")
        except:
            pass
        await query.edit_message_caption(caption=query.message.caption + "\n\n❌ ОТКЛОНЕНО")


# ========== ЗАПУСК ==========
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("create_promo", create_promo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()