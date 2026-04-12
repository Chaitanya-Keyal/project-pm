from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from project_pm.config import settings

# PM database (read-write) — contributors, task actions, conversations
pm_engine = create_async_engine(
    settings.pm_database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)
pm_session = async_sessionmaker(pm_engine, class_=AsyncSession, expire_on_commit=False)


async def get_pm_db():
    async with pm_session() as session:
        yield session


@asynccontextmanager
async def get_pm_db_context():
    """Async context manager for DB access outside of FastAPI dependency injection."""
    async with pm_session() as session:
        yield session
