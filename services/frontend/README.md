# OCR-ArcheAI React Frontend

A lightweight React + Vite interface to upload fax documents and trigger the existing `POST /upload` endpoint in `fax_ingress`.

## Development

1. Install dependencies from the frontend service directory:
   ```bash
   cd services/frontend
   npm install
   ```
2. Run the dev server:
   ```bash
   npm run dev
   ```
3. Open the UI at http://localhost:5173 (Vite default port).

> The form posts to http://localhost:8001/upload by default. Ensure the backend API is running locally before uploading.

## Job lookup

The page also includes a clean job metadata lookup powered by `GET /jobs/{fax_job_id}`. Enter an ID after uploading to see the stored tenant/status/timestamps directly from PostgreSQL.

## Browse jobs

Use the “Load all jobs” button to call `GET /jobs` and render the list of stored records. This helps you verify the database output without hitting the CLI.

## Trigger processing

The UI now includes a lightweight processing panel that invokes `POST /process/{job_id}` on the processing API and shows a simple progress indicator while the background work begins.
