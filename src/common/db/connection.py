import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

load_dotenv()

HOST = os.getenv("PG_HOST")
PORT = os.getenv("PG_PORT")
USER = os.getenv("PG_USER")
PASSWORD = os.getenv("PG_PASSWORD")
DB_NAME = os.getenv("PG_DB")


DATABASE_URL = f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"

engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # SQL 로그 보려면 True
)

SessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)