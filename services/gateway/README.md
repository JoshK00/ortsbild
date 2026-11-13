# Connector Gateway

The entrance for new reports. It takes a report in from a channel, checks the input of that channel and hands the report to the backend **in the backend's format** (`IncomingReport`, see `backend/models/incoming_report.py`). It contains no AI and keeps no data of its own: the backend and its agent network set the rules, the gateway adapts to them.

Channels today: **the app**. Planned: email, partner apps (see the TODOs).

```
                      ┌──────────── Caddy ────────────┐
iPhone app ── POST /v1/reports ──► gateway ──► backend: POST /internal/v1/reports ──► privacy → classification → research → draft
           ── everything else (login, answer, approve, photos, dashboard) ─────────► backend
```

## What the gateway does with a report from the app

1. **Same request as before.** `POST /v1/reports` takes exactly the form the app sends (`ios/Ortsbild/Services/BackendClient.swift`) with the same rules as the backend (`backend/api/reports.py`). The app does not change.
2. **Checks the channel input**: form fields, photo size (15 MB) and the real image type (JPEG, PNG, HEIC, read from the file).
3. **Stores the raw photo** in the raw bucket of the backend, at the ref the privacy layer expects: `raw/<report id>/p1.<ext>`. The photo is not changed: removing metadata and covering faces is the job of the privacy layer.
4. **Builds the report** in the backend's format (`GatewaySubmission` = `IncomingReport` without the user, `backend/models/gateway_submission.py`).
5. **Hands it over** to `POST /internal/v1/reports` with the user's token (passed on unchanged, the backend checks it) and the shared `GATEWAY_KEY`.
6. **Relays the answer** of the backend to the app as it is (status code and body).

Who owns the raw photo: until the backend takes the report, the gateway. If the backend does not take it (401, 403, 422, 429, a retry of an existing report, or the backend is unreachable), the gateway deletes the photo. Once the backend took it, its privacy layer deletes the raw photo after the sanitized copy exists. On a backend error (5xx) or a timeout the gateway leaves it, as the privacy layer keeps the raw data of a failed run for the operator.

## Layout

| Path | What it does |
| --- | --- |
| `gateway/app_channel.py` | The app channel: `POST /v1/reports` |
| `gateway/photos.py` | Is the upload really a JPEG, PNG or HEIC? |
| `gateway/raw_store.py` | Writes into the raw bucket of the backend (S3, locally moto) |
| `gateway/backend.py` | Hands a report to the backend's entrance |
| `gateway/config.py` | Settings, with the same variable names as the backend |
| `../../backend/api/gateway.py` | The backend's entrance for the gateway |
| `../../docs/api/openapi.json` | The request of the app as the gateway takes it. Generated, never edited by hand |

## Configuration

The gateway reads the env file of the backend (the names are the same), plus two of its own:

| Variable | Meaning |
| --- | --- |
| `GATEWAY_KEY` | Shared secret of gateway and backend. Without it in the backend, its entrance for the gateway does not exist. |
| `BACKEND_URL` | Default `http://backend:8000` (inside docker compose) |
| `STORAGE_ENDPOINT_URL`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_REGION`, `STORAGE_BUCKET_RAW` | The raw bucket of the backend |

## Run locally (with the backend)

In `backend/` (see the backend's setup for `.env`), add `GATEWAY_KEY` to `backend/.env` (any long random text), then:

```powershell
cd backend
docker compose up --build
```

`http://localhost:8088` is Caddy with the same routing as on the server (new reports to the gateway, everything else to the backend). The gateway alone is on `http://localhost:8080`, the backend alone on `http://localhost:8000`.

A full test through the real API, with Josh's script of test reports (it opens a session for a test user, no Apple login needed):

```powershell
docker compose exec backend python scripts/seed_stuttgart_reports.py --base http://caddy
docker compose logs gateway
```

## Tests

```powershell
cd services/gateway
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

`tests/test_with_backend.py` runs the gateway together with the real backend code. It needs the backend's dependencies (`pip install -r ../../backend/requirements.txt`) and is skipped without them.

Before a commit: `ruff check .`, `ruff format .` and `python scripts/export_openapi.py` (CI checks all three).

## Open

- TODO: Email channel: needs a rule for reports without a position, a way for the sender to approve, and an answer by email. The first version (IMAP poller, parser) is in the git history (commit 8962c4f).
- TODO: Partner apps and Open311 as further channels.
- TODO: The app waits for the whole chain in one request. Once the app asks for the status by polling, the gateway can answer at once.
