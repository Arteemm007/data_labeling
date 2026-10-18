import os
from app.core.database import SessionLocal
from app.models.document import Document


def convert_docx_to_pdf_task(doc_id: int, docx_path: str):
    """Фоновая задача: конвертирует .docx в .pdf и обновляет статус в БД."""
    db = SessionLocal()
    try:
        pdf_path = os.path.splitext(docx_path)[0] + ".pdf"

        # Конвертируем Word в PDF
        from docx2pdf import convert
        convert(docx_path, pdf_path)

        # Обновляем запись в базе данных: меняем путь на PDF и статус на ready
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.file_url = pdf_path
            doc.filename = os.path.basename(pdf_path)
            doc.status = "ready"
            db.commit()
    except Exception as e:
        print(f"Ошибка конвертации документа {doc_id}: {e}")
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "conversion_error"
            db.commit()
    finally:
        db.close()