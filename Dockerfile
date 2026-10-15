FROM python:3.10-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home parser
COPY main.py parser.py database.py utils.py max_notify.py ./
USER 10001:10001
WORKDIR /data
CMD ["python", "-u", "/app/main.py"]
