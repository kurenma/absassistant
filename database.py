from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from collections.abc import Iterator
from sqlalchemy.orm import Session
from settings import settings

engine = create_engine(settings.db_conn)

SessionLocal = sessionmaker(bind=engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
