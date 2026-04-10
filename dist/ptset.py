import asyncio
import websockets
import messages_pb2 # Твой скомпилированный файл

# ДАННЫЕ ИЗ ТВОЕГО ДАМПА 0.38
TOKEN = "ТВОЙ_BEARER_TOKEN_eyJ" 
WS_URL = "wss://server.boltgaming.io/ws"

async def standoff_bot():
    # Заголовки для авторизации (как в дампе)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    async with websockets.connect(WS_URL, extra_headers=headers) as ws:
        print("✅ Подключено к серверу Axlebolt!")

        # Пример отправки запроса на рынок через ClientMsg (стр. 21 дампа)
        msg = messages_pb2.ClientMsg()
        msg.id = "1"
        msg.cls = "Marketplace"
        msg.func = "GetListings"
        
        # Упаковываем ID предмета в BinaryValue
        val = messages_pb2.BinaryValue()
        val.one = int(1400).to_bytes(4, 'little') # ID AKR
        msg.data.append(val)

        await ws.send(msg.SerializeToString())
        print("📡 Запрос к рынку отправлен...")

        # Слушаем поток событий
        while True:
            raw_data = await ws.recv()
            server_msg = messages_pb2.ServerMsg()
            server_msg.ParseFromString(raw_data)

            # Обрабатываем события (новые лоты)
            for event in server_msg.events:
                if event.event == "OnNewListing":
                    # Вот здесь мы достаем Item ID и Наклейки!
                    # Данные лежат в event.params.one
                    print(f"🔥 ПОЙМАН НОВЫЙ ЛОТ! Расшифровываю...")
                    # Здесь мы применим структуру из твоего PDF (стр. 13)
            
            # Обрабатываем прямые ответы
            for resp in server_msg.responses:
                print(f"📩 Получен ответ на запрос {resp.id}")

if __name__ == "__main__":
    asyncio.run(standoff_bot())
