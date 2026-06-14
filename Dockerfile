FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies into the system Python — no venv needed inside a container
COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --no-hashes -o /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt

# Copy application code
COPY . .

RUN useradd --system --create-home appuser && \
    chown -R appuser /app
USER appuser

EXPOSE 8123

CMD ["gunicorn", "web_server:app", "--bind", "0.0.0.0:8123", "--workers", "2", "--worker-tmp-dir", "/tmp"]
