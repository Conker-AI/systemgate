FROM python:3.12-slim

WORKDIR /app

# Debian security fixes newer than the base image.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY systemgate ./systemgate

EXPOSE 8040
CMD ["python", "-m", "uvicorn", "systemgate.main:app", "--host", "0.0.0.0", "--port", "8040"]

