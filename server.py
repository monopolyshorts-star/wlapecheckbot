import sqlite3
import re
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any
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
    conn.commit()
    conn.close()

ensure_schema()

@app.get("/")
def read_root():
    return {"status": "online", "service": "Arizona Tracker API is running"}

class RealtorItem(BaseModel):
    slot: int
    house_id: Optional[int] = None
    payday: int
    type: str
    state: Optional[str] = None

class RealtorPayload(BaseModel):
    server_id: Any
    server_name: str
    season: Optional[str] = "Неизвестно"
    scan_ts: Optional[float] = None
    items: List[RealtorItem]

# ТАБЛИЦА ПРАВИЛ СЛЁТОВ (Thresholds)
SERVER_RULES = {
    "01": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # phoenix
    "02": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # tucson
    "03": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # scottdale
    "04": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # chandler
    "05": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # brainburg
    "06": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # saintrose
    "07": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # mesa
    "08": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # redrock
    "09": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # yuma
    "10": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # surprise
    "11": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # prescott
    "12": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # glendale
    "13": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # kingman
    "14": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # winslow
    "15": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2}, # payson
    "16": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # gilbert
    "17": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2}, # showlow
    "18": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # casagrande
    "19": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # page
    "20": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2}, # suncity
    "21": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # queencreek
    "22": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # sedona
    "23": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2}, # holiday
    "24": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # wednesday
    "25": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # yava
    "26": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3}, # faraway
    "27": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2}, # bumblebee
    "28": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # christmas
    "29": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3}, # mirage
    "30": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3}, # love
    "31": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2}, # drake
    "32": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2}, # space
    "33": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2}, # home
}

def get_payday_slot_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)

def calculate_fall_time(server_id: str, obj_type: str, payday_val: int, insurance_status: str, update_time: datetime):
    try:
        sid = str(server_id).zfill(2)
        rules = SERVER_RULES.get(sid, SERVER_RULES["01"])
        is_biz = (obj_type == "Бизнес")

        if is_biz:
            if insurance_status in ["Нестрах, Без занятости", "Нестрах", "Не страх, Без занят"]:
                drop_per_hour = 4
                target_pd = rules["b_un"]
            elif insurance_status in ["Страх, Занят", "Страх, есть занятость"]:
                drop_per_hour = 1
                target_pd = rules["b_ins"]
            else:
                drop_per_hour = 2
                target_pd = rules["b_un"]
        else:
            if insurance_status in ["Нестрах", "Не страх"]:
                drop_per_hour = 2
                target_pd = rules["h_un"]
            else:
                drop_per_hour = 1
                target_pd = rules["h_ins"]

        if payday_val <= target_pd:
            hours_to_wait = 1
        else:
            hours_to_wait = math.ceil((payday_val - target_pd) / drop_per_hour) + 1

        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        fall_time = next_payday + timedelta(hours=hours_to_wait - 1)
        return fall_time.isoformat()
    except Exception as e:
        print(f"[Calc Error] {e}", flush=True)
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    try:
        print(f"[API] Пакет от {payload.server_name} [{payload.server_id}], объектов: {len(payload.items)}", flush=True)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        if payload.scan_ts:
            now = (datetime.fromtimestamp(payload.scan_ts, tz=timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        else:
            now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
            
        now_str = now.strftime("%d.%m.%Y %H:%M:%S")

        cursor.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (str(payload.server_id),))
        m_season = cursor.fetchone()
        active_season = m_season[0] if m_season and m_season[0] else payload.season

        # --- ОБРАБОТКА ПУСТОЙ РИЕЛТОРКИ ---
        if len(payload.items) == 0:
            # Стираем все активные слёты для этого сервера
            cursor.execute("DELETE FROM server_objects WHERE server_id = ?", (str(payload.server_id),))
            # Сохраняем событие очистки в историю
            cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, 0, 'Пусто', 0, ?)", (str(payload.server_id), now_str))
            conn.commit()
            conn.close()
            print(f"[API УСПЕХ] Сервер {payload.server_name} полностью очищен (пустая риелторка)!", flush=True)
            return {"status": "success", "count": 0}
        # ----------------------------------

        cursor.execute("SELECT recorded_at FROM scan_history WHERE server_id = ? ORDER BY id DESC LIMIT 1", (str(payload.server_id),))
        last_global_row = cursor.fetchone()

        last_scan_items = {}
        last_scan_by_pd = {}
        hours_diff = 0

        if last_global_row and last_global_row[0]:
            try:
                last_time_str = last_global_row[0]
                last_dt = datetime.strptime(last_time_str, "%d.%m.%Y %H:%M:%S")
                diff_hours_calc = int(round((get_payday_slot_hour(now) - get_payday_slot_hour(last_dt)).total_seconds() / 3600.0))
                hours_diff = diff_hours_calc if 1 <= diff_hours_calc <= 24 else 0

                cursor.execute("""
                    SELECT sh.slot, sh.obj_type, sh.payday, so.house_id, so.insurance_status
                    FROM scan_history sh
                    LEFT JOIN server_objects so ON sh.server_id = so.server_id AND sh.slot = so.slot AND sh.obj_type = so.obj_type
                    WHERE sh.server_id = ? AND sh.recorded_at = ?
                """, (str(payload.server_id), last_time_str))
                for prev_slot_num, prev_type, prev_pd, prev_hid, prev_ins in cursor.fetchall():
                    item_dict = {"slot": prev_slot_num, "type": prev_type, "payday": prev_pd, "house_id": prev_hid, "insurance": prev_ins or "Неизвестно"}
                    if prev_hid: last_scan_items[(prev_type, "hid", prev_hid)] = item_dict
                    last_scan_items[(prev_type, "slot", prev_slot_num)] = item_dict
                    last_scan_by_pd.setdefault((prev_type, prev_pd), []).append(item_dict)
            except Exception as e:
                print(f"[History Load Error] {e}", flush=True)

        distinct_types = set(item.type for item in payload.items)
        for obj_type in distinct_types:
            # --- ЛОГИКА СКЛЕЙКИ СТРАНИЦ ---
            # Проверяем дату последнего обновления именно этого типа объектов на данном сервере
            cursor.execute("""
                SELECT MAX(last_updated) FROM server_objects 
                WHERE server_id = ? AND obj_type = ?
            """, (str(payload.server_id), obj_type))
            last_up_row = cursor.fetchone()
            
            is_paged_scan = False
            if last_up_row and last_up_row[0]:
                try:
                    last_up_dt = datetime.strptime(last_up_row[0], "%d.%m.%Y %H:%M:%S")
                    # Если прошло меньше 60 секунд, это продолжение сканирования (перелистывание страниц)
                    if (now - last_up_dt).total_seconds() < 60:
                        is_paged_scan = True
                except Exception as e:
                    print(f"[Paged Check Error] {e}", flush=True)

            # Если это новый сеанс (не многостраничный), удаляем старые записи
            if not is_paged_scan:
                type_slots = [item.slot for item in payload.items if item.type == obj_type]
                if type_slots:
                    placeholders = ",".join("?" for _ in type_slots)
                    cursor.execute(f"DELETE FROM server_objects WHERE server_id = ? AND obj_type = ? AND slot NOT IN ({placeholders})", [str(payload.server_id), obj_type] + type_slots)
            # ------------------------------

        matched_prev_items = set()

        for item in payload.items:
            insurance = item.state
            matched_prev = None

            if item.house_id and (item.type, "hid", item.house_id) in last_scan_items:
                matched_prev = last_scan_items[(item.type, "hid", item.house_id)]
            elif hours_diff == 0 and (item.type, "slot", item.slot) in last_scan_items:
                prev = last_scan_items[(item.type, "slot", item.slot)]
                if prev["payday"] == item.payday: matched_prev = prev
            elif hours_diff > 0:
                candidate = last_scan_items.get((item.type, "slot", item.slot))
                if candidate and id(candidate) not in matched_prev_items:
                    drop = candidate["payday"] - item.payday
                    expected_rates = [1, 2] if item.type == "Дом" else [1, 2, 4]
                    if any(drop == rate * hours_diff for rate in expected_rates): matched_prev = candidate
                if not matched_prev:
                    expected_rates = [1, 2] if item.type == "Дом" else [1, 2, 4]
                    for rate in expected_rates:
                        old_needed_pd = item.payday + (rate * hours_diff)
                        candidates = last_scan_by_pd.get((item.type, old_needed_pd), [])
                        for cand in candidates:
                            if id(cand) not in matched_prev_items:
                                matched_prev = cand
                                break
                        if matched_prev: break

            if matched_prev:
                matched_prev_items.add(id(matched_prev))
                if matched_prev.get("insurance") and matched_prev["insurance"] != "Неизвестно":
                    insurance = matched_prev["insurance"]
                elif hours_diff > 0:
                    pd_diff = matched_prev["payday"] - item.payday
                    drop_speed = pd_diff / hours_diff
                    if item.type == "Бизнес":
                        if drop_speed >= 3.0: insurance = "Нестрах, Без занятости"
                        elif drop_speed >= 1.5: insurance = "Страх, Незанят"
                        elif drop_speed >= 0.8: insurance = "Страх, Занят"
                        else: insurance = "Неизвестно"
                    else:
                        if drop_speed >= 1.5: insurance = "Нестрах"
                        elif drop_speed >= 0.8: insurance = "Страх"
                        else: insurance = "Неизвестно"
            else:
                if not insurance: insurance = "Неизвестно"

            fall_time = calculate_fall_time(str(payload.server_id), item.type, item.payday, insurance, now)

            cursor.execute("""
                INSERT INTO server_objects (
                    server_id, server_name, season, obj_type, slot, house_id, 
                    payday, insurance_status, exact_fall_time, last_updated, 
                    is_frozen, is_h2, is_estate
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
                ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                    payday = excluded.payday,
                    house_id = COALESCE(excluded.house_id, server_objects.house_id),
                    insurance_status = excluded.insurance_status,
                    season = excluded.season,
                    exact_fall_time = excluded.exact_fall_time,
                    last_updated = excluded.last_updated
            """, (str(payload.server_id), payload.server_name, active_season, item.type, item.slot, item.house_id, item.payday, insurance, fall_time, now_str))

            cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, ?, ?, ?, ?)", (str(payload.server_id), item.slot, item.type, item.payday, now_str))

        conn.commit()
        conn.close()
        print(f"[API УСПЕХ] Сервер {payload.server_name} обновлен!", flush=True)
        return {"status": "success", "count": len(payload.items)}
    except Exception as e:
        print(f"[API КРИТИЧЕСКАЯ ОШИБКА] {e}", flush=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
