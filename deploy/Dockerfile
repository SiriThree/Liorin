FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir . "psycopg[binary]>=3.2" "redis>=5.0" "fastapi>=0.115" "uvicorn[standard]>=0.34"

EXPOSE 2024
CMD ["uvicorn", "production.api:app", "--host", "0.0.0.0", "--port", "2024"]
