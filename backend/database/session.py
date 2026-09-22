"""
Database Session and Engine Initialization
Supports SQLite and PostgreSQL.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from backend.config.settings import settings
from backend.database.models import Base

# Ensure SQLite directory exists if local file path is used
if settings.DATABASE_URL.startswith("sqlite"):
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
    echo=False
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
ScopedSession = scoped_session(SessionFactory)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = ScopedSession()
    try:
        yield db
    finally:
        db.close()
