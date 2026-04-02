FROM python:3.12-slim AS base
WORKDIR /app

FROM base AS builder
COPY foundation/ /tmp/foundation/
RUN pip install --no-cache-dir /tmp/foundation/
COPY services/yoda-api/ /tmp/service/
RUN pip install --no-cache-dir /tmp/service/

FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/yoda-api/src/ /app/src/
COPY foundation/src/ /app/foundation_src/
ENV PYTHONPATH="/app/src:/app/foundation_src"
ENV PORT=8001
EXPOSE ${PORT}
CMD ["sh", "-c", "uvicorn yoda_api.main:app --host 0.0.0.0 --port ${PORT}"]
