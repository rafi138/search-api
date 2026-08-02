FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ca.crt /app/config/ca.crt
COPY . .

# Port + workers come from .env (injected by docker-compose env_file).
# Shell form so ${APP_PORT} / ${GUNICORN_WORKERS} expand at runtime.
CMD sh -c "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${GUNICORN_WORKERS:-32} -b 0.0.0.0:${APP_PORT:-8101} --timeout 120"
