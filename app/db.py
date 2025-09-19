from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from app.config import settings

engine = create_async_engine(settings.database.url, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

@asynccontextmanager
async def session_scope():
    async with SessionLocal() as session:
        yield session
