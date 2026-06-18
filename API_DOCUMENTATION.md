# OCR-ArcheAI API Documentation

OCR-ArcheAI provides a FastAPI service for uploading, classifying, processing, reviewing, and exporting prior authorization fax documents. Processing now runs through the local OCR and extraction pipeline without an external workflow engine.

## Core Endpoints

### Health

`GET /health`

Returns basic API health.

### Upload One Document

`POST /upload`

Form fields:

- `file`: PDF, TIFF, PNG, JPG, or JPEG document.
- `tenant_id`: tenant identifier, defaults to `default`.
- `auto_process`: when `true`, queues local background processing.

When `auto_process=true`, poll `GET /jobs/{job_id}/summary` for progress and final status.

### Upload And Wait

`POST /upload/complete`

Uploads one document, runs local processing before returning, and includes the final summary and extracted fields in the response.

### Upload A Batch

`POST /upload/bulk`

Accepts multiple files in the `files` form field. Each file is classified before ingestion; non-prior-authorization documents are rejected.

### Process One Job

`POST /process/{job_id}?tenant_id=default`

Queues local background processing for an uploaded job.

### Process Multiple Jobs

`POST /process/bulk`

JSON body:

```json
{
  "job_ids": [1, 2, 3],
  "tenant_id": "default"
}
```

### Processing Status

`GET /process/status/{job_id}?tenant_id=default`

Returns page and OCR counts for a job.

### Job Summary

`GET /jobs/{job_id}/summary?tenant_id=default`

Returns high-level processing status, review flags, key extracted fields, and finality.

### Extracted Fields

`GET /jobs/{job_id}/fields?tenant_id=default`

Returns extracted fields from the horizontal summary view when available.

### Review UI

`GET /review-ui/{job_id}`

Opens the human review interface for a processed job.

### CSV Export

`GET /export-csv/{job_id}?tenant_id=default`

Downloads extracted fields as CSV.

## Local Development

Start the API:

```bash
python run.py
```

Start the Docker stack:

```bash
docker compose up --build
```

Main service ports:

- Backend API: `http://localhost:8001`
- Frontend: `http://localhost`
- PostgreSQL: `localhost:5432`
- PgAdmin, optional tools profile: `http://localhost:5050`
