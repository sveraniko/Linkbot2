from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from app.config import settings

# Create engine with optimized connection pooling
engine = create_async_engine(
    settings.database.url,
    future=True,
    pool_pre_ping=True,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_timeout=settings.database.pool_timeout,
    pool_recycle=3600,  # Recycle connections every hour
    echo=settings.database.echo,
    echo_pool=settings.database.echo if settings.is_development else False
)

SessionLocal = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False, 
    class_=AsyncSession,
    autoflush=False  # Manual flushing for better performance
)

class Base(DeclarativeBase):
    pass

async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

@asynccontextmanager
async def session_scope():
    async with SessionLocal() as session:
        yield session
