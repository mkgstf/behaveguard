from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import DATABASE_URL

# `pool_pre_ping` avoids handing out dead connections after e.g. a DB restart.
# `future=True` pins 2.0-style behavior explicitly (SQLAlchemy 2.x default anyway).
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for one unit of work, mirroring the old sqlite3
    `connection()` context manager's commit/rollback/close semantics."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
