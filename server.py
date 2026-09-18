import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

class RealtorItem(BaseModel):
    slot: int
    payday: int
    type: str  # "Дом" или "Бизнес"
    state: Optional[str] = None # "Страх", "Нестрах" и т.д.

class RealtorPayload(BaseModel):
    server_id: str
    server_name: str
    season: str
    items: List[RealtorItem]

def calculate_fall_time(payday_val, insurance_status, update_time):
    try:
        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        hours_to_add = 0
        
        if insurance_status in ["Страх", "Страх, Занят"]:
            hours_to_add = payday_val - 1
        elif insurance_status in ["Страх, Незанят", "Нестрах", "Нестрах, Незанят"]:
            hours_to_add = (payday_val // 2) - 1 if payday_val > 1 else 0
        else:
            hours_to_add = payday_val - 1  # Дефолт
            
        fall_time = next_payday + timedelta(hours=max(0, hours_to_add))
        return fall_time.isoformat()
    except Exception:
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%d.%m.%Y %H:%M:%S")
    
    print(f"\n[API] Получен скан от: {payload.server_name} [{payload.server_id}] | Сезон: {payload.season}")

    for item in payload.items:
        # Пытаемся сохранить статус, если он пришел из Lua
        insurance = item.state
        
        # Если статус не пришел, пробуем восстановить из базы
        if not insurance:
            cursor.execute("""
                SELECT insurance_status FROM server_objects
                WHERE server_id = ? AND slot = ? AND obj_type = ?
            """, (payload.server_id, item.slot, item.type))
            row = cursor.fetchone()
            if row:
                insurance = row[0]

        fall_time = calculate_fall_time(item.payday, insurance, now)

        cursor.execute("""
            INSERT INTO server_objects (server_id, server_name, season, obj_type, slot, payday, insurance_status, exact_fall_time, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                payday = excluded.payday,
                insurance_status = COALESCE(excluded.insurance_status, server_objects.insurance_status),
                season = excluded.season,
                exact_fall_time = COALESCE(excluded.exact_fall_time, server_objects.exact_fall_time),
                last_updated = excluded.last_updated
        """, (payload.server_id, payload.server_name, payload.season, item.type, item.slot, item.payday, insurance, fall_time, now_str))

    conn.commit()
    conn.close()
    return {"status": "success", "count": len(payload.items)}

if __name__ == "__main__":
    import uvicorn
    print("[SERVER] Сервер API запущен на порту 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
