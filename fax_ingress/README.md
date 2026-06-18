# Fax Ingress Service (MVP)

This is the fax ingestion service for the OCR-ArcheAI MVP. It handles uploading fax documents and storing them for processing.

## Features

- ✅ Upload fax documents (PDF, TIFF, JPEG, PNG)
- ✅ SHA256-based deduplication
- ✅ Store files in local storage
- ✅ Track jobs in PostgreSQL database
- ✅ Multi-tenant support
- ✅ RESTful API with FastAPI
- ✅ Auto-generated API documentation

## Setup

1. Install dependencies:
```bash
cd fax_ingress
pip install -r requirements.txt
```

2. Make sure PostgreSQL is running and the database schema is applied:
```bash
cd ..
docker compose up -d db postgres-schema
```

3. Configure environment variables (optional):
Create a `.env` file in the root directory:
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fax_db
```

## Running the Service

### Option 1: Using the run script
```bash
python run.py
```

### Option 2: Using uvicorn directly
```bash
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

### Option 3: From the root directory
```bash
python -m uvicorn fax_ingress.app:app --host 0.0.0.0 --port 8001 --reload
```

## API Endpoints

### Health Check
```
GET /health
```

### Upload Fax
```
POST /upload
Content-Type: multipart/form-data

Parameters:
- file: File to upload (required)
- tenant_id: Tenant identifier (optional, default: "default")
```

### Get Fax Job
```
GET /jobs/{fax_job_id}
```

### List Fax Jobs
```
GET /jobs?tenant_id={tenant_id}&status={status}&limit=100&offset=0
```

## Testing

Test the upload endpoint:
```bash
# Using curl
curl -X POST "http://localhost:8001/upload" \
  -F "file=@test_document.pdf" \
  -F "tenant_id=default"

# Using PowerShell
$file = Get-Item "test_document.pdf"
$uri = "http://localhost:8001/upload"
$form = @{
    file = $file
    tenant_id = "default"
}
Invoke-RestMethod -Uri $uri -Method Post -Form $form
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Storage

Uploaded files are stored in the `storage/` directory at the root of the project.

## Notes

- This is the MVP version without Celery/Redis for background processing
- Files are processed synchronously in the ingestion phase
- For production, consider adding background task processing
