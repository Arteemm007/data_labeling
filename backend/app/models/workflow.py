from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, JSON
from app.core.database import Base


class AppSetting(Base):
    """Системные настройки (например, процент перехлеста)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)


class DocumentType(Base):
    """Конструктор форм: типы документов и список их полей."""
    __tablename__ = "doc_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    fields_schema = Column(JSON, nullable=False)


class Submission(Base):
    """Ответ конкретного асессора по документу."""
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), index=True, nullable=False)
    assessor_id = Column(String, index=True, nullable=False)
    selected_doc_type = Column(String, nullable=True)
    data = Column(JSON, nullable=False, default=dict)
    is_trash = Column(Boolean, default=False)
    duration_seconds = Column(Float, default=0.0)
    is_golden_error = Column(Boolean, default=False)
    is_conflict_error = Column(Boolean, default=False)  # Ошибка при арбитраже конфликта или перепроверке
    is_archived = Column(Boolean, default=False)        # True, если документ отправлен на повторную перепроверку
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class FinalResult(Base):
    """Эталонный (финальный) результат разметки документа."""
    __tablename__ = "final_results"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, index=True, nullable=False)
    doc_type = Column(String, nullable=True)
    final_data = Column(JSON, nullable=False, default=dict)
    is_trash = Column(Boolean, default=False)
    resolution_type = Column(String, nullable=False)  # single_assessor, auto_2_of_2, admin_arbitration
    resolved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class User(Base):
    """Пользователи системы: assessor, admin, superadmin."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="assessor", nullable=False)  # "assessor", "admin", "superadmin"