from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Assessor Platform"
    
    # Настройки PostgreSQL
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "secretpassword"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "assessor_db"

    STORAGE_DIR: str = "storage"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    class Config:
        env_file = "../.env"  # <--- Указываем путь на уровень выше, в корень проекта
        extra = "ignore"

settings = Settings()