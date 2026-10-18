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

def test_export_contains_only_completed_documents():
    """Тест экспорта: в итоговом файле должны оказаться строго 3 завершенных документа."""
    db = TestingSessionLocal()

    # 1. Создаем 3 завершенных документа (у них есть запись в FinalResult)
    for i in range(1, 4):
        doc = Document(filename=f"completed_{i}.pdf", file_url=f"http://example.com/{i}.pdf", status="completed")
        db.add(doc)
        db.commit()
        
        final_res = FinalResult(
            document_id=doc.id,
            doc_type="passport",
            final_data={"fio": f"User {i}"},
            is_trash=False,
            resolution_type="single_assessor"
        )
        db.add(final_res)

    # 2. Создаем 1 документ в статусе "conflict" (не должен попасть в экспорт)
    conflict_doc = Document(filename="conflict.pdf", file_url="http://example.com/conflict.pdf", status="conflict")
    db.add(conflict_doc)

    # 3. Создаем 1 документ в процессе разметки "pending" (не должен попасть в экспорт)
    pending_doc = Document(filename="pending.pdf", file_url="http://example.com/pending.pdf", status="ready")
    db.add(pending_doc)
    
    db.commit()
    db.close()

    # Запускаем экспорт в формате JSON
    response = client.get("/workflow/export?format=json")
    
    assert response.status_code == 200
    
    # Парсим JSON-ответ (бэкенд возвращает список через StreamingResponse)
    exported_data = response.json()
    
    # Проверяем, что в выгрузке ровно 3 документа
    assert len(exported_data) == 3
    
    # Дополнительно проверяем ID выгруженных элементов
    exported_filenames = [item["filename"] for item in exported_data]
    assert "completed_1.pdf" in exported_filenames
    assert "completed_2.pdf" in exported_filenames
    assert "completed_3.pdf" in exported_filenames
    assert "conflict.pdf" not in exported_filenames
    assert "pending.pdf" not in exported_filenames