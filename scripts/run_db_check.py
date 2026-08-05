import asyncio
from backend.app import database

async def main():
    print('DATABASE_URL:', database.DATABASE_URL)
    await database.init_db()
    async with database.async_session() as session:
        result = await session.execute("SELECT 1")
        print('result:', result)

if __name__ == '__main__':
    asyncio.run(main())
