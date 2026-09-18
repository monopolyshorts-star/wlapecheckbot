import asyncio
import logging
import uvicorn
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from database import init_db

# Импортируем роутеры и логику (предполагаем, что они в тех же файлах)
from server import app as fastapi_app
from bot import dp, bot, TOKEN

async def run_bot():
    logging.info("Запуск Telegram бота...")
    await dp.start_polling(bot)

async def run_server():
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=10000, log_level="info")
    server = uvicorn.Server(config)
    logging.info("Запуск API сервера на порту 10000...")
    await server.serve()

async def main():
    # Инициализируем базу данных при старте
    init_db()
    
    # Запускаем бота и сервер одновременно
    await asyncio.gather(
        run_server(),
        run_bot()
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
