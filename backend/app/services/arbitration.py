import re
import random
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.workflow import Submission, FinalResult, AppSetting


def _clean_text(val: str) -> str:
    """Удаляет все пробелы/отступы и приводит к нижнему регистру (сравниваем только буквы и цифры)."""
    return re.sub(r"\s+", "", str(val or "")).lower()


def normalize_answer(sub: Submission) -> dict:
    if sub.is_trash:
        return {"__is_trash__": True}

    normalized_data = {}
    for key, val in (sub.data or {}).items():
        if isinstance(val, dict):
            # unreadable теперь означает "Нечитаемо / блики", но текст асессора все равно учитывается, если он введен
            unreadable = bool(val.get("unreadable", False))
            raw_val = _clean_text(val.get("value", ""))
            normalized_data[key] = {"value": raw_val, "unreadable": unreadable}
        else:
            normalized_data[key] = {"value": _clean_text(val), "unreadable": False}

    return {
        "__is_trash__": False,
        "doc_type": _clean_text(sub.selected_doc_type or ""),
        "data": normalized_data,
    }

def answers_match(sub1: Submission, sub2: Submission) -> bool:
    return normalize_answer(sub1) == normalize_answer(sub2)


def get_overlap_percent(db: Session) -> int:
    setting = db.query(AppSetting).filter(AppSetting.key == "overlap_percent").first()
    if not setting:
        return 10
    try:
        return max(0, min(100, int(setting.value)))
    except ValueError:
        return 10


def recalculate_overlap(db: Session, new_percent: int | None = None):
    """Мгновенно пересчитывает флаг перехлеста (is_sample_double) для всех документов в базе."""
    if new_percent is not None:
        setting = db.query(AppSetting).filter(AppSetting.key == "overlap_percent").first()
        if not setting:
            setting = AppSetting(key="overlap_percent", value=str(new_percent))
            db.add(setting)
        else:
            setting.value = str(new_percent)
        db.commit()
    else:
        new_percent = get_overlap_percent(db)

    all_docs = db.query(Document).order_by(Document.id).all()
    total = len(all_docs)
    if total == 0:
        return

    target_double_count = round(total * (new_percent / 100.0))

    # Разделяем документы: те, где уже есть >= 2 ответов, трогать нельзя (они уже прошли двойную проверку)
    locked_double_docs = []
    adjustable_docs = []

    for doc in all_docs:
        active_subs_count = db.query(Submission).filter(
            Submission.document_id == doc.id,
            Submission.is_archived == False
        ).count()
        if active_subs_count >= 2 or doc.status == "conflict":
            doc.is_sample_double = True
            locked_double_docs.append(doc)
        else:
            adjustable_docs.append(doc)

    remaining_needed = max(0, target_double_count - len(locked_double_docs))

    # Сначала оставляем уже помеченные как double, если их не больше нужного, либо добираем/убираем
    current_doubles = [d for d in adjustable_docs if d.is_sample_double]
    current_singles = [d for d in adjustable_docs if not d.is_sample_double]

    if len(current_doubles) < remaining_needed:
        need_to_add = remaining_needed - len(current_doubles)
        chosen = random.sample(current_singles, min(need_to_add, len(current_singles)))
        for d in chosen:
            d.is_sample_double = True
    elif len(current_doubles) > remaining_needed:
        need_to_remove = len(current_doubles) - remaining_needed
        chosen = random.sample(current_doubles, min(need_to_remove, len(current_doubles)))
        for d in chosen:
            d.is_sample_double = False
            # Если у документа уже есть 1 ответ, он сразу становится полностью завершенным
            active_subs = db.query(Submission).filter(
                Submission.document_id == d.id,
                Submission.is_archived == False
            ).count()
            if active_subs == 1:
                d.status = "completed"

    db.commit()


def _upsert_final_result(db: Session, doc: Document, sub: Submission, resolution_type: str):
    final = db.query(FinalResult).filter(FinalResult.document_id == doc.id).first()
    if not final:
        final = FinalResult(
            document_id=doc.id,
            doc_type=sub.selected_doc_type,
            final_data=sub.data,
            is_trash=sub.is_trash,
            resolution_type=resolution_type
        )
        db.add(final)
    else:
        final.doc_type = sub.selected_doc_type
        final.final_data = sub.data
        final.is_trash = sub.is_trash
        final.resolution_type = resolution_type


def process_submission(db: Session, doc: Document, new_sub: Submission) -> str:
    """
    Логика по ТЗ:
    1. После первого асессора документ СРАЗУ попадает в FinalResult (в экспорт).
    2. Если документ в перехлесте (is_sample_double=True), он ждет второго асессора.
    3. После второго асессора: если совпало (без учета регистра и пробелов) — остается в экспорте.
       Если конфликт — удаляется из FinalResult (из экспорта) и переходит в статус 'conflict'.
    """
    if doc.is_golden:
        # Ищем эталонный результат для этого золотого скана
        golden_ref = db.query(FinalResult).filter(
            FinalResult.document_id == doc.id,
            FinalResult.resolution_type == "golden_standard"
        ).first()

        is_match = True
        if golden_ref:
            # Создаем временный объект для сравнения через наш механизм нормализации
            ref_sub = Submission(
                selected_doc_type=golden_ref.doc_type,
                data=golden_ref.final_data,
                is_trash=golden_ref.is_trash
            )
            is_match = answers_match(ref_sub, new_sub)

        if not is_match:
            # Фиксируем ошибку асессора на золотом скане
            new_sub.is_golden_error = True
            new_sub.is_archived = True  # Изолируем ошибочный ответ от экспорта
            db.commit()
            return "golden_error"
        else:
            # Если ответ правильный — засчитываем как успешное прохождение золотого скана
            doc.status = "completed"
            db.commit()
            return "golden_success"
            
    active_subs = db.query(Submission).filter(
        Submission.document_id == doc.id,
        Submission.is_archived == False
    ).order_by(Submission.id).all()

    count = len(active_subs)

    if count == 1:
        # Сразу добавляем в экспорт
        _upsert_final_result(db, doc, new_sub, "single_assessor")
        doc.doc_type = new_sub.selected_doc_type
        doc.status = "in_progress" if doc.is_sample_double else "completed"
        db.commit()
        return "added_to_export_waiting_second" if doc.is_sample_double else "completed_single"

    elif count >= 2:
        sub1, sub2 = active_subs[0], active_subs[1]
        if answers_match(sub1, sub2):
            _upsert_final_result(db, doc, sub1, "auto_2_of_2")
            doc.doc_type = sub1.selected_doc_type
            doc.status = "completed"
            db.commit()
            return "matched_double_check"
        else:
            # Конфликт! Убираем документ из экспорта и отправляем в 4 блок (Перепроверка)
            db.query(FinalResult).filter(FinalResult.document_id == doc.id).delete()
            doc.status = "conflict"
            db.commit()
            return "conflict_detected"

    return doc.status