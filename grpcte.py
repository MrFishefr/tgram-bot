import grpc
import schemes_pb2_grpc
import schemes_pb2

async def test_grpc():
    # Попробуем официальный gRPC порт
    channel = grpc.secure_channel('://axlebolt.com', grpc.ssl_channel_credentials())
    # Название сервиса возьми из своего schemes_pb2_grpc.py (например, MarketplaceStub)
    stub = schemes_pb2_grpc.MarketplaceStub(channel) 
    
    try:
        print("--- Запрос рынка через gRPC ---")
        # Пробуем вызвать метод получения лотов напрямую
        request = schemes_pb2.GetMarketListingsRequest(itemDefinitionId=1400)
        response = stub.GetListings(request)
        print("✅ Ответ получен!")
    except Exception as e:
        print(f"❌ Ошибка gRPC: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_grpc())
