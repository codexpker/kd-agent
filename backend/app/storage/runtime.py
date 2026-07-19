from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.storage.database import create_database_engine, create_session_factory
from app.storage.repository import PaperRepository
from app.storage.pdf_repository import PdfRepository


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return create_session_factory(create_database_engine(database_url))


@lru_cache
def get_paper_repository(database_url: str) -> PaperRepository:
    return PaperRepository(get_session_factory(database_url))


@lru_cache
def get_pdf_repository(database_url: str) -> PdfRepository:
    return PdfRepository(get_session_factory(database_url))
