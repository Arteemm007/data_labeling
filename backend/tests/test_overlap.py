import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.document import Document
from app.models.workflow import FinalResult

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

def test_overlap_and_double_verification():
    """Тест перехлеста: при совпадении ответов двух асессоров документ переходит в завершенные."""
    db = TestingSessionLocal()
    
    # Шаг А: Создаем тестовый документ, принудительно пометив его как двойную выборку (перехлест)
    doc = Document(
        filename="overlap_doc.pdf",
        file_url="http://example.com/overlap.pdf",
        status="ready",
        is_sample_double=True # Попал в выборку перехлеста
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id
    db.close()

    # Шаг Б: Асессор 1 дает ответ
    response_1 = client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_1",
        "selected_doc_type": "passport",
        "data": {"fio": "Иванов"}
    })
    assert response_1.status_code == 200
    
    # Проверяем, что документ еще не завершен (ждет второго асессора из-за перехлеста)
    db = TestingSessionLocal()
    doc_check = db.query(Document).filter(Document.id == doc_id).first()
    assert doc_check.status != "completed"
    db.close()

    # Шаг В: Асессор 2 дает ТАКОЙ ЖЕ ответ
    response_2 = client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "assessor_2",
        "selected_doc_type": "passport",
        "data": {"fio": "Иванов"}
    })
    assert response_2.status_code == 200

    # Шаг Г: Проверяем, что при совпадении ответов документ получил статус "completed" 
    # и записался в финальные результаты (FinalResult)
    db = TestingSessionLocal()
    completed_doc = db.query(Document).filter(Document.id == doc_id).first()
    final_res = db.query(FinalResult).filter(FinalResult.document_id == doc_id).first()
    
    assert completed_doc.status == "completed"
    assert final_res is not None
    assert final_res.final_data.get("fio") == "Иванов"
    db.close()