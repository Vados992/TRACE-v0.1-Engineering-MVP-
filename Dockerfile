FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 trace && mkdir -p /var/lib/trace/evidence && chown -R trace:trace /var/lib/trace
WORKDIR /app

COPY requirements.lock /app/
RUN pip install -r requirements.lock

COPY services/api /app/services/api
COPY scripts /app/scripts
COPY db /app/db
COPY fixtures /app/fixtures

ENV PYTHONPATH=/app/services/api
USER trace

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
