from app.config import load_database_url
from sqlalchemy import text
from app.database import create_db_engine


def main():
    engine = create_db_engine(load_database_url())

    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT current_database(), current_user")
            )
            print(result.one())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()