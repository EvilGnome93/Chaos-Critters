from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import ASYNC_DATABASE_URL

engine = create_async_engine(ASYNC_DATABASE_URL, pool_pre_ping=True)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
