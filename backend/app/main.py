import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text
from app.core.database import engine, Base, SessionLocal
from app.models import document, workflow
from app.api import documents, workflow as workflow_api

Base.metadata.create_all(bind=engine)


def run_auto_migrations_and_seed():
    # 1. Безопасное добавление новых колонок в существующую БД
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_sample_double BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS is_conflict_error BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE submissions ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;"))

    db = SessionLocal()
    try:
        # 2. Настройка процента перехлеста по умолчанию (10%)
        overlap_setting = db.query(workflow.AppSetting).filter(workflow.AppSetting.key == "overlap_percent").first()
        if not overlap_setting:
            db.add(workflow.AppSetting(key="overlap_percent", value="10"))

        # 3. Создание дефолтного суперадмина, если его нет
        superadmin = db.query(workflow.User).filter(workflow.User.username == "superadmin").first()
        if not superadmin:
            db.add(workflow.User(username="superadmin", password="admin", role="superadmin"))

        # Приводим старую роль 'user' к единому стандарту 'assessor'
        old_users = db.query(workflow.User).filter(workflow.User.role == "user").all()
        for u in old_users:
            u.role = "assessor"

        db.commit()
    finally:
        db.close()


run_auto_migrations_and_seed()

app = FastAPI(
    title="Assessor Platform API",
    description="Система разметки и перекрестной проверки документов",
    version="1.0.0"
)

app.include_router(documents.router)
app.include_router(workflow_api.router)


@app.get("/", include_in_schema=False)
def serve_frontend():
    """Отдает главный веб-интерфейс приложения."""
    frontend_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")
    )
    return FileResponse(frontend_path)


@app.get("/ping", tags=["Проверка связи"])
def ping():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}