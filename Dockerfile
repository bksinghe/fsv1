# Build dependencies separately so compilers never enter the runtime image.
FROM python:3.11-slim-bookworm AS builder

# Some dependencies (including Hydrogram's pyaes) may need building from source.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/pip check

# The same Python base keeps the built virtual environment compatible.
FROM python:3.11-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . .
CMD ["python", "bot.py"]
