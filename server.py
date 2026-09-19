import sqlite3
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any
from fastapi import FastAPI
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

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

def calculate_fall_time(obj_type: str, payday_val: int, insurance_status: str, update_time: datetime):
    try:
        is_biz = (obj_type == "Бизнес")
        is_insured = True
        
        if is_biz:
            if insurance_status in ["Нестрах, Без занятости", "Нестрах"]:
                is_insured = False
            drop_per_hour = 4 if insurance_status in ["Нестрах, Без занятости", "Нестрах"] else (1 if insurance_status == "Страх, Занят" else 2)
            target_pd = 4 if not is_insured else 2
        else:
            if insurance_status and "Нестрах" in str(insurance_status):
                is_insured = False
            drop_per_hour = 1 if is_insured else 2
            target_pd = 2 if is_insured else 3

        paydays_left = max(0, payday_val - target_pd)
        hours_to_add = paydays_left / drop_per_hour

        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        fall_time = next_payday + timedelta(hours=hours_to_add)
        return fall_time.isoformat()
    except Exception as e:
        print(f"[Calc Error] {e}")
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Автоматическое добавление колонки house_id, если её нет в БД
        try:
            cursor.execute("ALTER TABLE server_objects ADD COLUMN house_id INTEGER;")
            conn.commit()
        except:
            pass

        if payload.scan_ts:
            now = (datetime.fromtimestamp(payload.scan_ts, tz=timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        else:
            now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
            
        now_str = now.strftime("%d.%m.%Y %H:%M:%S")

        cursor.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (str(payload.server_id),))
        m_season = cursor.fetchone()
        active_season = m_season[0] if m_season and m_season[0] else payload.season

        for item in payload.items:
            cursor.execute("""
                SELECT payday, recorded_at FROM scan_history
                WHERE server_id = ? AND slot = ? AND obj_type = ?
                ORDER BY id DESC LIMIT 1
            """, (str(payload.server_id), item.slot, item.type))
            old_rec = cursor.fetchone()

            insurance = item.state

            if not old_rec:
                insurance = "Неизвестно"
            elif not insurance:
                old_pd, old_time_str = old_rec
                try:
                    old_time = datetime.strptime(old_time_str, "%d.%m.%Y %H:%M:%S")
                    hours_diff = max(1, int((now - old_time).total_seconds() / 3600))
                    pd_diff = old_pd - item.payday
                    drop_speed = pd_diff / hours_diff
                    
                    if item.type == "Бизнес":
                        if drop_speed >= 3.5:
                            insurance = "Нестрах, Без занятости"
                        elif drop_speed >= 1.8 and drop_speed <= 2.2:
                            insurance = "Страх, Незанят"
                        elif drop_speed >= 0.8 and drop_speed <= 1.2:
                            insurance = "Страх, Занят"
                        else:
                            insurance = "Неизвестно"
                    else:
                        if drop_speed >= 1.5:
                            insurance = "Нестрах"
                        elif drop_speed > 0:
                            insurance = "Страх"
                        else:
                            insurance = "Неизвестно"
                except:
                    insurance = "Неизвестно"

            fall_time = calculate_fall_time(item.type, item.payday, insurance, now)

            cursor.execute("""
                INSERT INTO server_objects (server_id, server_name, season, obj_type, slot, house_id, payday, insurance_status, exact_fall_time, last_updated, is_frozen, is_h2, is_estate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                    payday = excluded.payday,
                    house_id = COALESCE(excluded.house_id, server_objects.house_id),
                    insurance_status = excluded.insurance_status,
                    season = excluded.season,
                    exact_fall_time = excluded.exact_fall_time,
                    last_updated = excluded.last_updated,
                    is_frozen = excluded.is_frozen,
                    is_estate = excluded.is_estate
            """, (str(payload.server_id), payload.server_name, active_season, item.type, item.slot, item.house_id, item.payday, insurance, fall_time, now_str))

            cursor.execute("""
                INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (str(payload.server_id), item.slot, item.type, item.payday, now_str))

        conn.commit()
        conn.close()
        return {"status": "success", "count": len(payload.items)}
    except Exception as e:
        print(f"[API Error] {e}")
        return {"status": "error", "message": str(e)}, 500
