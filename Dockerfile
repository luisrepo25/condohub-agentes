# Agentes (FastAPI). Construir: docker build -t condohub-agentes services/agentes
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install .
RUN useradd --system --uid 10001 condohub
USER condohub
EXPOSE 8084
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8084), 2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8084"]