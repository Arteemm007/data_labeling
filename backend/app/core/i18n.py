from fastapi import Header

TRANSLATIONS = {
    "ru": {
        "user_exists": "Такой пользователь уже существует",
        "superadmin_only": "Только суперадмин может выполнять это действие",
        "user_not_found": "Пользователь не найден",
        "username_taken": "Этот логин уже занят",
        "doc_type_exists": "Такой тип документа уже существует",
        "doc_type_not_found": "Тип документа не найден",
        "doc_not_found": "Документ не найден",
        "already_annotated": "Вы уже размечали этот документ",
        "no_tasks": "Нет доступных документов для разметки",
        "unauthorized": "Доступ запрещен",
        "reset_success": "Все данные успешно сброшены",
        "invalid_credentials": "Неверный логин или пароль",
    },
    "en": {
        "user_exists": "User already exists",
        "superadmin_only": "Only superadmin can perform this action",
        "user_not_found": "User not found",
        "username_taken": "This username is already taken",
        "doc_type_exists": "Document type already exists",
        "doc_type_not_found": "Document type not found",
        "doc_not_found": "Document not found",
        "already_annotated": "You have already annotated this document",
        "no_tasks": "No available documents for labeling",
        "unauthorized": "Access denied",
        "reset_success": "All data has been successfully reset",
        "invalid_credentials": "Invalid username or password",
    }
}

def get_message(key: str, lang: str = "ru") -> str:
    """Возвращает переведенный текст по ключу. Если язык не поддерживается, падает на русский."""
    lang = lang if lang in TRANSLATIONS else "ru"
    return TRANSLATIONS[lang].get(key, key)

def get_lang(accept_language: str = Header(default="ru")) -> str:
    # Берем первые 2 символа, например из "en-US,en;q=0.9" -> "en"
    lang = accept_language.split(",")[0].strip()[:2].lower()
    return lang if lang in ["ru", "en"] else "ru"