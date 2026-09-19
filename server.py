import sqlite3
import re
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

def get_payday_slot_hour(dt: datetime) -> datetime:
    """
    Определяет часовой интервал PayDay:
    17:55 - 17:59 -> относится к часу 17:00.
    18:00 - 18:54 -> относится к 18:00.
    """
    return dt.replace(minute=0, second=0, microsecond=0)

def calculate_fall_time(obj_type: str, payday_val: int, insurance_status: str, update_time: datetime):
    try:
        is_biz = (obj_type == "Бизнес")
        
        if is_biz:
            if insurance_status in ["Нестрах, Без занятости", "Нестрах"]:
                drop_per_hour = 4
                target_pd = 4
            elif insurance_status == "Страх, Занят":
                drop_per_hour = 1
                target_pd = 2
            else:
                drop_per_hour = 2
                target_pd = 2
        else:
            if insurance_status and "Нестрах" in str(insurance_status):
                drop_per_hour = 2
                target_pd = 3
            else:
                drop_per_hour = 1
                target_pd = 2

        paydays_left = max(0, payday_val - target_pd)
        hours_to_add = paydays_left / drop_per_hour

        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        fall_time = next_payday + timedelta(hours=hours_to_add)
        return fall_time.isoformat()
    except Exception as e:
        print(f"[Calc Error] {e}", flush=True)
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    try:
        print(f"[API] Принят пакет: сервер {payload.server_name} [{payload.server_id}], объектов: {len(payload.items)}", flush=True)
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

        # Получаем данные последнего предыдущего скана для этого сервера
        cursor.execute("""
            SELECT recorded_at FROM scan_history 
            WHERE server_id = ?
            ORDER BY id DESC LIMIT 1
        """, (str(payload.server_id),))
        last_global_row = cursor.fetchone()

        last_scan_items = {}
        last_scan_by_pd = {}
        hours_diff = 0

        if last_global_row and last_global_row[0]:
            try:
                last_time_str = last_global_row[0]
                last_dt = datetime.strptime(last_time_str, "%d.%m.%Y %H:%M:%S")
                
                current_slot = get_payday_slot_hour(now)
                prev_slot = get_payday_slot_hour(last_dt)
                
                diff_hours_calc = int(round((current_slot - prev_slot).total_seconds() / 3600.0))
                
                if 1 <= diff_hours_calc <= 24:
                    hours_diff = diff_hours_calc
                else:
                    hours_diff = 0

                cursor.execute("""
                    SELECT sh.slot, sh.obj_type, sh.payday, so.house_id, so.insurance_status
                    FROM scan_history sh
                    LEFT JOIN server_objects so ON sh.server_id = so.server_id AND sh.slot = so.slot AND sh.obj_type = so.obj_type
                    WHERE sh.server_id = ? AND sh.recorded_at = ?
                """, (str(payload.server_id), last_time_str))
                for prev_slot_num, prev_type, prev_pd, prev_hid, prev_ins in cursor.fetchall():
                    item_dict = {
                        "slot": prev_slot_num,
                        "type": prev_type,
                        "payday": prev_pd,
                        "house_id": prev_hid,
                        "insurance": prev_ins or "Неизвестно"
                    }
                    if prev_hid:
                        last_scan_items[(prev_type, "hid", prev_hid)] = item_dict
                    last_scan_items[(prev_type, "slot", prev_slot_num)] = item_dict
                    last_scan_by_pd.setdefault((prev_type, prev_pd), []).append(item_dict)

            except Exception as e:
                print(f"[History Load Error] {e}", flush=True)

        # -------------------------------------------------------------
        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ:
        # Удаляем "хвосты" - старые позиции, которые слетели или отсутствуют в новом пакете
        # -------------------------------------------------------------
        distinct_types = set(item.type for item in payload.items)
        for obj_type in distinct_types:
            type_slots = [item.slot for item in payload.items if item.type == obj_type]
            if type_slots:
                placeholders = ",".join("?" for _ in type_slots)
                cursor.execute(f"""
                    DELETE FROM server_objects 
                    WHERE server_id = ? AND obj_type = ? AND slot NOT IN ({placeholders})
                """, [str(payload.server_id), obj_type] + type_slots)

        matched_prev_items = set()

        for item in payload.items:
            insurance = item.state
            matched_prev = None

            # 1. Точное сопоставление по house_id (скорострелы)
            if item.house_id and (item.type, "hid", item.house_id) in last_scan_items:
                matched_prev = last_scan_items[(item.type, "hid", item.house_id)]

            # 2. Тот же час (повторный скан без смены PayDay)
            elif hours_diff == 0 and (item.type, "slot", item.slot) in last_scan_items:
                prev = last_scan_items[(item.type, "slot", item.slot)]
                if prev["payday"] == item.payday:
                    matched_prev = prev

            # 3. Следующий PayDay (прошел 1 или несколько часов)
            elif hours_diff > 0:
                # А) По тому же слоту
                candidate = last_scan_items.get((item.type, "slot", item.slot))
                if candidate and id(candidate) not in matched_prev_items:
                    drop = candidate["payday"] - item.payday
                    expected_rates = [1, 2] if item.type == "Дом" else [1, 2, 4]
                    if any(drop == rate * hours_diff for rate in expected_rates):
                        matched_prev = candidate

                # Б) Со смещением позиций
                if not matched_prev:
                    expected_rates = [1, 2] if item.type == "Дом" else [1, 2, 4]
                    for rate in expected_rates:
                        old_needed_pd = item.payday + (rate * hours_diff)
                        candidates = last_scan_by_pd.get((item.type, old_needed_pd), [])
                        for cand in candidates:
                            if id(cand) not in matched_prev_items:
                                matched_prev = cand
                                break
                        if matched_prev:
                            break

            # Определение статуса страховки
            if matched_prev:
                matched_prev_items.add(id(matched_prev))
                
                if matched_prev.get("insurance") and matched_prev["insurance"] != "Неизвестно":
                    insurance = matched_prev["insurance"]
                elif hours_diff > 0:
                    pd_diff = matched_prev["payday"] - item.payday
                    drop_speed = pd_diff / hours_diff
                    
                    if item.type == "Бизнес":
                        if drop_speed >= 3.0:
                            insurance = "Нестрах, Без занятости"
                        elif drop_speed >= 1.5:
                            insurance = "Страх, Незанят"
                        elif drop_speed >= 0.8:
                            insurance = "Страх, Занят"
                        else:
                            insurance = "Неизвестно"
                    else:
                        if drop_speed >= 1.5:
                            insurance = "Нестрах"
                        elif drop_speed >= 0.8:
                            insurance = "Страх"
                        else:
                            insurance = "Неизвестно"
            else:
                if not insurance:
                    insurance = "Неизвестно"

            fall_time = calculate_fall_time(item.type, item.payday, insurance, now)

            # Сохраняем актуальный объект
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
                    last_updated = excluded.last_updated,
                    is_frozen = excluded.is_frozen,
                    is_estate = excluded.is_estate
            """, (
                str(payload.server_id), payload.server_name, active_season, 
                item.type, item.slot, item.house_id, item.payday, insurance, 
                fall_time, now_str
            ))

            # Записываем в историю
            cursor.execute("""
                INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (str(payload.server_id), item.slot, item.type, item.payday, now_str))

        conn.commit()
        conn.close()
        print(f"[API УСПЕХ] Сервер {payload.server_name} обновлен ({len(payload.items)} об.)", flush=True)
        return {"status": "success", "count": len(payload.items)}
    except Exception as e:
        print(f"[API КРИТИЧЕСКАЯ ОШИБКА] {e}", flush=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
