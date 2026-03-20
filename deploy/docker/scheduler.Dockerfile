FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY packages/common /app/packages/common
COPY services/scheduler /app/services/scheduler

RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -e /app/packages/common -e /app/services/scheduler

CMD ["python", "-m", "gvhmr_batch_scheduler.main"]

