import asyncio
import logging
import sqlite3
import secrets
import os
from datetime import datetime, timedelta
from html import escape
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from database import DB_NAME, init_db

TOKEN = "ВАШ_ТОКЕН"
ADMIN_IDS = {123456789} # Сюда ваш ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

SEASON_ICONS = {
    "Мотогонки": "🏍",
    "Ловля по инфе": "📱",
    "По инфе": "📱",
    "По новому": "✈️",
    "Автогонки": "🚗",
    "Скорострелы": "⌨️",
}

SEASONS = ["Скорострелы", "Ловля по инфе", "Автогонки", "По новому", "Мотогонки"]

def db():
    return sqlite3.connect(DB_NAME)

def has_access(user_id: int) -> bool:
    if user_id in ADMIN_IDS: return True
    conn = db()
    row = conn.execute("SELECT expires_at FROM allowed_users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row: return False
    return datetime.fromisoformat(row[0]) > datetime.now()

def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⚠️ Ближайшие"), KeyboardButton(text="📋 Все слёты")],
        [KeyboardButton(text="🌐 По серверу"), KeyboardButton(text="🏆 Поиск по сезону")],
        [KeyboardButton(text="📍 Статус"), KeyboardButton(text="😴 Стоит проснуться")],
    ], resize_keyboard=True)

def status_text(status):
    return {
        "Страх": "Застраховано",
        "Нестрах": "Не застраховано",
        "Страх, Занят": "Застраховано, есть занятость",
        "Страх, Незанят": "Застраховано, нет занятости",
        "Нестрах, Незанят": "Не застраховано, нет занятости",
    }.get(status or "", "Неизвестно")

def format_falls(rows, title):
    if not rows: return f"{title}\n\nСлётов не обнаружено."
    result = [title, ""]
    grouped = {}
    for row in rows:
        server_name, server_id, season, obj_type, slot, payday, status, fall, frozen, h2, estate = row
        dt = datetime.fromisoformat(fall)
        hour = dt.strftime("%H:00")
        key = (hour, server_id, server_name, season)
        grouped.setdefault(key, {"Дом": [], "Бизнес": []})[obj_type].append(row)

    for (hour, server_id, server_name, season), types in sorted(grouped.items()):
        result.append(f"🕰️ <b>Слёты в {hour}:</b> 🕰️")
        result.append(f"   └─🌐 <b>Сервер {server_name.upper()} {SEASON_ICONS.get(season, '🌐')}</b>")
        for kind, items in types.items():
            if not items: continue
            icon = "🏠" if kind == "Дом" else "✨"
            result.append(f"      └─{icon} <b>{kind}а:</b>")
            for r in items:
                _, _, _, _, slot, payday, status, _, _, h2, estate = r
                info = status_text(status)
                if estate: info += " (🔒 С поместьем)"
                if h2: info += " (🔒 Х2 ДОМ!!!)"
                result.append(f"         └─pos {slot} (PayDay: {payday}) - {info}")
        result.append("")
    return "\n".join(result)

@dp.message(Command("start"))
async def start(message: types.Message):
    if not has_access(message.from_user.id):
        await message.answer("🔒 Нет доступа.")
        return
    await message.answer("👋 <b>Arizona Tracker</b>", reply_markup=main_keyboard(), parse_mode="HTML")

@dp.message(Command("grant"))
async def grant(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, uid, days = message.text.split()
        exp = (datetime.now() + timedelta(days=int(days))).isoformat()
        conn = db()
        conn.execute("INSERT OR REPLACE INTO allowed_users VALUES (?, ?, ?, ?)", (int(uid), "", exp, datetime.now().isoformat()))
        conn.commit(); conn.close()
        await message.answer(f"✅ Доступ выдан до {exp}")
    except: await message.answer("Ошибка. Юзай: /grant ID ДНИ")

@dp.message(Command("revoke"))
async def revoke(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = message.text.split()[1]
        conn = db(); conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (int(uid),)); conn.commit(); conn.close()
        await message.answer("✅ Доступ отозван.")
    except: pass

@dp.message(F.text == "⚠️ Ближайшие")
async def nearest(message: types.Message):
    if not has_access(message.from_user.id): return
    now, limit = datetime.now(), datetime.now() + timedelta(hours=3)
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat())).fetchall()
    conn.close()
    await message.answer(format_falls(rows, "⚠️ <b>Ближайшие слёты</b>"), parse_mode="HTML")

@dp.message(F.text == "📋 Все слёты")
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id): return
    now, limit = datetime.now(), datetime.now() + timedelta(hours=24)
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat())).fetchall()
    conn.close()
    await message.answer(format_falls(rows, "📋 <b>Слёты за 24 часа</b>"), parse_mode="HTML")

@dp.message(F.text == "📍 Статус")
async def status(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    rows = conn.execute("SELECT server_name, last_updated FROM server_objects GROUP BY server_id ORDER BY last_updated DESC").fetchall()
    conn.close()
    res = "📍 <b>Последние сейвы:</b>\n" + "\n".join([f"<code>{r[0]:<12} | {r[1]}</code>" for r in rows])
    await message.answer(res, parse_mode="HTML")

@dp.message(F.text == "😴 Стоит проснуться")
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0").fetchall()
    conn.close()
    filt = []
    # Группировка для проверки масс-слета
    check = {}
    for r in rows:
        k = (r[7], r[1])
        check.setdefault(k, []).append(r)
    for k, v in check.items():
        if any(x[3] == "Бизнес" for x in v) or len(v) > 5: filt.extend(v)
    await message.answer(format_falls(filt, "😴 <b>Стоит проснуться</b>"), parse_mode="HTML")

@dp.message(F.text == "🏆 Поиск по сезону")
async def season_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s, callback_data=f"s:{s}")] for s in SEASONS])
    await message.answer("🏆 Выберите сезон:", reply_markup=kb)

@dp.callback_query(F.data.startswith("s:"))
async def season_res(cb: types.CallbackQuery):
    s = cb.data.split(":")[1]
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE season=? AND is_frozen=0", (s,)).fetchall()
    conn.close()
    await cb.message.answer(format_falls(rows, f"🏆 <b>Сезон: {s}</b>"), parse_mode="HTML")
    await cb.answer()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
