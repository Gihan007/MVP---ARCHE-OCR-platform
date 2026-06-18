# Deployment

The Docker stack now runs the application without an external workflow engine.

## Services

- `db`: PostgreSQL application database on port `5432`
- `postgres-schema`: one-shot schema initialization
- `backend`: FastAPI API on port `8001`
- `frontend`: Nginx-served frontend on port `80`
- `pgadmin`: optional PostgreSQL UI on port `5050` with the `tools` profile

## Start

```bash
docker compose up --build
```

## Optional Tools

```bash
docker compose --profile tools up pgadmin
```

## Check Status

```bash
docker compose ps
curl http://localhost:8001/health
```

## Logs

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
```

## Stop

```bash
docker compose down
```

To remove the database volume as well:

```bash
docker compose down -v
```
