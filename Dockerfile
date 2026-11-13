FROM python:3.12-slim

ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY main.py ./
COPY zapp ./zapp
EXPOSE 8011
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8011"]
