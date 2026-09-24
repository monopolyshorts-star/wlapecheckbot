import asyncio
import logging
import os

import uvicorn
from database import init_db
from server import app
from bot import bot, dp

logging.basicConfig(level=logging.INFO)

async def run_api():
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

async def main():
    init_db()
    logging.info("🚀 Запуск Arizona Tracker (API + Telegram Bot)...")
    await asyncio.gather(run_api(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())
