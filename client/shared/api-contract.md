# Client API Contract

The desktop UI talks to a local FastAPI service at `http://127.0.0.1:8000`.

Required endpoints:

- `GET /api/health`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/validate`
- `POST /api/sessions/{session_id}/run`
- `POST /api/sessions/{session_id}/cancel`
- `GET /api/sessions/{session_id}/events`
- `GET /api/sessions/{session_id}/report`
- `POST /api/uploads/vmcore`
- `GET /api/settings/env`
- `PUT /api/settings/env`
- `POST /api/settings/env/load`

`POST /api/uploads/vmcore` accepts multipart form-data with a `file` field and
returns:

```json
{
  "filename": "vmcore",
  "stored_path": "C:/path/to/cache/client_uploads/vmcore/<id>/vmcore",
  "size": 123456
}
```

The returned `stored_path` should be assigned to `config.vmcore` when creating a
new session.

`GET /api/settings/env` returns the `.env` path and masked key status. `PUT
/api/settings/env` accepts:

```json
{
  "values": {
    "API_KEY": "sk-...",
    "MODEL_NAME": "gpt-4o",
    "TAVILY_API_KEY": "..."
  }
}
```

Only allowlisted environment keys are persisted. Existing configured values are
kept when omitted by the client.

`POST /api/settings/env/load` accepts an existing `.env` path and makes it the
active environment file for the client:

```json
{
  "path": "C:/Users/me/project/.env"
}
```

The path is persisted in `cache/client_settings.json`, so the client keeps using
the same `.env` after restart.
