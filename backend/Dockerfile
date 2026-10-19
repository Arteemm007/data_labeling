FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements из папки backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код бэкенда в /app
COPY backend/ .

# Копируем папку frontend на уровень выше (в корень относительно /app, то есть в /frontend)
COPY frontend/ /frontend/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]