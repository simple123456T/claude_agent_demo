FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
RUN pip install --no-cache-dir .
# Migrations ship in the image: `docker compose run --rm backend alembic upgrade head`
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations

RUN useradd --create-home --uid 10001 datagent
USER datagent
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
