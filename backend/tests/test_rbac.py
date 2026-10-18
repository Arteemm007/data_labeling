import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.workflow import User

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

def test_assessor_cannot_access_admin_endpoints():
    """Тест RBAC: Асессор получает ошибку доступа при попытке вызвать админские эндпоинты."""
    db = TestingSessionLocal()
    
    assessor = User(username="test_assessor", password="password123", role="assessor")
    db.add(assessor)
    db.commit()
    db.close()

    # Передаем actor_username обычного асессора
    response_backup = client.get("/workflow/superadmin/backup?actor_username=test_assessor")
    assert response_backup.status_code in [401, 403, 404]

    response_overlap = client.post("/workflow/admin/overlap?actor_username=test_assessor", json={"overlap_percent": 50})
    assert response_overlap.status_code in [401, 403, 422]