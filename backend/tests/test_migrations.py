from pathlib import Path
import subprocess
import pytest

def test_alembic_structure():
    """Проверяет наличие конфигурации и папки миграций Alembic в проекте."""
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "alembic.ini"
    alembic_folder = backend_dir / "alembic"
    
    # Если вы еще не инициализировали Alembic, эти файлы/папки могут отсутствовать.
    # Этот тест подсветит, когда настанет время их добавить.
    if not alembic_ini.is_file() or not alembic_folder.is_dir():
        pytest.skip("Alembic еще не инициализирован в проекте (нет alembic.ini или папки alembic)")

    versions_folder = alembic_folder / "versions"
    assert versions_folder.is_dir(), "Папка alembic/versions/ для файлов миграций не найдена!"

def test_models_are_in_sync_with_migrations():
    """
    Проверяет с помощью 'alembic check', что изменения в моделях SQLAlchemy 
    не расходятся с файлами миграций.
    """
    if not Path("alembic.ini").exists():
        pytest.skip("Alembic не настроен, проверка sync пропущена")

    result = subprocess.run(
        ["alembic", "check"],
        capture_output=True,
        text=True,
        encoding="utf-8"
    )
    
    assert result.returncode == 0, (
        "Обнаружены изменения в моделях SQLAlchemy, для которых не созданы миграции!\n"
        f"Вывод:\n{result.stdout}\n{result.stderr}"
    )