FROM python:3.12-slim

WORKDIR /tests

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY test_pipeline.py .

CMD ["pytest", "-q", "test_pipeline.py"]
