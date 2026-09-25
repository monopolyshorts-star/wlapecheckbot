import sqlite3
import re
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any, Union, Dict
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

def ensure_schema():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manual_seasons (
            server_id TEXT PRIMARY KEY,
            season TEXT NOT NULL
        )
    """)
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(server_objects)").fetchall()}
    if "house_id" not in columns:
        cursor.execute("ALTER TABLE server_objects ADD COLUMN house_id INTEGER;")
    if "is_frozen" not in columns:
        cursor.execute("ALTER TABLE server_objects ADD COLUMN is_frozen INTEGER DEFAULT 0;")
    conn.commit()
    conn.close()

ensure_schema()

@app.get("/")
def read_root():
    return {"status": "online", "service": "Arizona Tracker API is running"}

class RealtorPayload(BaseModel):
    server_id: Any
    server_name: str
    season: Optional[str] = "Неизвестно"
    scan_ts: Optional[float] = None
    scan_type: Optional[str] = None
    items: Any = []

SERVER_RULES = {
    "01": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "02": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "03": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "04": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "05": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "06": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "07": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "08": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "09": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "10": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "11": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "12": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "13": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "14": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "15": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "16": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "17": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "18": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "19": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "20": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "21": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "22": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "23": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "24": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "25": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "26": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3},
    "27": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "28": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "29": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "30": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3},
    "31": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "32": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2},
    "33": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2},
}

def get_payday_slot_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)

def calculate_fall_time(server_id: str, obj_type: str, payday_val: int, insurance_status: str, update_time: datetime):
    try:
        sid = str(server_id).zfill(2)
        rules = SERVER_RULES.get(sid, SERVER_RULES["01"])
        is_biz = obj_type == "Бизнес"

        if is_biz:
            if insurance_status == "Не страх, Без занят":
                drop_per_hour, target_pd = 4, rules["b_un"]
            elif insurance_status == "Страх, Без занят":
                drop_per_hour, target_pd = 2, rules["b_un"]
            elif insurance_status == "Страх, Занят":
                drop_per_hour, target_pd = 1, rules["b_ins"]
            else:
                drop_per_hour, target_pd = 2, rules["b_un"]
        else:
            if insurance_status == "Не страх":
                drop_per_hour, target_pd = 2, rules["h_un"]
            else:
                drop_per_hour, target_pd = 1, rules["h_ins"]

        if payday_val <= target_pd:
            hours_to_wait = 1
        else:
            hours_to_wait = math.ceil((payday_val - target_pd) / drop_per_hour) + 1

        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        return (next_payday + timedelta(hours=hours_to_wait - 1)).isoformat()
    except Exception as e:
        print(f"[Calc Error] {e}", flush=True)
        return None

def classify_insurance(obj_type, previous_pd, current_pd, hours_diff):
    if not hours_diff or previous_pd is None:
        return "Неизвестно"
    drop = previous_pd - current_pd
    speed = drop / hours_diff
    if speed <= 0:
        return "Неизвестно"
    if obj_type == "Дом":
        return "Не страх" if speed >= 1.5 else "Страх"
    if speed >= 3.0:
        return "Не страх, Без занят"
    if speed >= 1.5:
        return "Страх, Без занят"
    return "Страх, Занят"

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    try:
        raw_items = payload.items
        if isinstance(raw_items, list):
            items_list = raw_items
        elif isinstance(raw_items, dict):
            items_list = list(raw_items.values()) if raw_items else []
        else:
            items_list = []

        server_id = str(payload.server_id)
        print(f"[API] Пакет от {payload.server_name} [{server_id}], тип: {payload.scan_type}, объектов: {len(items_list)}", flush=True)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        if payload.scan_ts:
            now = (datetime.fromtimestamp(payload.scan_ts, tz=timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        else:
            now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        now_str = now.strftime("%d.%m.%Y %H:%M:%S")

        row = cursor.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (server_id,)).fetchone()
        active_season = row[0] if row and row[0] else payload.season

        if not items_list:
            target_type = payload.scan_type or "Дом"
            cursor.execute("DELETE FROM server_objects WHERE server_id = ? AND obj_type = ?", (server_id, target_type))
            cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, 0, ?, 0, ?)", (server_id, f"Пусто_{target_type}", now_str))
            conn.commit()
            conn.close()
            return {"status": "success", "count": 0}

        grouped = {}
        for item in items_list:
            if isinstance(item, dict) and item.get("type"):
                grouped.setdefault(item["type"], []).append(item)

        for obj_type, type_items in grouped.items():
            histories = cursor.execute("""
                SELECT DISTINCT recorded_at FROM scan_history
                WHERE server_id = ? AND obj_type = ?
                ORDER BY id DESC LIMIT 20
            """, (server_id, obj_type)).fetchall()

            # Берём предыдущий час, а не повторный быстрый просмотр текущего часа.
            previous_time = None
            previous_dt = None
            for (time_str,) in histories:
                try:
                    dt = datetime.strptime(time_str, "%d.%m.%Y %H:%M:%S")
                    diff = (now.replace(minute=0, second=0, microsecond=0) - dt.replace(minute=0, second=0, microsecond=0)).total_seconds() / 3600
                    if diff >= 1:
                        previous_time, previous_dt = time_str, dt
                        break
                except ValueError:
                    continue

            previous = {}
            hours_diff = 0
            if previous_time and previous_dt:
                hours_diff = int(round((get_payday_slot_hour(now) - get_payday_slot_hour(previous_dt)).total_seconds() / 3600))
                cursor.execute("""
                    SELECT sh.slot, sh.payday, so.house_id, so.insurance_status
                    FROM scan_history sh
                    LEFT JOIN server_objects so
                      ON so.server_id = sh.server_id AND so.slot = sh.slot AND so.obj_type = sh.obj_type
                    WHERE sh.server_id = ? AND sh.obj_type = ? AND sh.recorded_at = ?
                """, (server_id, obj_type, previous_time))
                for slot, pd, hid, ins in cursor.fetchall():
                    previous[slot] = {"payday": pd, "house_id": hid, "insurance": ins or "Неизвестно"}

            # При новом полном скане раздела удаляем только исчезнувшие позиции.
            cursor.execute("SELECT MAX(last_updated) FROM server_objects WHERE server_id = ? AND obj_type = ?", (server_id, obj_type))
            last_update = cursor.fetchone()[0]
            paged = False
            if last_update:
                try:
                    paged = (now - datetime.strptime(last_update, "%d.%m.%Y %H:%M:%S")).total_seconds() < 60
                except ValueError:
                    pass
            if not paged:
                slots = [x.get("slot") for x in type_items]
                placeholders = ",".join("?" for _ in slots)
                cursor.execute(f"DELETE FROM server_objects WHERE server_id = ? AND obj_type = ? AND slot NOT IN ({placeholders})", [server_id, obj_type] + slots)

            for item in type_items:
                slot = item.get("slot")
                current_pd = item.get("payday")
                old = previous.get(slot)

                insurance = classify_insurance(
                    obj_type,
                    old["payday"] if old else None,
                    current_pd,
                    hours_diff,
                )

                # В текущем часовом повторном скане сохраняем уже определённый статус.
                if insurance == "Неизвестно":
                    old_db = cursor.execute("""
                        SELECT insurance_status FROM server_objects
                        WHERE server_id = ? AND slot = ? AND obj_type = ?
                    """, (server_id, slot, obj_type)).fetchone()
                    if old_db and old_db[0] and old_db[0] != "Неизвестно":
                        insurance = old_db[0]

                frozen = 1 if old and hours_diff >= 1 and current_pd == old["payday"] else 0
                if hours_diff == 0:
                    old_frozen = cursor.execute("""
                        SELECT is_frozen FROM server_objects
                        WHERE server_id = ? AND slot = ? AND obj_type = ?
                    """, (server_id, slot, obj_type)).fetchone()
                    frozen = old_frozen[0] if old_frozen else 0

                fall_time = calculate_fall_time(server_id, obj_type, current_pd, insurance, now)
                house_id = item.get("house_id")

                cursor.execute("""
                    INSERT INTO server_objects
                    (server_id, server_name, season, obj_type, slot, house_id, payday,
                     insurance_status, exact_fall_time, last_updated, is_frozen, is_h2, is_estate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                        server_name = excluded.server_name,
                        season = excluded.season,
                        house_id = excluded.house_id,
                        payday = excluded.payday,
                        insurance_status = excluded.insurance_status,
                        exact_fall_time = excluded.exact_fall_time,
                        last_updated = excluded.last_updated,
                        is_frozen = excluded.is_frozen
                """, (server_id, payload.server_name, active_season, obj_type, slot, house_id,
                      current_pd, insurance, fall_time, now_str, frozen))

                cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, ?, ?, ?, ?)", (server_id, slot, obj_type, current_pd, now_str))

        conn.commit()
        conn.close()
        return {"status": "success", "count": len(items_list)}
    except Exception as e:
        print(f"[API КРИТИЧЕСКАЯ ОШИБКА] {e}", flush=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
