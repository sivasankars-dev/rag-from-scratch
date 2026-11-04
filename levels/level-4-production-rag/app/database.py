from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from sqlalchemy import text
from app.config import load_database_url

def create_db_engine(database_url: str):
    return create_engine(
        database_url,
        pool_pre_ping=True,
        hide_parameters=True,
    )

def create_session_factory(engine):
    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

@contextmanager
def create_database_resources():
    engine = create_db_engine(load_database_url())

    try:
        # Engine creation alone does not verify connectivity.
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        session_factory = create_session_factory(engine)

        yield engine, session_factory
    finally:
        engine.dispose()