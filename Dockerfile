# FROM python:3.12-slim
# WORKDIR /app
# ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt
# COPY . .
# HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD python healthcheck.py
# CMD ["python", "bot.py"]
