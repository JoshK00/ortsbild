# Ortsbild

Ortsbild is an iPhone app for reporting defects in public space (potholes, broken lights, illegal dumping). A citizen
photographs the defect. The server removes personal data, classifies the report, researches the responsible authority
and drafts a short message. The citizen checks and releases it. Released reports appear on a public dashboard, where
reports about the same defect count as votes for one case.

University project. The design goal is privacy first: nothing leaves our server before a local privacy layer has removed
personal data from the text and the photo.

## How it works

```
iPhone app -> gateway -> backend: privacy layer -> classification -> research -> draft -> user approves -> dashboard
```

- **Privacy layer** (local models and rules): GLiNER2-PII and fixed patterns for text, YuNet for faces, metadata removed from photos, users stored only as hashed pseudonyms.
- **One Claude model (Haiku) at three points**: classification, authority research (the only real agent, with web search) and drafting. All three can be replaced by rule-based stand-ins that need no API key.
- **Fixed flow** as a LangGraph graph: emergencies stop with a hint to call 110 / 112, unclear photos trigger a question to the user.

Details and the reasons behind each decision: [DOCUMENTATION.md](DOCUMENTATION.md).

## Repository layout

| Folder | Content |
|---|---|
| [`backend/`](backend) | FastAPI backend: privacy, classification, research, drafting, LangGraph flow, cases, API, tests |
| [`backend/dashboard/`](backend/dashboard) | Public dashboard (plain HTML, CSS and JavaScript, no build step) |
| [`services/gateway/`](services/gateway) | Connector gateway: entrance for new reports ([README](services/gateway/README.md)) |
| [`ios/`](ios) | SwiftUI app (Xcode project) |
| [`deploy/`](deploy) | Production setup: Docker Compose, Caddy, scripts |
| [`docs/`](docs) | OpenAPI spec of the app request (`api/openapi.json`) |

## Run it locally

Requirements: Python 3.12, Docker, and (for the app) Xcode with iOS 26.

```bash
cd backend
cp .env.example .env
```

Fill in `backend/.env`. The three secrets and the API key are random strings:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

`PSEUDONYM_SECRET` and `AUTH_SECRET` are required, the API does not start without them. `GATEWAY_KEY` is needed for the
gateway to hand reports over, `API_KEY` only shows the details on `/health`. Use one random value each. The other values
in the file already match the local Docker stack.

Start the stack (PostgreSQL, S3 stand-in, backend, gateway, Caddy):

```bash
docker compose up --build
```

The backend answers on <http://127.0.0.1:8000> (try `/health`), the dashboard is at `/dashboard`.

**No API key needed.** By default classification uses a rule-based stand-in, research is off and the draft is a fixed
German template. To use Claude, set `ANTHROPIC_KEY` and the providers `CLASSIFICATION_PROVIDER=anthropic`,
`RESEARCH_PROVIDER=anthropic` and `DRAFT_PROVIDER=anthropic` in `backend/.env`. The models are chosen with
`ANTHROPIC_CLASSIFICATION_MODEL`, `ANTHROPIC_RESEARCH_MODEL` and `ANTHROPIC_DRAFT_MODEL`.

**Models.** The GLiNER2 model is downloaded from Hugging Face on first use (the Docker image already contains it), so the
first start needs internet. YuNet is in `backend/assets/`.

**Map.** The dashboard map needs a `*.pmtiles` file in `tiles/` (not in git because of its size, see `tiles/` in
`.gitignore`). Without the folder the backend still serves the dashboard page, but not the map file.

## Tests

```bash
cd backend
make install
make test
```

`make install` creates `backend/.venv` and installs the CPU build of torch, so it takes a few minutes. `make test` runs
the backend tests (587 at the last run, about 10 seconds). Tests that need the Docker stack run with
`make test-integration`.

```bash
cd backend && node --test tests/dashboard_*.test.js
cd services/gateway && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q
```

The app tests run in Xcode (scheme `Ortsbild`, tests in `ios/OrtsbildTests`). The gateway has a GitHub Actions workflow
([`.github/workflows/gateway.yml`](.github/workflows/gateway.yml)).

## Project rules

The codebase is written in English, including comments, identifiers, commit messages and file names. Only user-facing
UI texts (labels, buttons, chat messages) are German for now. Everything open, provisional, mocked or unfinished is
marked with a `TODO: <what is missing>` comment directly at that spot. Nothing is left open silently.

## Licenses

Third-party models and their licenses: [backend/MODEL_NOTICES.md](backend/MODEL_NOTICES.md). `make notices` generates
the list of package licenses.
