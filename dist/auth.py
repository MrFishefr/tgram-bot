import asyncio
import ssl
import re
import schemes_pb2
import messages_pb2

async def bypass_and_get_token():
    # Данные из твоего дампа 0.38
    HOST = 'server.boltgaming.io'
    PORT = 2223
    VERSION = "0.38.0"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        reader, writer = await asyncio.open_connection(HOST, PORT, ssl=ctx)
        print("✅ Подключено к шлюзу Boltgaming")

        # 1. Handshake с твоим API-ключом (c7202ece...)
        handshake = schemes_pb2.ServerHandshake(
            gameId="standoff2",
            apiKey="c7202ece89390c490b1b94d5b71225e1",
            version=VERSION
        )
        msg1 = messages_pb2.ClientMsg(id="h1", cls="System", func="Handshake")
        msg1.data.append(messages_pb2.BinaryValue(one=handshake.SerializeToString()))
        
        # Шлем первый пакет
        p1 = msg1.SerializeToString()
        writer.write(len(p1).to_bytes(4, 'little') + p1)
        await writer.drain()
        await reader.read(1024) # Пропускаем ответ

        # 2. Имитируем вход GUEST (самый важный шаг из дампа)
        # Мы генерируем случайный ID устройства, чтобы сервер выдал НОВЫЙ токен
        login = schemes_pb2.Handshake(ticket="GUEST_ezzz_new_dev_1")
        msg2 = messages_pb2.ClientMsg(id="login_v1", cls="Auth", func="Login")
        msg2.data.append(messages_pb2.BinaryValue(one=login.SerializeToString()))
        
        p2 = msg2.SerializeToString()
        # Шлем с префиксом длины (4 байта, little-endian)
        writer.write(len(p2).to_bytes(4, 'little') + p2)
        await writer.drain()
        print("📡 Запрос GUEST-авторизации отправлен...")

        # 3. Читаем СЫРОЙ ответ без фильтров
        data = await reader.read(4096)
        if data:
            print(f"📩 ПОЛУЧЕН ОТВЕТ! Длина: {len(data)} байт")
            print(f"HEX: {data.hex()}")
            
            # Попробуем распарсить через ServerMsg (твоя структура из Proto)
            try:
                s_msg = messages_pb2.ServerMsg()
                # Пропускаем первые 4 байта длины
                s_msg.ParseFromString(data[4:])
                print(f"🔔 Сообщение от сервера: {s_msg}")
            except Exception as e:
                print(f"⚠️ Ошибка парсинга: {e}")
        else:
            print("❌ Сервер закрыл соединение без ответа.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        writer.close()

if __name__ == "__main__":
    asyncio.run(bypass_and_get_token())
