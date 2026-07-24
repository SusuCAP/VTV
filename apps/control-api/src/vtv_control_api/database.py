from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vtv_db.repository import ProjectRepository, SqlAlchemyProjectRepository

from .config import Settings
def create_repository(settings: Settings) -> ProjectRepository:
    if not settings.database_url:
        raise RuntimeError(
            "VTV_DATABASE_URL is required; configure PostgreSQL before starting the control API"
        )
    if not settings.database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("VTV_DATABASE_URL must use postgresql+asyncpg://")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyProjectRepository(sessions)
