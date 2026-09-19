import asyncio
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from database import DB_NAME, init_db

TOKEN = os.getenv("BOT_TOKEN", "REPLACE_WITH_NEW_TOKEN")
ADMIN_IDS = {1321937398}

init_db()
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

SEASONS_LIST = ["Автогонки", "Мотогонки", "По инфе", "По новому", "Скорострелы"]
SEASON_ICONS = {"Мотогонки": "🏍", "Ловля по инфе": "📱", "По инфе": "📱", "По новому": "✈️", "Автогонки": "🚗", "Скорострелы": "⌨️"}
SELECT_COLUMNS = "server_name, server_id, season, obj_type, slot, house_id, payday, insurance_status, exact_fall_time, is_frozen, is_h2, is_estate"
SERVERS_LIST = [("01", "Phoenix"), ("02", "Tucson"), ("03", "Scottdale"), ("04", "Chandler"), ("05", "Brainburg"), ("06", "Saint-Rose"), ("07", "Mesa"), ("08", "Red-Rock"), ("09", "Yuma"), ("10", "Surprise"), ("11", "Prescott"), ("12", "Glendale"), ("13", "Kingman"), ("14", "Winslow"), ("15", "Payson"), ("16", "Gilbert"), ("17", "Show-Low"), ("18", "Casa-Grande"), ("19", "Page"), ("20", "Sun-City"), ("21", "Queen-Creek"), ("22", "Sedona"), ("23", "Holiday"), ("24", "Wednesday"), ("25", "Yava"), ("26", "Faraway"), ("27", "Bumble-Bee"), ("28", "Christmas"), ("29", "Mirage"), ("30", "Love"), ("31", "Drake"), ("32", "Space"), ("33", "Home")]


def db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE IF NOT EXISTS manual_seasons (server_id TEXT PRIMARY KEY, season TEXT NOT NULL)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(server_objects)").fetchall()}
    if "house_id" not in columns:
        conn.execute("ALTER TABLE server_objects ADD COLUMN house_id INTEGER")
    conn.commit()
    return conn


def has_access(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    conn = db()
    row = conn.execute("SELECT expires_at FROM allowed_users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return False
    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except (ValueError, TypeError):
        return False


def keyboard(user_id: int):
    rows = [
        [KeyboardButton(text="⚠️ Ближайшие слёты"), KeyboardButton(text="📋 Все слёты")],
        [KeyboardButton(text="🌐 По серверу"), KeyboardButton(text="🏆 Сезоны")],
        [KeyboardButton(text="📍 Статус"), KeyboardButton(text="😴 Стоит проснуться")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text="⚙️ Консоль разработчика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def status_name(value):
    return {"Страх": "Застраховано", "Нестрах": "Не застраховано", "Страх, Занят": "Застраховано, есть занятость", "Страх, Незанят": "Застраховано, нет занятости", "Нестрах, Без занятости": "Не застраховано, без занятости", "Неизвестно": "Неизвестно"}.get(value or "Неизвестно", "Неизвестно")


def get_season_icon(season):
    s = (season or "").lower()
    if "мото" in s: return "🏍"
    if "инф" in s: return "📱"
    if "нов" in s: return "✈️"
    if "авто" in s or "гонк" in s: return "🚗"
    if "скорост" in s: return "⌨️"
    return "🌐"


def fetch_rows(where="", params=()):
    conn = db()
    query = f"SELECT {SELECT_COLUMNS} FROM server_objects"
    if where: query += " WHERE " + where
    query += " ORDER BY exact_fall_time ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def format_server(rows, server_id, server_name):
    conn = db()
    manual = conn.execute("SELECT season FROM manual_seasons WHERE server_id=?", (server_id,)).fetchone()
    conn.close()
    season = manual[0] if manual and manual[0] else (rows[0][2] if rows and rows[0][2] else "Неизвестно")
    result = [f"🌐 <b>Сервер {server_name.upper()} [{server_id}]</b>", f"└─ Сезон: {get_season_icon(season)} <b>{season}</b>"]
    for kind, icon, title in (("Дом", "🏠", "Дома"), ("Бизнес", "✨", "Бизнесы")):
        group = sorted([r for r in rows if r[3] == kind], key=lambda r: r[4])
        if not group: continue
        result.append(f"└─ {icon} <b>{title}:</b>")
        for r in group:
            _, _, _, _, slot, house_id, payday, state, fall, _, _, _ = r
            suffix = f" [ID: {house_id}]" if "скорострел" in season.lower() and house_id else ""
            fall_text = ""
            if fall:
                try: fall_text = f" | ⏰ {datetime.fromisoformat(fall):%H:%M}"
                except ValueError: pass
            result.append(f"   pos {slot}{suffix} (PayDay: {payday}) — {status_name(state)}{fall_text}")
    return "\n".join(result)


def format_falls(rows, title):
    if not rows: return f"{title}\n\n⚠️ Слётов не обнаружено."
    result = [title, ""]
    for r in sorted(rows, key=lambda x: x[8] or ""):
        name, sid, season, kind, slot, house_id, payday, state, fall, *_ = r
        if not fall: continue
        try: hour = datetime.fromisoformat(fall).strftime("%H:00")
        except ValueError: continue
        suffix = f" [ID: {house_id}]" if "скорострел" in (season or "").lower() and house_id else ""
        result.append(f"🕰️ <b>{hour}</b> — 🌐 <b>{name.upper()} {get_season_icon(season)}</b> — {('🏠' if kind == 'Дом' else '✨')} pos {slot}{suffix} ({payday} PD) — {status_name(state)}")
    return "\n".join(result) if len(result) > 2 else f"{title}\n\n⚠️ Слётов не обнаружено."


@dp.message(Command("start"))
async def start(message: types.Message):
    if not has_access(message.from_user.id):
        await message.answer("🔒 У вас нет доступа к боту.")
        return
    await message.answer("👋 <b>Arizona Tracker</b>", reply_markup=keyboard(message.from_user.id), parse_mode="HTML")


@dp.message(F.text.in_({"⚠️ Ближайшие слёты", "Ближайшие слёты"}))
async def nearest(message: types.Message):
    if not has_access(message.from_user.id): return
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    rows = fetch_rows("is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), (now + timedelta(hours=3)).isoformat()))
    await message.answer(format_falls(rows, "⚠️ <b>Ближайшие слёты (3 ПД)</b>"), parse_mode="HTML")


@dp.message(F.text.in_({"📋 Все слёты", "Все слёты"}))
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id): return
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    rows = fetch_rows("is_frozen=0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), (now + timedelta(hours=24)).isoformat()))
    await message.answer(format_falls(rows, "📋 <b>Все слёты за 24 часа</b>"), parse_mode="HTML")


@dp.message(F.text.in_({"🌐 По серверу", "По серверу"}))
async def servers_menu(message: types.Message):
    if not has_access(message.from_user.id): return
    buttons = [InlineKeyboardButton(text=f"{sid} {name}", callback_data=f"srv:{sid}") for sid, name in SERVERS_LIST]
    await message.answer("🌐 Выберите сервер:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)]))


@dp.callback_query(F.data.startswith("srv:"))
async def server_result(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True); return
    sid = callback.data.split(":", 1)[1]
    name = next((n for i, n in SERVERS_LIST if i == sid), sid)
    await callback.message.answer(format_server(fetch_rows("server_id=? AND is_frozen=0", (sid,)), sid, name), parse_mode="HTML")
    await callback.answer()


@dp.message(F.text.in_({"🏆 Сезоны", "Сезоны"}))
async def seasons(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    lines = ["🏆 <b>Сезоны по серверам</b>", ""]
    for sid, name in SERVERS_LIST:
        manual = conn.execute("SELECT season FROM manual_seasons WHERE server_id=?", (sid,)).fetchone()
        row = conn.execute("SELECT season FROM server_objects WHERE server_id=? ORDER BY last_updated DESC LIMIT 1", (sid,)).fetchone()
        season = (manual[0] if manual and manual[0] else (row[0] if row and row[0] else "Неизвестно"))
        lines.append(f"<code>[{sid}] {name:<12}</code> {get_season_icon(season)} {season}")
    conn.close()
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text.in_({"⚙️ Консоль разработчика", "Консоль разработчика"}))
async def dev_console(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    buttons = [InlineKeyboardButton(text=f"[{sid}] {name}", callback_data=f"devsrv:{sid}") for sid, name in SERVERS_LIST]
    await message.answer("⚙️ <b>Выберите сервер:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)]), parse_mode="HTML")


@dp.callback_query(F.data.startswith("devsrv:"))
async def dev_server(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    sid = callback.data.split(":", 1)[1]
    buttons = [[InlineKeyboardButton(text=s, callback_data=f"devset:{sid}:{s}")] for s in SEASONS_LIST]
    await callback.message.answer("Выберите сезон:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("devset:"))
async def dev_set(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    _, sid, season = callback.data.split(":", 2)
    conn = db()
    conn.execute("INSERT OR REPLACE INTO manual_seasons(server_id, season) VALUES(?, ?)", (sid, season))
    conn.commit(); conn.close()
    await callback.message.answer(f"✅ Сервер [{sid}]: {season}")
    await callback.answer()


@dp.message(F.text.in_({"📍 Статус", "Статус"}))
async def status(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    rows = conn.execute("SELECT server_name, MAX(last_updated) FROM server_objects GROUP BY server_id").fetchall()
    conn.close()
    rows.sort(key=lambda x: x[1] or "", reverse=True)
    text = "📍 <b>Последние сейвы:</b>\n\n" + "\n".join(f"<code>{n:<14} | {v}</code>" for n, v in rows)
    await message.answer(text if rows else "📍 Данных пока нет.", parse_mode="HTML")


@dp.message(F.text.in_({"😴 Стоит проснуться", "Стоит проснуться"}))
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id): return
    rows = fetch_rows("is_frozen=0")
    selected = [r for r in rows if r[3] == "Бизнес"]
    await message.answer(format_falls(selected, "😴 <b>Стоит проснуться</b>"), parse_mode="HTML")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
