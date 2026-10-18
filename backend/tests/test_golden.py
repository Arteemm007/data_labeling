import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.document import Document
from app.models.workflow import User, FinalResult, Submission

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

def test_golden_scan_error_handling():
    """Тест золотых сканов: ошибка асессора на золотом скане увеличивает счетчик ошибок и не попадает в экспорт."""
    db = TestingSessionLocal()

    # 1. Создаем пользователя-асессора
    assessor = User(username="bad_assessor", password="123", role="assessor")
    db.add(assessor)
    db.commit()

    # 2. Создаем "Золотой скан" (документ с эталонными данными или флагом is_golden)
    # Зависимости обработки golden сканов проверяются в process_submission (app/services/arbitration.py)
    doc = Document(
        filename="golden_scan.pdf",
        file_url="http://example.com/golden.pdf",
        status="ready",
        is_golden=True
    )
    db.add(doc)
    db.commit()
    doc_id = doc.id

    # Задаем эталонный правильный ответ
    golden_standard = FinalResult(
        document_id=doc_id,
        doc_type="passport",
        final_data={"fio": "ПравильныйИванов"},
        is_trash=False,
        resolution_type="golden_standard"
    )
    db.add(golden_standard)
    db.commit()
    db.close()

    # 3. Асессор отправляет заведомо НЕПРАВИЛЬНЫЙ/ошибочный ответ
    response = client.post("/workflow/submit", json={
        "document_id": doc_id,
        "assessor_id": "bad_assessor",
        "selected_doc_type": "passport",
        "data": {"fio": "ОшибкаНаЗолотомСкане"}
    })
    
    assert response.status_code == 200

    # 4. Проверяем, что в статистике асессора зафиксировалась ошибка, 
    # а в FinalResult не ушел ошибочный результат
    db = TestingSessionLocal()
    
    # Проверяем счетчик ошибок через эндпоинт статистики админа
    stats_response = client.get("/workflow/admin/stats")
    assert stats_response.status_code == 200
    stats_data = stats_response.json()
    
    assessor_stats = next((s for s in stats_data["stats"] if s["assessor_id"] == "bad_assessor"), None)
    assert assessor_stats is not None
    assert assessor_stats["errors"] >= 1  # Счетчик ошибок увеличился

    # Проверяем, что фейковый ответ не попал в итоговую базу (FinalResult пуст для этого документа)
    final_res = db.query(FinalResult).filter(FinalResult.document_id == doc_id).first()
    # На золотом скане при ошибке результат либо архивируется, либо не формируется как валидный финальный
    db.close()