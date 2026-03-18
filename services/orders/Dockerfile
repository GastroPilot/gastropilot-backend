FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is gastropilot-backend/
COPY services/orders/pyproject.toml .
RUN pip install --no-cache-dir build && pip install --no-cache-dir .

COPY services/orders/app/ ./app/
COPY packages/ /packages/

ENV PYTHONPATH=/packages:/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
