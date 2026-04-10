import asyncio
import database as db

async def create_my_key():
    # 1. Подключаемся к базе (проверь имя файла базы!)
    # 2. Создаем ключ: "НАЗВАНИЕ_КЛЮЧА", КОЛ-ВО ДНЕЙ
    await db.generate_key("sigmakillerlegenda1227", 30)
    print("✅ Ключ успешно добавлен! Теперь введи его в боте.")

if __name__ == "__main__":
    asyncio.run(create_my_key())
