# Dockerfile (Recommended for Cloud Run)

# 1. Base Image: Use the Python version you developed with
FROM python:3.11-slim

# 2. Set Environment Variables for Python and Port
# Last build triggered: 2025-04-27 <--- ADD OR MODIFY A DATE
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
# Cloud Run automatically provides the PORT env var, gunicorn respects it when using --bind
ENV PORT 8080

# 3. Set Working Directory
WORKDIR /app

# 4. Install Dependencies (Good practice: copy only requirements first)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt
    # Ensure 'gunicorn' is listed in requirements.txt!

# 5. Copy Application Code (Respects .dockerignore)
COPY . .

# 6. Expose the Port the app runs on (Good practice)
EXPOSE 8080

# 7. Command to run the application using Gunicorn + Uvicorn workers
#    -w 4: Specifies 4 worker processes (adjust based on instance size/load)
#    -k uvicorn.workers.UvicornWorker: Tells Gunicorn to use Uvicorn for running the ASGI app
#    --bind 0.0.0.0:8080: Tells Gunicorn which address and port to listen on
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8080"]