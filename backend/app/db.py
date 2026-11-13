from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings

class Base(DeclarativeBase):
    pass

settings = get_settings()
if settings.database_url.startswith('sqlite:///') and ':memory:' not in settings.database_url:
    db_file = Path(settings.database_url.removeprefix('sqlite:///'))
    db_file.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}, pool_pre_ping=True)
if settings.database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_pragmas(dbapi_connection, _):
        cur = dbapi_connection.cursor()
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        yield db
