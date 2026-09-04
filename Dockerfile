FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8080
CMD ["sh", "-c", "gunicorn -w 2 -k gthread --threads 4 --timeout 60 -b 0.0.0.0:${PORT:-8080} wsgi:application"]
