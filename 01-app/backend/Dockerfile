FROM python:3.12-slim

WORKDIR /app/01-app/backend
COPY 01-app/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY 01-app/backend ./
COPY 03-training /app/03-training

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
