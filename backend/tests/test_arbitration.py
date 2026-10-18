import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.document import Document

# Используем SQLite в памяти для быстрых и изолированных тестов
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_conflict_detection():
    """Тест 1: Разные ответы («Иванов» и «Петров») создают конфликт."""
    db = TestingSessionLocal()
    doc = Document(filename="test_doc.pdf", file_url="http://example.com/test.pdf", status="pending")
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    # Асессор 1 отправляет вариант «Иванов» (исправили путь на /workflow/submit)
    response_1 = client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_1",
        "selected_doc_type": "passport",
        "data": {"fio": "Иванов"}
    })
    
    # Асессор 2 отправляет вариант «Петров»
    response_2 = client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_2",
        "selected_doc_type": "passport",
        "data": {"fio": "Петров"}
    })

    # Проверяем, что статус документа изменился на "conflict"
    db = TestingSessionLocal()
    updated_doc = db.query(Document).filter(Document.id == doc_id).first()
    assert updated_doc.status == "conflict"
    db.close()

def test_case_insensitive_match():
    """Тест 2: «иванов» и «Иванов» НЕ вызывают конфликт (регистр игнорируется)."""
    db = TestingSessionLocal()
    doc = Document(filename="test_doc_2.pdf", file_url="http://example.com/test2.pdf", status="pending")
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    # Асессор 1 отправляет «иванов»
    client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_1",
        "selected_doc_type": "passport",
        "data": {"fio": "иванов"}
    })
    
    # Асессор 2 отправляет «Иванов»
    client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_2",
        "selected_doc_type": "passport",
        "data": {"fio": "Иванов"}
    })

    # Проверяем, что конфликт НЕ возник
    db = TestingSessionLocal()
    updated_doc = db.query(Document).filter(Document.id == doc_id).first()
    assert updated_doc.status != "conflict"
    db.close()