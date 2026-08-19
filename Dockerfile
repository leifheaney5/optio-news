FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Preserve the current production behavior for now: main.py starts the Flask
# server and the existing in-process daily scheduler. Once the dedicated
# Railway digest cron service is live, the web service can override this with
# a single-worker gunicorn start command so the scheduler no longer keeps it
# awake.
CMD ["python", "main.py"]
