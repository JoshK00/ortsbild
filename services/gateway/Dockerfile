FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY gateway ./gateway
RUN pip install --no-cache-dir .

RUN useradd --create-home appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "--factory", "gateway.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
