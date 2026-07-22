FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# En producción: alembic upgrade head antes de arrancar (ver README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
