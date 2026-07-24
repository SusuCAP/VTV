# VTV Control API Reference

Generated from FastAPI OpenAPI schema. Full interactive docs available at:
- Local: http://127.0.0.1:8000/docs (Swagger UI)
- Local: http://127.0.0.1:8000/redoc (ReDoc)
- JSON schema: docs/openapi.json

## Authentication
Set VTV_API_KEY env var to enable Bearer token auth. Empty = auth disabled (local dev).

## API Style
- REST + JSON
- Async tasks return HTTP 202 + {job_id}
- Progress via SSE: GET /v1/projects/{id}/events
- All timestamps: ISO 8601 UTC
