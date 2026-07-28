FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY backend/ backend/
COPY config/ config/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "backend.main"]
