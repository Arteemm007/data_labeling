from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.document import Document
from app.models.workflow import DocumentType, Submission, FinalResult, User, AppSetting
from app.schemas.workflow import (
    DocTypeCreate,
    DocTypeResponse,
    SubmissionCreate,
    AdminResolveRequest,
    OverlapUpdate,
    UserCreate,
    UserUpdate,
    UserLogin,
)
from app.services.arbitration import (
    process_submission,
    get_overlap_percent,
    recalculate_overlap,
)
import json
from fastapi.responses import StreamingResponse
from app.core.i18n import get_message, get_lang

router = APIRouter(prefix="/workflow", tags=["Пайплайн разметки и Арбитраж"])


# ==================== 1. АВТОРИЗАЦИЯ И ПОЛЬЗОВАТЕЛИ ====================
@router.post("/login")
def login_user(payload: UserLogin, lang: str = Depends(get_lang), db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.username == payload.username,
        User.password == payload.password
    ).first()
    if not user:
        raise HTTPException(status_code=400, detail=get_message("invalid_credentials", lang))
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role
    }


@router.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "password": u.password,
            "role": u.role
        }
        for u in users
    ]


@router.post("/users")
def create_user(payload: UserCreate, actor_username: str = None, lang: str = Depends(get_lang), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail=get_message("user_exists", lang))
    
    if payload.role == "superadmin":
        actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
        if not actor or actor.role != "superadmin":
            raise HTTPException(status_code=403, detail=get_message("superadmin_only", lang))

    user = User(
        username=payload.username.strip(),
        password=payload.password,
        role=payload.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "password": user.password,
        "role": user.role
    }


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, actor_username: str = None, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Защита: назначить роль superadmin может только суперадмин
    if payload.role == "superadmin":
        actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
        if not actor or actor.role != "superadmin":
            raise HTTPException(status_code=403, detail="Только суперадмин может назначать роль суперадмина")

    old_username = user.username
    if payload.username and payload.username.strip() != user.username:
        new_uname = payload.username.strip()
        dup = db.query(User).filter(User.username == new_uname, User.id != user_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="Этот логин уже занят")
        user.username = new_uname
        db.query(Submission).filter(Submission.assessor_id == old_username).update(
            {Submission.assessor_id: new_uname}
        )

    if payload.password is not None and payload.password != "":
        user.password = payload.password
    if payload.role:
        user.role = payload.role

    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "password": user.password,
        "role": user.role
    }


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    db.delete(user)
    db.commit()
    return {"status": "deleted"}


# ==================== 2. КОНСТРУКТОР ФОРМ ====================
@router.post("/doc-types", response_model=DocTypeResponse)
def create_doc_type(payload: DocTypeCreate, db: Session = Depends(get_db)):
    existing = db.query(DocumentType).filter(DocumentType.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Такой тип документа уже существует")
    doc_type = DocumentType(
        name=payload.name.strip(),
        fields_schema=[f.model_dump() for f in payload.fields_schema]
    )
    db.add(doc_type)
    db.commit()
    db.refresh(doc_type)
    return doc_type


@router.get("/doc-types", response_model=list[DocTypeResponse])
def get_doc_types(db: Session = Depends(get_db)):
    return db.query(DocumentType).order_by(DocumentType.id).all()


@router.delete("/doc-types/{doc_type_id}")
def delete_doc_type(doc_type_id: int, db: Session = Depends(get_db)):
    dt = db.query(DocumentType).filter(DocumentType.id == doc_type_id).first()
    if not dt:
        raise HTTPException(status_code=404, detail="Тип документа не найден")
    db.delete(dt)
    db.commit()
    return {"status": "deleted"}


# ==================== 3. НАСТРОЙКА ПЕРЕХЛЕСТА ====================
@router.get("/admin/overlap")
def get_overlap(db: Session = Depends(get_db)):
    return {"overlap_percent": get_overlap_percent(db)}


@router.post("/admin/overlap")
def set_overlap(payload: OverlapUpdate, actor_username: str = None, db: Session = Depends(get_db)):
    actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
    if not actor or actor.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Доступ запрещен")
        
    percent = max(0, min(100, payload.overlap_percent))
    recalculate_overlap(db, percent)
    return {"status": "success", "overlap_percent": percent}


# ==================== 4. РАБОЧЕЕ МЕСТО АСЕССОРА ====================
@router.get("/next-task")
def get_next_task(assessor_id: str, db: Session = Depends(get_db)):
    """
    Выдает следующий документ асессору:
    - Документ не должен быть в статусе 'conflict'
    - Этот асессор еще не размечал данный документ в текущем цикле (is_archived == False)
    - У документа либо 0 ответов, либо 1 ответ и включен флаг перехлеста (is_sample_double == True)
    """
    all_docs = db.query(Document).filter(Document.status != "conflict").order_by(Document.id).all()

    for doc in all_docs:
        active_subs = db.query(Submission).filter(
            Submission.document_id == doc.id,
            Submission.is_archived == False
        ).all()

        # Если этот асессор уже размечал документ, пропускаем
        if any(s.assessor_id == assessor_id for s in active_subs):
            continue

        # Если 0 ответов — выдаем любому асессору
        if len(active_subs) == 0:
            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "file_url": doc.file_url,
                "doc_type": doc.doc_type
            }

        # Если 1 ответ и документ попал в выборку перехлеста — выдаем второму асессору
        if len(active_subs) == 1 and doc.is_sample_double:
            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "file_url": doc.file_url,
                "doc_type": doc.doc_type
            }

    return {"document_id": None, "detail": "Нет доступных документов для разметки"}


@router.post("/submit")
def submit_annotation(payload: SubmissionCreate, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == payload.document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    duplicate = db.query(Submission).filter(
        Submission.document_id == payload.document_id,
        Submission.assessor_id == payload.assessor_id,
        Submission.is_archived == False
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Вы уже размечали этот документ")

    new_sub = Submission(
        document_id=payload.document_id,
        assessor_id=payload.assessor_id,
        selected_doc_type=payload.selected_doc_type,
        data=payload.data,
        is_trash=payload.is_trash,
        duration_seconds=payload.duration_seconds
    )
    db.add(new_sub)
    db.commit()
    db.refresh(new_sub)

    result_stage = process_submission(db, doc, new_sub)
    return {
        "submission_id": new_sub.id,
        "document_id": doc.id,
        "new_document_status": doc.status,
        "pipeline_result": result_stage
    }


# ==================== 5. ПЕРЕПРОВЕРКА (КОНФЛИКТЫ) ====================
@router.get("/conflicts")
def get_conflicts(db: Session = Depends(get_db)):
    conflict_docs = db.query(Document).filter(Document.status == "conflict").order_by(Document.id).all()
    result = []
    for doc in conflict_docs:
        subs = db.query(Submission).filter(
            Submission.document_id == doc.id,
            Submission.is_archived == False
        ).order_by(Submission.id).all()
        result.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "file_url": doc.file_url,
            "submissions": [
                {
                    "id": s.id,
                    "assessor_id": s.assessor_id,
                    "selected_doc_type": s.selected_doc_type,
                    "data": s.data,
                    "is_trash": s.is_trash
                }
                for s in subs
            ]
        })
    return result


@router.post("/resolve/{document_id}")
def resolve_conflict(document_id: int, payload: AdminResolveRequest, db: Session = Depends(get_db)):
    """Админ выбирает правильный вариант из двух асессоров. Второму засчитывается ошибка."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    active_subs = db.query(Submission).filter(
        Submission.document_id == doc.id,
        Submission.is_archived == False
    ).all()

    for s in active_subs:
        if payload.winning_submission_id and s.id != payload.winning_submission_id:
            s.is_conflict_error = True
        elif payload.winning_assessor_id and s.assessor_id != payload.winning_assessor_id:
            s.is_conflict_error = True

    doc.status = "completed"
    doc.doc_type = payload.doc_type

    final = db.query(FinalResult).filter(FinalResult.document_id == doc.id).first()
    if not final:
        final = FinalResult(document_id=doc.id, resolution_type="admin_arbitration")
        db.add(final)

    final.doc_type = payload.doc_type
    final.final_data = payload.final_data
    final.is_trash = payload.is_trash
    final.resolution_type = "admin_arbitration"
    db.commit()

    return {"status": "resolved", "document_id": doc.id}


@router.post("/recheck/{document_id}")
def send_to_recheck(document_id: int, db: Session = Depends(get_db)):
    """
    Кнопка 'Отправить на перепроверку':
    Обоим асессорам засчитывается ошибка, их ответы уходят в архив,
    а документ снова становится доступен для разметки с нуля.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")

    active_subs = db.query(Submission).filter(
        Submission.document_id == doc.id,
        Submission.is_archived == False
    ).all()

    for s in active_subs:
        s.is_conflict_error = True
        s.is_archived = True

    db.query(FinalResult).filter(FinalResult.document_id == doc.id).delete()
    doc.status = "ready"
    db.commit()

    return {"status": "sent_to_recheck", "document_id": doc.id}


# ==================== 6. ЭКСПОРТ И СТАТИСТИКА ====================
@router.get("/export")
def export_results(format: str = "json", db: Session = Depends(get_db)):
    """Потоковая выгрузка данных (StreamingResponse) пачками по 500 записей для защиты от Out of Memory."""
    docs_map = {d.id: d.filename for d in db.query(Document).all()}
    
    if format == "csv":
        def generate_csv():
            yield '"document_id","filename","doc_type","is_trash","resolution_type","final_data"\n'
            batch_size = 500
            offset = 0
            while True:
                finals = db.query(FinalResult).order_by(FinalResult.document_id).offset(offset).limit(batch_size).all()
                if not finals:
                    break
                for f in finals:
                    row = [
                        str(f.document_id),
                        str(docs_map.get(f.document_id, "")),
                        str(f.doc_type or ""),
                        str(f.is_trash),
                        str(f.resolution_type),
                        json.dumps(f.final_data, ensure_ascii=False)
                    ]
                    # Исправление: заменяем двойные кавычки и собираем безопасную строку без слэшей внутри f-строки
                    safe_row = [v.replace('"', '""') for v in row]
                    escaped_row = [f'"{val}"' for val in safe_row]
                    yield ",".join(escaped_row) + "\n"
                offset += batch_size

        return StreamingResponse(
            generate_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=export_results.csv"}
        )
    else:
        def generate_json():
            yield "["
            batch_size = 500
            offset = 0
            first = True
            while True:
                finals = db.query(FinalResult).order_by(FinalResult.document_id).offset(offset).limit(batch_size).all()
                if not finals:
                    break
                for f in finals:
                    item = {
                        "document_id": f.document_id,
                        "filename": docs_map.get(f.document_id, ""),
                        "doc_type": f.doc_type,
                        "is_trash": f.is_trash,
                        "resolution_type": f.resolution_type,
                        "final_data": f.final_data,
                    }
                    prefix = "" if first else ","
                    first = False
                    yield prefix + json.dumps(item, ensure_ascii=False)
                offset += batch_size
            yield "]"

        return StreamingResponse(
            generate_json(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=export_results.json"}
        )
    
@router.get("/export/stats")
def get_export_stats(db: Session = Depends(get_db)):
    """Возвращает общее количество готовых документов и разбивку по их типам для Блока 3."""
    from sqlalchemy import func
    
    # Группируем завершенные документы из таблицы FinalResult по их типу
    stats_query = (
        db.query(FinalResult.doc_type, func.count(FinalResult.id))
        .group_by(FinalResult.doc_type)
        .all()
    )
    
    breakdown = []
    total_count = 0
    
    for doc_type, count in stats_query:
        dt_name = doc_type if doc_type else "Не указан"
        breakdown.append({"doc_type": dt_name, "count": count})
        total_count += count

    return {
        "total": total_count,
        "breakdown": breakdown
    }

@router.get("/admin/stats")
def get_admin_stats(db: Session = Depends(get_db)):
    total_docs = db.query(Document).count()
    completed_docs = db.query(FinalResult).count()

    # Показываем статистику по всем асессорам
    assessors = db.query(User).filter(User.role == "assessor").order_by(User.id).all()
    stats_list = []

    for u in assessors:
        subs = db.query(Submission).filter(Submission.assessor_id == u.username).all()
        total_completed = len(subs)
        total_time = round(sum((s.duration_seconds or 0.0) for s in subs), 1)
        avg_speed = round(total_time / total_completed, 1) if total_completed > 0 else 0.0
        errors_count = sum(1 for s in subs if s.is_conflict_error or s.is_golden_error)

        stats_list.append({
            "assessor_id": u.username,
            "total_completed": total_completed,
            "total_time_sec": total_time,
            "avg_speed_sec": avg_speed,
            "errors": errors_count
        })

    return {
        "total_documents": total_docs,
        "completed_documents": completed_docs,
        "stats": stats_list
    }


# ==================== 7. СУПЕРАДМИН: БЭКАП, ЗАГРУЗКА, СБРОС ====================
@router.get("/superadmin/backup")
def backup_all_data(actor_username: str = None, db: Session = Depends(get_db)):
    """Сохраняет полное состояние базы данных в JSON."""
    actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
    if not actor or actor.role != "superadmin":
        raise HTTPException(status_code=403, detail="Доступ разрешен только суперадмину")

    return {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": [{"key": s.key, "value": s.value} for s in db.query(AppSetting).all()],
        "users": [
            {"id": u.id, "username": u.username, "password": u.password, "role": u.role}
            for u in db.query(User).all()
        ],
        "doc_types": [
            {"id": dt.id, "name": dt.name, "fields_schema": dt.fields_schema}
            for dt in db.query(DocumentType).all()
        ],
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "doc_type": d.doc_type,
                "status": d.status,
                "file_url": d.file_url,
                "is_golden": d.is_golden,
                "is_sample_double": d.is_sample_double
            }
            for d in db.query(Document).all()
        ],
        "submissions": [
            {
                "id": s.id,
                "document_id": s.document_id,
                "assessor_id": s.assessor_id,
                "selected_doc_type": s.selected_doc_type,
                "data": s.data,
                "is_trash": s.is_trash,
                "duration_seconds": s.duration_seconds,
                "is_golden_error": s.is_golden_error,
                "is_conflict_error": s.is_conflict_error,
                "is_archived": s.is_archived
            }
            for s in db.query(Submission).all()
        ],
        "final_results": [
            {
                "id": f.id,
                "document_id": f.document_id,
                "doc_type": f.doc_type,
                "final_data": f.final_data,
                "is_trash": f.is_trash,
                "resolution_type": f.resolution_type
            }
            for f in db.query(FinalResult).all()
        ]
    }


@router.post("/superadmin/restore")
def restore_all_data(backup: dict[str, Any] = Body(...), actor_username: str = None, db: Session = Depends(get_db)):
    """Восстанавливает данные из ранее сохраненного резервного JSON-файла."""
    actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
    if not actor or actor.role != "superadmin":
        raise HTTPException(status_code=403, detail="Доступ разрешен только суперадмину")

    try:
        db.query(FinalResult).delete()
        db.query(Submission).delete()
        db.query(Document).delete()
        db.query(DocumentType).delete()
        db.query(AppSetting).delete()
        db.commit()

        for s in backup.get("settings", []):
            db.add(AppSetting(key=s["key"], value=str(s["value"])))

        for u in backup.get("users", []):
            existing = db.query(User).filter(User.username == u["username"]).first()
            if existing:
                existing.password = u["password"]
                existing.role = u["role"]
            else:
                db.add(User(username=u["username"], password=u["password"], role=u["role"]))

        for dt in backup.get("doc_types", []):
            db.add(DocumentType(name=dt["name"], fields_schema=dt["fields_schema"]))

        db.commit()

        # Сопоставляем старые ID документов с новыми
        doc_id_map = {}
        for d in backup.get("documents", []):
            new_doc = Document(
                filename=d["filename"],
                doc_type=d.get("doc_type"),
                status=d.get("status", "ready"),
                file_url=d["file_url"],
                is_golden=d.get("is_golden", False),
                is_sample_double=d.get("is_sample_double", False)
            )
            db.add(new_doc)
            db.flush()
            doc_id_map[d["id"]] = new_doc.id

        for s in backup.get("submissions", []):
            mapped_doc_id = doc_id_map.get(s["document_id"])
            if mapped_doc_id:
                db.add(Submission(
                    document_id=mapped_doc_id,
                    assessor_id=s["assessor_id"],
                    selected_doc_type=s.get("selected_doc_type"),
                    data=s.get("data", {}),
                    is_trash=s.get("is_trash", False),
                    duration_seconds=s.get("duration_seconds", 0.0),
                    is_golden_error=s.get("is_golden_error", False),
                    is_conflict_error=s.get("is_conflict_error", False),
                    is_archived=s.get("is_archived", False)
                ))

        for f in backup.get("final_results", []):
            mapped_doc_id = doc_id_map.get(f["document_id"])
            if mapped_doc_id:
                db.add(FinalResult(
                    document_id=mapped_doc_id,
                    doc_type=f.get("doc_type"),
                    final_data=f.get("final_data", {}),
                    is_trash=f.get("is_trash", False),
                    resolution_type=f.get("resolution_type", "single_assessor")
                ))

        db.commit()
        return {"status": "restored"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка восстановления: {str(e)}")


@router.delete("/superadmin/reset-all")
def reset_all_data(actor_username: str = None, db: Session = Depends(get_db)):
    """
    Полное удаление данных (Блок 7 Суперадмина):
    Удаляет все загруженные документы, обнуляет статистику асессоров,
    удаляет конструктор форм, экспорт данных и конфликты разметок.
    """
    actor = db.query(User).filter(User.username == actor_username).first() if actor_username else None
    if not actor or actor.role != "superadmin":
        raise HTTPException(status_code=403, detail="Доступ разрешен только суперадмину")

    try:
        db.query(FinalResult).delete()
        db.query(Submission).delete()
        db.query(Document).delete()
        db.query(DocumentType).delete()
        db.commit()
        return {"status": "success", "message": "Все данные успешно сброшены"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))