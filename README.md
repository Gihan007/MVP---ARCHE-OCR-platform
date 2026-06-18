# OCR - Integrated Fax Processing System

## System Architecture

Unified API architecture for fax document OCR and field extraction:

```text
User -> Frontend (80) -> Backend API (8001) -> PostgreSQL
```

## Service Folders

Docker service-owned files live under `services/`:

- `services/backend`: backend Dockerfile
- `services/frontend`: frontend app, Dockerfile, and Nginx config
- `services/postgres`: database Dockerfile and schema

The Python packages remain at the repo root so local imports and `run.py` keep working.

## Services

### Backend API (Port 8001)

- Upload fax files (PDF/TIFF/images)
- SHA256 deduplication
- Store files and create job records
- Run local OCR and extraction processing
- Docs: http://localhost:8001/docs

### Frontend (Port 80)

- Upload, processing, and review dashboard
- Dev command: `cd services/frontend && npm run dev`

### PostgreSQL (Port 5432)

- Stores job metadata and extracted fields
- Optional pgAdmin UI: http://localhost:5050

## Quick Start

```bash
docker compose up --build
```

## Local Backend

```bash
python run.py
```

## Frontend Shell

```bash
cd services/frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` if the API is behind another host or port.

## Usage

1. Upload: `POST http://localhost:8001/upload`
2. Process: `POST http://localhost:8001/process/{job_id}`
3. Query: `GET http://localhost:8001/jobs/{job_id}`
