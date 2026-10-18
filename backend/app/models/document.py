from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)               
    doc_type = Column(String, nullable=True)                
    status = Column(String, default="uploaded", index=True) 
    file_url = Column(String, nullable=False)               
    is_golden = Column(Boolean, default=False)              
    
    # --- НОВОЕ ПОЛЕ ---
    is_sample_double = Column(Boolean, default=False)       # Попал ли документ в выборку перехлеста
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))