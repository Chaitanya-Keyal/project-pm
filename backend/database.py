from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

# PM database (read-write) — contributors, task actions, conversations
pm_engine = create_async_engine(
    settings.pm_database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)
pm_session = async_sessionmaker(pm_engine, class_=AsyncSession, expire_on_commit=False)

# Lens database (read-only) — github_prs, pr_assessments, git_commits, etc.
lens_engine = create_async_engine(
    settings.lens_database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)
lens_session = async_sessionmaker(lens_engine, class_=AsyncSession, expire_on_commit=False)


async def get_pm_db():
    async with pm_session() as session:
        yield session


async def get_lens_db():
    async with lens_session() as session:
        yield session
