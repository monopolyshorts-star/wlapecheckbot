import asyncio
import logging
import os
import uvicorn
from database import init_db
from server import app
from bot import dp, bot

logging.basicConfig(level=logging.INFO)

async def run_api():
    port = int(os.getenv("PORT", "10000"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot():
    await dp.start_polling(bot)

async def main():
    init_db()
    await asyncio.gather(run_api(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())
