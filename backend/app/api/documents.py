import os
import csv
import io
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.document import Document
from app.schemas.document import DocumentResponse
from app.schemas.workflow import CdnUrlsRequest
from app.services.storage import storage_service
from app.services.arbitration import recalculate_overlap
from app.workers.converter import convert_docx_to_pdf_task
from app.services.watermark import add_watermark_to_image, add_watermark_to_pdf
from typing import List

router = APIRouter(prefix="/documents", tags=["Документы"])


@router.post("/upload", response_model=DocumentResponse)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form(None),
    db: Session = Depends(get_db)
):
    try:
        file_path = storage_service.save_file(file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")

    is_word = file.filename.lower().endswith((".docx", ".doc"))
    initial_status = "converting" if is_word else "ready"

    db_document = Document(
        filename=file.filename,
        doc_type=doc_type,
        status=initial_status,
        file_url=file_path,
        is_golden=False
    )
    db.add(db_document)
    db.commit()
    db.refresh(db_document)

    # Пересчитываем выборку перехлеста с учетом нового документа
    recalculate_overlap(db)

    if is_word:
        background_tasks.add_task(convert_docx_to_pdf_task, db_document.id, file_path)

    return db_document


@router.post("/upload-urls")
def upload_cdn_urls(payload: CdnUrlsRequest, db: Session = Depends(get_db)):
    """Загрузка документов по одной или нескольким ссылкам на CDN."""
    added_docs = []
    for raw_url in payload.urls:
        url = raw_url.strip()
        if not url:
            continue
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path) or "cdn_document"
        doc = Document(
            filename=filename,
            doc_type=None,
            status="ready",
            file_url=url,
            is_golden=False
        )
        db.add(doc)
        added_docs.append(doc)

    db.commit()
    recalculate_overlap(db)
    return {"status": "success", "added_count": len(added_docs)}


@router.get("/", response_model=list[DocumentResponse])
def get_documents(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return db.query(Document).order_by(Document.id.desc()).offset(skip).limit(limit).all()


@router.get("/{doc_id}/file")
def get_document_file(doc_id: int, assessor_id: str = "anonymous", db: Session = Depends(get_db)):
    """Отдает локальный файл (с водяным знаком) или перенаправляет на CDN-ссылку."""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден в БД")

    # Если документ загружен по ссылке CDN
    if doc.file_url.startswith(("http://", "https://")):
        return RedirectResponse(url=doc.file_url)

    if not os.path.exists(doc.file_url):
        raise HTTPException(status_code=404, detail="Файл документа не найден на диске")

    file_path = doc.file_url
    filename_lower = file_path.lower()

    try:
        if filename_lower.endswith(".pdf"):
            watermarked_stream = add_watermark_to_pdf(file_path, assessor_id)
            return StreamingResponse(watermarked_stream, media_type="application/pdf")
        elif filename_lower.endswith((".jpg", ".jpeg", ".png")):
            watermarked_stream = add_watermark_to_image(file_path, assessor_id)
            return StreamingResponse(watermarked_stream, media_type="image/jpeg")
        else:
            return FileResponse(file_path)
    except Exception:
        # Если водяной знак не удалось наложить, отдаем файл напрямую
        return FileResponse(file_path)

@router.post("/upload-batch", response_model=list[DocumentResponse])
def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """Массовая загрузка файлов за один запрос с единовременным пересчетом перехлеста."""
    saved_documents = []
    
    for file in files:
        try:
            file_path = storage_service.save_file(file)
        except Exception:
            continue  # Пропускаем поврежденные файлы, если такие встретятся

        is_word = file.filename.lower().endswith((".docx", ".doc"))
        initial_status = "converting" if is_word else "ready"

        db_document = Document(
            filename=file.filename,
            doc_type=None,
            status=initial_status,
            file_url=file_path,
            is_golden=False
        )
        db.add(db_document)
        saved_documents.append(db_document)

        if is_word:
            background_tasks.add_task(convert_docx_to_pdf_task, db_document.id, file_path)

    db.commit()
    for doc in saved_documents:
        db.refresh(doc)

    # Пересчитываем выборку перехлеста ВСЕГО ОДИН РАЗ для всей пачки
    recalculate_overlap(db)

    return saved_documents

@router.post("/import-links-csv", response_model=list[DocumentResponse])
def import_links_from_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Массовый импорт документов по ссылкам из загруженного CSV-файла."""
    content = file.file.read().decode("utf-8-sig")  # Читаем с поддержкой UTF-8 BOM
    reader = csv.reader(io.StringIO(content))
    
    saved_documents = []
    for row in reader:
        if not row:
            continue
        # Берем первую колонку как URL (или файл)
        url = row[0].strip()
        if not url or url.startswith("#") or url.lower() == "url" or url.lower() == "link":
            continue  # Пропускаем заголовки или пустые строки
            
        filename = url.split("/")[-1].split("?")[0] or "imported_document.pdf"
        
        is_word = filename.lower().endswith((".docx", ".doc"))
        initial_status = "converting" if is_word else "ready"

        db_document = Document(
            filename=filename,
            doc_type=None,
            status=initial_status,
            file_url=url, # Ссылка на CDN / внешний источник
            is_golden=False
        )
        db.add(db_document)
        saved_documents.append(db_document)

    db.commit()
    for doc in saved_documents:
        db.refresh(doc)

    # Пересчитываем перехлест ровно один раз для всей пачки
    recalculate_overlap(db)

    return saved_documents