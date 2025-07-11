import logging
import sqlite3
from datetime import time, datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
SELECTING_TIME, SELECTING_TIMEZONE = range(2)
TIPS = [
    "выключайте свет и электроприборы когда они не используются",
    "Рациональной используй энергоресурсы",
    "Ппредпочитай упаковки многоразового использования",
    "Используй многоразовые пакеты",
    "Потребляй меньше продуктов животного происхождения",
    "Соритурй отходы"
]

# Инициализация базы данных
conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        hour INTEGER,
        minute INTEGER,
        timezone TEXT
    )
''')
conn.commit()

# ===== ОСНОВНЫЕ ФУНКЦИИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🍵 Привет. Я EcoHelper🕊️, твой персональный эко-помощник. "
        "Тут ты можешь узнать о глобальном потеплении и решении этой проблемы. "
        "Каждый день я буду присылать тебе простые советы. "
        "Готов сделать мир чуть зеленее? Нажми команду /vibrat"
    )

async def vibrat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Выбрать часовой пояс", callback_data="set_timezone")]
    ]
    await update.message.reply_text(
        "Сначала выбери свой часовой пояс:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_TIMEZONE

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    timezones = [
        
        ["Москва (UTC+3)", "Europe/Moscow"],
        ["Лондон (UTC+1)", "Europe/London"],
        ["Нью-Йорк (UTC-4)", "America/New_York"],
        ["Токио (UTC+9)", "Asia/Tokyo"]
    ]
    
    keyboard = []
    for tz in timezones:
        keyboard.append([InlineKeyboardButton(tz[0], callback_data=f"tz_{tz[1]}")])
    
    await query.edit_message_text(
        "Выбери свой часовой пояс:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_TIME

async def handle_timezone_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    timezone = query.data.split("_")[1]
    context.user_data['timezone'] = timezone
    
    keyboard = [
        [
            InlineKeyboardButton("08:00", callback_data="8_0"),
            InlineKeyboardButton("12:00", callback_data="12_0"),
            InlineKeyboardButton("18:00", callback_data="18_0"),
        ],
        [InlineKeyboardButton("Другое время", callback_data="custom")]
    ]
    await query.edit_message_text(
        "Теперь выбери время для напоминания:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_TIME

async def handle_time_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "custom":
        await query.edit_message_text("Введи время в формате ЧЧ:ММ (например, 09:30)")
        return SELECTING_TIME
    else:
        hour, minute = map(int, query.data.split("_"))
        timezone = context.user_data.get('timezone', 'Europe/Moscow')
        save_user_time(query.from_user.id, hour, minute, timezone)
        await query.edit_message_text(
            f"✅ Отлично! Буду присылать советы в {hour:02d}:{minute:02d} по часовому поясу {timezone}."
        )
        await schedule_daily_tip(context, query.from_user.id, hour, minute, timezone)
        return ConversationHandler.END

async def handle_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_str = update.message.text
        hour, minute = map(int, time_str.split(":"))
        if 0 <= hour < 24 and 0 <= minute < 60:
            timezone = context.user_data.get('timezone', 'Europe/Moscow')
            save_user_time(update.message.from_user.id, hour, minute, timezone)
            await update.message.reply_text(
                f"✅ Отлично! Буду присылать советы в {hour:02d}:{minute:02d} по часовому поясу {timezone}."
            )
            await schedule_daily_tip(context, update.message.from_user.id, hour, minute, timezone)
            return ConversationHandler.END
        else:
            await update.message.reply_text("⛔ Некорректное время. Попробуй снова.")
            return SELECTING_TIME
    except ValueError:
        await update.message.reply_text("⛔ Неверный формат. Введи время как ЧЧ:ММ (например, 09:30).")
        return SELECTING_TIME

def save_user_time(user_id: int, hour: int, minute: int, timezone: str):
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, hour, minute, timezone) VALUES (?, ?, ?, ?)",
        (user_id, hour, minute, timezone)
    )
    conn.commit()

async def schedule_daily_tip(context: ContextTypes.DEFAULT_TYPE, user_id: int, hour: int, minute: int, timezone: str):
    # Удаляем старые задачи
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()

    # Создаем время с учетом часового пояса
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    
    # Добавляем новую задачу
    context.job_queue.run_daily(
        send_daily_tip,
        time(hour, minute, tzinfo=tz),
        chat_id=user_id,
        name=str(user_id),
        data={"user_id": user_id}
    )

async def send_daily_tip(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    
    # Получаем информацию о пользователе из БД
    cursor.execute("SELECT hour, minute, timezone FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        hour, minute, timezone = row
        # Ротация советов по дням
        day_index = datetime.now(pytz.timezone(timezone)).timetuple().tm_yday
        tip = TIPS[day_index % len(TIPS)]
        
        try:
            await context.bot.send_message(chat_id=user_id, text=tip)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

# ===== ИНФОРМАЦИОННЫЕ КОМАНДЫ =====
async def global_warming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌍 Глобальное потепление — повышение средней температуры климатической системы Земли. "
        "Узнать больше: /what"
    )

async def what(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Последствия изменения климата:\n"
        "- Сильные засухи и нехватка воды\n"
        "- Повышение уровня моря\n"
        "- Катастрофические погодные явления\n"
        "- Сокращение биоразнообразия\n"
        "Причины: /why"
    )

async def why(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 Основные причины глобального потепления:\n"
        "1. Выбросы парниковых газов (CO2, метан)\n"
        "2. Сжигание ископаемого топлива\n"
        "3. Вырубка лесов\n"
        "4. Промышленные процессы\n"
        "5. Свалки мусора (выделяют метан)\n\n"
        "💡 Каждый может помочь: начните с малого - используйте /vibrat"
    )

# ===== ОСНОВНАЯ ФУНКЦИЯ =====
def main():
    # Создаем Application
    application = Application.builder().token("8002741992:AAEP7E6ltIpCa41A0toloxpr9POPVHUn77o").build()

    # Обработчик выбора времени и часового пояса
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('vibrat', vibrat)],
        states={
            SELECTING_TIMEZONE: [CallbackQueryHandler(set_timezone)],
            SELECTING_TIME: [
                CallbackQueryHandler(handle_timezone_selection, pattern="^tz_"),
                CallbackQueryHandler(handle_time_selection),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_time)
            ]
        },
        fallbacks=[]
    )

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("globalwarming", global_warming))
    application.add_handler(CommandHandler("what", what))
    application.add_handler(CommandHandler("why", why))
    application.add_handler(conv_handler)

    # Восстановление расписания из БД
    cursor.execute("SELECT user_id, hour, minute, timezone FROM users")
    for row in cursor.fetchall():
        user_id, hour, minute, timezone = row
        application.job_queue.run_once(
            lambda ctx, uid=user_id, h=hour, m=minute, tz=timezone: schedule_daily_tip(ctx, uid, h, m, tz),
            0
        )

    # Запуск бота
    application.run_polling()
    logger.info("Бот запущен и работает...")

if __name__ == '__main__':
    main()
