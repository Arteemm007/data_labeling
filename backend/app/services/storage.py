import os
from fastapi import UploadFile
from app.core.config import settings

# Создаем папку для хранения файлов, если её нет
STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)


class LocalStorageService:
    @staticmethod
    def save_file(file: UploadFile) -> str:
        file_path = os.path.join(STORAGE_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
        return file_path


storage_service = LocalStorageService()