import asyncio
import logging
import sqlite3
import secrets
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from database import DB_NAME, init_db

TOKEN = "8480773029:AAGO1I2nYPGc8agez0UJziFm1qx0YBEUGAo"
ADMIN_IDS = {1321937398} # Сюда ваш ID

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
    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except:
        return False

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
    }.get(status or "", "Застраховано") # По ТЗ неизвестно считаем застрахованным

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
            label = "Дома" if kind == "Дом" else "Бизнесы"
            result.append(f"      └─{icon} <b>{label}:</b>")
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
        await message.answer("🔒 У вас нет доступа к боту.")
        return
    await message.answer("👋 <b>Arizona Tracker</b>", reply_markup=main_keyboard(), parse_mode="HTML")

# Команда для генерации ключа админом: /genkey ДНИ (например /genkey 30)
@dp.message(Command("genkey"))
async def genkey(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        days = int(message.text.split()[1])
        key = secrets.token_hex(4).upper() # Генерирует короткий код типа A3F9B2C1
        exp = (datetime.now() + timedelta(days=days)).isoformat()
        conn = db()
        conn.execute("INSERT INTO access_keys(key, expires_at, created_at, created_by) VALUES (?, ?, ?, ?)", 
                     (key, exp, datetime.now().isoformat(), message.from_user.id))
        conn.commit(); conn.close()
        await message.answer(f"🔑 Сгенерирован ключ на <b>{days} дн.</b>:\n<code>{key}</code>\n\nИгрок может активировать его командой:\n<code>/key {key}</code>", parse_mode="HTML")
    except Exception as e:
        await message.answer("Использование: /genkey <количество_дней>")

# Команда для активации ключа игроком: /key КЛЮЧ
@dp.message(Command("key"))
async def activate_key(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /key <ваш_ключ>")
        return
    key = args[1].strip().upper()
    conn = db()
    row = conn.execute("SELECT expires_at, used FROM access_keys WHERE key = ?", (key,)).fetchone()
    if not row:
        conn.close()
        await message.answer("❌ Ключ не найден.")
        return
    exp, used = row
    if used:
        conn.close()
        await message.answer("❌ Этот ключ уже был использован.")
        return
    
    conn.execute("UPDATE access_keys SET used = 1, used_by = ? WHERE key = ?", (message.from_user.id, key))
    conn.execute("INSERT OR REPLACE INTO allowed_users(user_id, username, expires_at, added_at) VALUES (?, ?, ?, ?)", 
                 (message.from_user.id, message.from_user.username or "", exp, datetime.now().isoformat()))
    conn.commit(); conn.close()
    await message.answer(f"✅ Подписка успешно активирована до <b>{datetime.fromisoformat(exp).strftime('%d.%m.%Y %H:%M')}</b>!", parse_mode="HTML", reply_markup=main_keyboard())

@dp.message(Command("grant"))
async def grant(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        _, uid, days = message.text.split()
        exp = (datetime.now() + timedelta(days=int(days))).isoformat()
        conn = db()
        conn.execute("INSERT OR REPLACE INTO allowed_users VALUES (?, ?, ?, ?)", (int(uid), "", exp, datetime.now().isoformat()))
        conn.commit(); conn.close()
        await message.answer(f"✅ Доступ напрямую выдан ID {uid} до {exp}")
    except: await message.answer("Ошибка. Использование: /grant USER_ID ДНИ")

@dp.message(Command("revoke"))
async def revoke(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = message.text.split()[1]
        conn = db(); conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (int(uid),)); conn.commit(); conn.close()
        await message.answer(f"✅ Подписка у пользователя {uid} аннулирована.")
    except: await message.answer("Использование: /revoke USER_ID")

@dp.message(F.text == "⚠️ Ближайшие")
async def nearest(message: types.Message):
    if not has_access(message.from_user.id): return
    now, limit = datetime.now(), datetime.now() + timedelta(hours=3)
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat())).fetchall()
    conn.close()
    if not rows:
        await message.answer("⚠️ В ближайшие 3 часа слётов не обнаружено.", parse_mode="HTML")
        return
    await message.answer(format_falls(rows, "⚠️ <b>Ближайшие слёты (3 ПД)</b>"), parse_mode="HTML")

@dp.message(F.text == "📋 Все слёты")
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id): return
    now, limit = datetime.now(), datetime.now() + timedelta(hours=24)
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat())).fetchall()
    conn.close()
    if not rows:
        await message.answer("📋 На ближайшие 24 часа слётов не обнаружено.", parse_mode="HTML")
        return
    await message.answer(format_falls(rows, "📋 <b>Все слёты за 24 часа</b>"), parse_mode="HTML")

@dp.message(F.text == "🌐 По серверу")
async def servers_menu(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    servers = conn.execute("SELECT DISTINCT server_id, server_name FROM server_objects ORDER BY server_name").fetchall()
    conn.close()
    if not servers:
        await message.answer("⚠️ В базе пока нет данных по серверам.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{name} [{s_id}]", callback_data=f"srv:{s_id}")] for s_id, name in servers])
    await message.answer("🌐 Выберите сервер из списка:", reply_markup=kb)

@dp.callback_query(F.data.startswith("srv:"))
async def srv_res(cb: types.CallbackQuery):
    if not has_access(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    s_id = cb.data.split(":")[1]
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE server_id = ? AND is_frozen=0 ORDER BY exact_fall_time", (s_id,)).fetchall()
    conn.close()
    if not rows:
        await cb.message.answer("⚠️ На этом сервере нет активных слётов.")
        await cb.answer()
        return
    await cb.message.answer(format_falls(rows, f"🌐 <b>Слёты на сервере {rows[0][0].upper()}</b>"), parse_mode="HTML")
    await cb.answer()

@dp.message(F.text == "📍 Статус")
async def status(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    rows = conn.execute("SELECT server_name, MAX(last_updated) FROM server_objects GROUP BY server_id ORDER BY MAX(datetime(substr(last_updated,7,4)||'-'||substr(last_updated,4,2)||'-'||substr(last_updated,1,2)||' '||substr(last_updated,12))) DESC").fetchall()
    conn.close()
    if not rows:
        await message.answer("📍 Данные о сканировании серверов отсутствуют.")
        return
    lines = ["📍 <b>Последние сейвы по серверам:</b>", ""]
    for name, val in rows:
        lines.append(f"<code>{name:<14} | {val}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "😴 Стоит проснуться")
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE is_frozen=0").fetchall()
    conn.close()
    filt = []
    check = {}
    for r in rows:
        k = (r[7], r[1])
        check.setdefault(k, []).append(r)
    for k, v in check.items():
        if any(x[3] == "Бизнес" for x in v) or len(v) > 5: filt.extend(v)
    if not filt:
        await message.answer("😴 Массовых слётов или бизнесов пока не обнаружено.")
        return
    await message.answer(format_falls(filt, "😴 <b>Стоит проснуться (Массовые / Бизнесы)</b>"), parse_mode="HTML")

@dp.message(F.text == "🏆 Поиск по сезону")
async def season_menu(message: types.Message):
    if not has_access(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=s, callback_data=f`s:{s}`)] for s in SEASONS])
    await message.answer("🏆 Выберите сезон:", reply_markup=kb)

@dp.callback_query(F.data.startswith("s:"))
async def season_res(cb: types.CallbackQuery):
    if not has_access(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    s = cb.data.split(":")[1]
    conn = db()
    rows = conn.execute("SELECT server_name, server_id, season, obj_type, slot, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate FROM server_objects WHERE season=? AND is_frozen=0", (s,)).fetchall()
    conn.close()
    if not rows:
        await cb.message.answer(f"🏆 В сезоне '{s}' слётов не обнаружено.")
        await cb.answer()
        return
    await cb.message.answer(format_falls(rows, f"🏆 <b>Сезон: {s}</b>"), parse_mode="HTML")
    await cb.answer()

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
