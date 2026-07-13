import os
import psycopg

from dotenv import load_dotenv
from sqlalchemy import text

from src.common.db.connection import SessionLocal

from loguru import logger


async def db_connection_test():
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        logger.info(f"DB CONNECTION ✅, result: {value}")
    

def OLD_db_connection_test():
    load_dotenv()

    dsn = (
        f"postgresql://{os.getenv('PG_USER')}:{os.getenv('PG_PASSWORD')}"
        f"@{os.getenv('PG_HOST')}:{os.getenv('PG_PORT')}/{os.getenv('PG_DB')}"
    )

    print("DSN =", dsn)

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
                print("✅ Connected!")
                print("PostgreSQL version:", row[0])
    except Exception as e:
        print("❌ Connection failed:", e)

