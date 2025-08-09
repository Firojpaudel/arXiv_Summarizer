from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

Base = declarative_base()
engine = create_engine('sqlite:///history.db')
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)  # Removed unique=True
    name = Column(String(255), nullable=False)
    provider = Column(String(50), nullable=False, default='google')  # Only 'google' now
    provider_id = Column(String(255), nullable=False)  # ID from the OAuth provider
    avatar_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to summaries
    summaries = relationship("SummaryHistory", back_populates="user", cascade="all, delete-orphan")

class SummaryHistory(Base):
    __tablename__ = 'summary_history'
    id = Column(Integer, primary_key=True)
    summary = Column(Text, nullable=False)
    original_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign key to user
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # Nullable for backward compatibility
    user = relationship("User", back_populates="summaries")

Base.metadata.create_all(engine)
