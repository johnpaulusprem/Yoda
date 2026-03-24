FROM python:3.11-slim AS base
WORKDIR /app

FROM base AS builder
COPY foundation/ /tmp/foundation/
RUN pip install --no-cache-dir /tmp/foundation/
COPY services/chat-service/ /tmp/service/
RUN pip install --no-cache-dir /tmp/service/

FROM base AS runtime
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/chat-service/src/ /app/src/
COPY foundation/src/ /app/foundation_src/
ENV PYTHONPATH="/app/src:/app/foundation_src"
EXPOSE 8003
CMD ["uvicorn", "chat_service.main:app", "--host", "0.0.0.0", "--port", "8003"]
