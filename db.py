from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()
engine = create_engine('sqlite:///history.db')
Session = sessionmaker(bind=engine)

class SummaryHistory(Base):
    __tablename__ = 'summary_history'
    id = Column(Integer, primary_key=True)
    summary = Column(Text, nullable=False)
    original_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
