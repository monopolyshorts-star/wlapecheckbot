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
        raw_items = payload.items
        items_list = []
        if isinstance(raw_items, list):
            items_list = raw_items
        elif isinstance(raw_items, dict) and len(raw_items) > 0:
            items_list = list(raw_items.values())
        
        print(f"[API] Пакет от {payload.server_name} [{payload.server_id}], объектов: {len(items_list)}", flush=True)
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

        # Полная очистка при пустой риелторке
        if len(items_list) == 0:
            cursor.execute("DELETE FROM server_objects WHERE server_id = ?", (str(payload.server_id),))
            cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, 0, 'Пусто', 0, ?)", (str(payload.server_id), now_str))
            conn.commit()
            conn.close()
            print(f"[API УСПЕХ] Сервер {payload.server_name} полностью очищен (риелторка пуста)!", flush=True)
            return {"status": "success", "count": 0}

        # Группируем входящие объекты по типам (Дом / Бизнес)
        grouped_by_type = {}
        for item in items_list:
            if isinstance(item, dict):
                grouped_by_type.setdefault(item.get("type"), []).append(item)

        for obj_type, type_items in grouped_by_type.items():
            # Находим последние 10 записей истории сканов
            cursor.execute("""
                SELECT DISTINCT recorded_at FROM scan_history 
                WHERE server_id = ? AND obj_type = ? 
                ORDER BY id DESC LIMIT 10
            """, (str(payload.server_id), obj_type))
            history_rows = cursor.fetchall()

            # Ищем самый свежий скан, который сделан более 3 минут назад
            last_time_str = None
            last_dt = None
            for (h_time_str,) in history_rows:
                try:
                    h_dt = datetime.strptime(h_time_str, "%d.%m.%Y %H:%M:%S")
                    if (now - h_dt).total_seconds() >= 180:
                        last_time_str = h_time_str
                        last_dt = h_dt
                        break
                except:
                    continue

            last_scan_items = {}
            last_scan_by_pd = {}
            hours_diff = 0

            if last_time_str and last_dt:
                try:
                    diff_hours_calc = int(round((get_payday_slot_hour(now) - get_payday_slot_hour(last_dt)).total_seconds() / 3600.0))
                    hours_diff = diff_hours_calc if 1 <= diff_hours_calc <= 24 else 0

                    cursor.execute("""
                        SELECT sh.slot, sh.obj_type, sh.payday, so.house_id, so.insurance_status
                        FROM scan_history sh
                        LEFT JOIN server_objects so ON sh.server_id = so.server_id AND sh.slot = so.slot AND sh.obj_type = so.obj_type
                        WHERE sh.server_id = ? AND sh.obj_type = ? AND sh.recorded_at = ?
                    """, (str(payload.server_id), obj_type, last_time_str))
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
                    print(f"[History Load Error {obj_type}] {e}", flush=True)

            cursor.execute("""
                SELECT MAX(last_updated) FROM server_objects 
                WHERE server_id = ? AND obj_type = ?
            """, (str(payload.server_id), obj_type))
            last_up_row = cursor.fetchone()
            
            is_paged_scan = False
            if last_up_row and last_up_row[0]:
                try:
                    last_up_dt = datetime.strptime(last_up_row[0], "%d.%m.%Y %H:%M:%S")
                    if (now - last_up_dt).total_seconds() < 60:
                        is_paged_scan = True
                except Exception as e:
                    print(f"[Paged Check Error] {e}", flush=True)

            if not is_paged_scan:
                type_slots = [item.get("slot") for item in type_items]
                if type_slots:
                    placeholders = ",".join("?" for _ in type_slots)
                    cursor.execute(f"DELETE FROM server_objects WHERE server_id = ? AND obj_type = ? AND slot NOT IN ({placeholders})", [str(payload.server_id), obj_type] + type_slots)

            matched_prev_items = set()

            for item in type_items:
                i_slot = item.get("slot")
                i_hid = item.get("house_id")
                i_pd = item.get("payday")
                i_type = item.get("type")
                insurance = item.get("state")
                matched_prev = None

                # 1. Сначала ищем по house_id (самое точное совпадение)
                if i_hid and (i_type, "hid", i_hid) in last_scan_items:
                    matched_prev = last_scan_items[(i_type, "hid", i_hid)]
                
                # 2. Если внутри того же часа (hours_diff == 0) — ищем по той же позиции и payday
                elif hours_diff == 0 and (i_type, "slot", i_slot) in last_scan_items:
                    prev = last_scan_items[(i_type, "slot", i_slot)]
                    if prev["payday"] == i_pd: 
                        matched_prev = prev
                
                # 3. Если сменился час (hours_diff > 0) — ищем по позиции с проверкой слёта
                elif hours_diff > 0:
                    candidate = last_scan_items.get((i_type, "slot", i_slot))
                    if candidate and id(candidate) not in matched_prev_items:
                        drop = candidate["payday"] - i_pd
                        expected_rates = [1, 2] if i_type == "Дом" else [1, 2, 4]
                        if any(drop == rate * hours_diff for rate in expected_rates) or drop == 0: 
                            matched_prev = candidate
                    
                    # 4. Резервный поиск по PayDay (если позиция в списке сдвинулась)
                    if not matched_prev:
                        expected_rates = [1, 2] if i_type == "Дом" else [1, 2, 4]
                        for rate in expected_rates + [0]: 
                            old_needed_pd = i_pd + (rate * hours_diff)
                            candidates = last_scan_by_pd.get((i_type, old_needed_pd), [])
                            for cand in candidates:
                                if id(cand) not in matched_prev_items:
                                    matched_prev = cand
                                    break
                            if matched_prev: 
                                break

                # Рассчитываем и жестко наследуем статус страховки
                if matched_prev:
                    matched_prev_items.add(id(matched_prev))
                    old_insurance = matched_prev.get("insurance")
                    
                    if old_insurance and old_insurance != "Неизвестно":
                        insurance = old_insurance
                    elif hours_diff > 0:
                        pd_diff = matched_prev["payday"] - i_pd
                        drop_speed = pd_diff / hours_diff
                        if i_type == "Бизнес":
                            if drop_speed >= 3.0: 
                                insurance = "Нестрах, Без занятости"
                            elif drop_speed >= 1.5: 
                                insurance = "Страх, Без занят"
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
                    
                    # Если расчёт дал "Неизвестно", но раньше страховка была известна — возвращаем старую
                    if insurance == "Неизвестно" and old_insurance and old_insurance != "Неизвестно":
                        insurance = old_insurance
                else:
                    if not insurance: 
                        insurance = "Неизвестно"

                # Вычисляем заморозку
                is_frozen = 0
                prev_pd_val = matched_prev["payday"] if matched_prev else None
                if hours_diff >= 1 and prev_pd_val is not None:
                    if i_pd == prev_pd_val:
                        is_frozen = 1
                    else:
                        is_frozen = 0
                elif hours_diff == 0 and matched_prev is not None:
                    # Сохраняем состояние заморозки при повторных кликах в один час
                    cursor.execute("""
                        SELECT is_frozen FROM server_objects 
                        WHERE server_id = ? AND slot = ? AND obj_type = ?
                    """, (str(payload.server_id), i_slot, i_type))
                    row_fr = cursor.fetchone()
                    if row_fr:
                        is_frozen = row_fr[0]

                fall_time = calculate_fall_time(str(payload.server_id), i_type, i_pd, insurance, now)

                cursor.execute("""
                    INSERT INTO server_objects (
                        server_id, server_name, season, obj_type, slot, house_id, 
                        payday, insurance_status, exact_fall_time, last_updated, 
                        is_frozen, is_h2, is_estate
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                    ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                        payday = excluded.payday,
                        house_id = excluded.house_id,
                        insurance_status = excluded.insurance_status,
                        season = excluded.season,
                        exact_fall_time = excluded.exact_fall_time,
                        last_updated = excluded.last_updated,
                        is_frozen = excluded.is_frozen
                """, (str(payload.server_id), payload.server_name, active_season, i_type, i_slot, i_hid, i_pd, insurance, fall_time, now_str, is_frozen))

                cursor.execute("INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at) VALUES (?, ?, ?, ?, ?)", (str(payload.server_id), i_slot, i_type, i_pd, now_str))

        conn.commit()
        conn.close()
        print(f"[API УСПЕХ] Сервер {payload.server_name} обновлен!", flush=True)
        return {"status": "success", "count": len(items_list)}
    except Exception as e:
        print(f"[API КРИТИЧЕСКАЯ ОШИБКА] {e}", flush=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
