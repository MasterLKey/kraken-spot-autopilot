FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

RUN mkdir -p /app/data /app/data/exports

VOLUME ["/app/data"]

CMD ["python", "-m", "bot", "run"]
