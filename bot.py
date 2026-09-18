import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from database import DB_NAME

TOKEN = "8480773029:AAGO1I2nYPGc8agez0UJziFm1qx0YBEUGAo"
ADMIN_IDS = [123456789] # <-- Впишите сюда СВОЙ числовой Telegram ID (чтобы быть админом)

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# Инициализация таблиц для ключей и пользователей в базе данных
def init_auth_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TEXT
        )
    """)
    # Автоматически добавляем админа в разрешенные
    for admin_id in ADMIN_IDS:
        cursor.execute("INSERT OR IGNORE INTO allowed_users (user_id, added_at) VALUES (?, ?)", 
                       (admin_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

init_auth_db()

# Проверка доступа пользователя
def check_user_access(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

# Клавиатуры
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚠️ Ближайшие слёты"), KeyboardButton(text="📋 Все слёты")],
            [KeyboardButton(text="🗺️ По серверу"), KeyboardButton(text="🏆 Сезоны")]
        ],
        resize_keyboard=True
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not check_user_access(message.from_user.id):
        await message.answer("🔒 <b>У вас нет доступа к этому боту.</b>\nОбратитесь к администратору для получения ключа.", parse_mode="HTML")
        return

    await message.answer(
        "👋 <b>Добро пожаловать в Arizona Tracker!</b>\n\n"
        "Система активирована. Используйте кнопки меню ниже:",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="HTML"
    )

# Админ-команда: выдать доступ пользователю -> /grant ID
@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /grant <Telegram_ID>")
        return
    
    target_id = int(args[1])
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO allowed_users (user_id, added_at) VALUES (?, ?)", 
                   (target_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Пользователю с ID <code>{target_id}</code> успешно выдан доступ!", parse_mode="HTML")

# Кнопка: Ближайшие слёты
@dp.message(F.text == "⚠️ Ближайшие слёты")
async def cmd_nearest(message: types.Message):
    if not check_user_access(message.from_user.id):
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    now_iso = datetime.now().isoformat()
    limit_iso = (datetime.now() + timedelta(hours=3)).isoformat()
    
    cursor.execute("""
        SELECT server_name, server_id, obj_type, slot, payday, exact_fall_time, insurance_status 
        FROM server_objects 
        WHERE exact_fall_time >= ? AND exact_fall_time <= ?
        ORDER BY exact_fall_time ASC
    """, (now_iso, limit_iso))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.answer("⚠️ В ближайшие 3 часа слётов не обнаружено.")
        return

    houses_count = sum(1 for r in rows if r[2] == "Дом")
    biz_count = sum(1 for r in rows if r[2] == "Бизнес")

    text = f"⚠️ <b>Слёты в ближайшие 3 часа</b>\n"
    text += f"🏠x{houses_count}  🏢x{biz_count}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"

    grouped_by_time = {}
    for r in rows:
        fall_time = r[5]
        dt = datetime.fromisoformat(fall_time)
        hour_str = dt.strftime("%d.%m в %H:00")
        if hour_str not in grouped_by_time:
            grouped_by_time[hour_str] = {}
        
        s_name = f"{r[0]} [{r[1]}]"
        if s_name not in grouped_by_time[hour_str]:
            grouped_by_time[hour_str][s_name] = {"Дом": [], "Бизнес": []}
            
        ins_info = f" ({r[6]})" if r[6] else ""
        grouped_by_time[hour_str][s_name][r[2]].append(f"pos {r[3]} (PayDay: {r[4]}){ins_info}")

    for hour, servers in grouped_by_time.items():
        text += f"\n⚡ <b>Слёты в {hour}:</b>\n"
        for s_name, types_dict in servers.items():
            text += f"┣ 🌐 <b>Сервер {s_name}</b>\n"
            for obj_t, items in types_dict.items():
                if items:
                    icon = "🏠" if obj_t == "Дом" else "🏢"
                    text += f"┃   ┗ {icon} {obj_t}ы:\n"
                    for item in items:
                        text += f"┃      ┣—{item}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())

# Кнопка: По серверу
@dp.message(F.text == "🗺️ По серверу")
async def cmd_servers_menu(message: types.Message):
    if not check_user_access(message.from_user.id):
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT server_id, server_name FROM server_objects ORDER BY CAST(server_id AS INTEGER)")
    servers = cursor.fetchall()
    conn.close()

    if not servers:
        await message.answer("⚠️ В базе пока нет данных ни с одного сервера. Сначала просканируйте риелторку в игре!")
        return

    keyboard = []
    row = []
    for s_id, s_name in servers:
        row.append(InlineKeyboardButton(text=f"[{s_id}] {s_name}", callback_data=f"tr_srv_{s_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await message.answer("📋 <b>Выберите сервер из списка:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")

@dp.callback_query(F.data.startswith("tr_srv_"))
async def cb_tracker_server(callback: types.CallbackQuery):
    if not check_user_access(callback.from_user.id):
        await callback.answer("🔒 Нет доступа", show_alert=True)
        return

    server_id = callback.data.split("_")[2]
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT server_name, season, obj_type, slot, payday, insurance_status, exact_fall_time 
        FROM server_objects 
        WHERE server_id = ? 
        ORDER BY exact_fall_time ASC
    """, (server_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("⚠️ По этому серверу нет данных.")
        await callback.answer()
        return

    s_name = rows[0][0]
    season = rows[0][1]

    text = f"📍 <b>Сервер: {s_name} [{server_id}]</b>\n"
    text += f"🎣 Сезон: {season}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for _, _, obj_type, slot, payday, insurance, fall_time in rows:
        icon = "🏠" if obj_type == "Дом" else "🏢"
        ins = insurance if insurance else "Неизвестно"
        time_str = "Н/Д"
        if fall_time:
            time_str = datetime.fromisoformat(fall_time).strftime("%d.%m в %H:00")
            
        text += f"{icon} <b>Pos №{slot} ({obj_type})</b>\n"
        text += f"   • PayDay: <b>{payday}</b> | Статус: <code>{ins}</code>\n"
        text += f"   • Слет примерно: <b>{time_str}</b>\n\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

async def main():
    print("[BOT] Защищенный трекер-бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
