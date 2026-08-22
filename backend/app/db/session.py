from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    # Serverless Postgres closes idle connections without telling the client.
    # pre_ping catches a dead one at checkout; recycle retires it beforehand.
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)
