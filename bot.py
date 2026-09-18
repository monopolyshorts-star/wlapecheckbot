import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from database import DB_NAME

TOKEN = "ВАШ_ТОКЕН_БОТА_ОТ_BOTFATHER"

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# Главная клавиатура (меню снизу, как в трекерах)
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
    await message.answer(
        "👋 <b>Добро пожаловать в Arizona Tracker!</b>\n\n"
        "Используйте кнопки меню ниже для поиска актуальной информации о слётах:",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="HTML"
    )

# Кнопка: Ближайшие слёты (в ближайшие 3 часа)
@dp.message(F.text == "⚠️ Ближайшие слёты")
async def cmd_nearest(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Берем объекты, у которых время слета через 3 часа от текущего момента
    now_iso = datetime.now().isoformat()
    limit_iso = (datetime.now() + timedelta(hours=3)).isoformat()
    
    cursor.execute("""
        SELECT server_name, server_id, obj_type, slot, payday, exact_fall_time 
        FROM server_objects 
        WHERE exact_fall_time >= ? AND exact_fall_time <= ?
        ORDER BY exact_fall_time ASC
    """, (now_iso, limit_iso))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.answer("⚠️ В ближайшие 3 часа слётов не обнаружено.")
        return

    # Подсчет общего кол-ва домов и бизнесов
    houses_count = sum(1 for r in rows if r[2] == "Дом")
    biz_count = sum(1 for r in rows if r[2] == "Бизнес")

    text = f"⚠️ <b>Слёты в ближайшие 3 часа</b>\n"
    text += f"🏠x{houses_count}  🏢x{biz_count}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"

    # Группируем по времени слета (часу)
    grouped_by_time = {}
    for r in rows:
        fall_time = r[5]
        dt = datetime.fromisoformat(fall_time)
        hour_str = dt.strftime("%H:00")
        if hour_str not in grouped_by_time:
            grouped_by_time[hour_str] = {}
        
        s_name = f"{r[0]} [{r[1]}]"
        if s_name not in grouped_by_time[hour_str]:
            grouped_by_time[hour_str][s_name] = {"Дом": [], "Бизнес": []}
            
        grouped_by_time[hour_str][s_name][r[2]].append(f"pos {r[3]} (PayDay: {r[4]})")

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

# Кнопка: По серверу (выбор сервера кнопками)
@dp.message(F.text == "🗺️ По серверу")
async def cmd_servers_menu(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT server_id, server_name FROM server_objects ORDER BY CAST(server_id AS INTEGER)")
    servers = cursor.fetchall()
    conn.close()

    if not servers:
        await message.answer("⚠️ В базе пока нет данных ни с одного сервера.")
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
            time_str = datetime.fromisoformat(fall_time).strftime("%d.%m %H:00")
            
        text += f"{icon} <b>Pos №{slot} ({obj_type})</b>\n"
        text += f"   • PayDay: <b>{payday}</b> | Статус: <code>{ins}</code>\n"
        text += f"   • Слет: <b>{time_str}</b>\n\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

async def main():
    print("[BOT] Трекер-бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())