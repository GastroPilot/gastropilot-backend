FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

# Build context is gastropilot-backend/
COPY services/notifications/pyproject.toml .
RUN uv pip install --system --no-cache -e .

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --group app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY services/notifications/app/ ./app/
COPY packages/ /packages/

RUN chown -R app:app /app /packages
USER app

ENV PYTHONPATH=/packages:/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--proxy-headers", "--forwarded-allow-ips", "*"]
