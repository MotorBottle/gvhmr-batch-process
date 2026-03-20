FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY packages/common /app/packages/common
COPY packages/gvhmr_runner /app/packages/gvhmr_runner
COPY services/api /app/services/api

RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -e /app/packages/common -e /app/packages/gvhmr_runner -e /app/services/api

EXPOSE 8000

CMD ["uvicorn", "gvhmr_batch_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
