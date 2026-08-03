# Build context is the repo root (see docker-compose.yml) so this Dockerfile
# can pull in both backend/ and frontend/ for a single combined image.

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini .
COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./app/static

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && cd app && python seed.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
