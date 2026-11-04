# Ortsbild: Documentation

Status: 2026-10-27. University group project, MVP

This document is the central project documentation. Sections 1 to 3 come from the original handoff (2026-10-26) and are partly outdated by the changes from the team meeting (section 4). The team's current architecture overview is still to come and will then replace section 3.

---

## 1. App concept

**Idea:** Citizens report defects in public space (litter, graffiti, broken playground equipment, potholes) with a photo. A team of agents classifies the report, researches the responsible authority, writes the report and bundles duplicates into one prioritized collective report. The user does as little as possible: a photo, and when in doubt one click.

**Flow:** Photo + location (once) → anonymization on the device → classification and emergency check → duplicate check → research of responsibility → draft → approval by click → sending (simulated in the prototype).

**Three lanes:**
- **Hazard** (e.g. broken climbing frame): one report is enough, never fully automatic, not public.
- **Nuisance** (e.g. graffiti, litter): approval by other users serves as a sorting criterion later.
- **Emergency** (violence, injured people, fire): only a hint to call 110 / 112, no ticket.

**Escalation ladder** (the user's effort grows only with the agent's uncertainty):
- **Level 0:** photo only, the agent reports on its own (low-risk cases, later)
- **Level 1:** photo + 1 click (approve, revise, wrong authority, close)
- **Level 2:** 1 follow-up question by tap
- **Level 3:** help from the user or an operator

**MVP categories:** litter, graffiti, street light, playground equipment, pothole, tree.

**Later:** pinboard with votes, follow-up with authorities, level 0, validator agent.

**Differentiation:** There are many defect reporters. The difference is the agent that researches responsibility itself, bundles duplicates and decides via level logic when the user has to step in.

---

## 2. Planned tech stack (working draft)

This is the current plan and may be adjusted.

| Layer | Plan | Note |
|---|---|---|
| App | Swift, SwiftUI, native iOS | Camera, location, push, Vision for anonymization |
| Backend | Python, FastAPI, Pydantic | Pydantic as the shared data contract |
| Agents | LangGraph + LangChain (model layer, `create_agent`) | Graph with approval pause (interrupt) |
| Models | Claude for agents and image recognition | GPT / Gemini optional for model comparison |
| Database and storage | PostgreSQL (container on the IONOS Cube, PostGIS planned) and the IONOS S3 object storage | Supabase was dropped on 2026-10-29, see sections 7 and 11 |
| External sources | OSM / Overpass, Nominatim, municipality websites | via `httpx` |
| Tests | `pytest` | 20 to 30 test cases for the evaluation |

**Still open:** authority dashboard (slim web view or mode in the app), backend hosting, example municipality, check the name (App Store, domain).

**Xcode project:** name Ortsbild, SwiftUI, Swift Testing, storage None, no CloudKit, bundle ID `com.joshua-kehrer.ortsbild`.

---

## 3. Architecture

```mermaid
flowchart LR
  A["iPhone app: photo + location, anonymization"] --> B["API (FastAPI)"]
  B --> C["Classification + emergency check (Claude Vision)"]
  C -->|Emergency| N["Hint to call 110 / 112"]
  C --> D["Duplicate check (PostGIS)"]
  D -->|new| R["Research agent"]
  R --> P["Policy code: choose level"]
  P --> E["Drafting agent"]
  E --> F["Approval pause"]
  F -->|Approve| S["Sending (simulated)"]
  F -->|Revise| E
  F -->|Wrong authority| R
```

**Two agents (LangGraph):**
- **Research agent:** determines responsibility and channel with tools (municipality registry, OSM, municipality websites, Open311 check). Returns authority, channel, sources and confidence.
- **Drafting agent:** writes the report (factual, neutral). The system generates the factual part, user additions are kept separate.

**Policy code:** a normal function without a model. It chooses the level based on classification, research confidence and channel status. The thresholds are configurable so that autonomy can be measured against error rate.

**Data (PostgreSQL and S3 object storage at IONOS):** reports, clusters, status, municipality registry, drafts and checkpoints in Postgres, photos in storage. The status lives in its own table: `received → classified → researching → draft_ready → approved → sent → closed`.

**Data models (Pydantic, mirrored as Swift `Codable`):**

```python
class Classification(BaseModel):
    category: Literal["litter","graffiti","street_light","playground_equipment","pothole","tree","other"]
    lane: Literal["hazard","nuisance"]
    emergency: bool
    confidence: float          # 0 to 1

class ResearchResult(BaseModel):
    authority: str | None
    channel: dict | None       # type: open311 | email | web_form, target, verified
    sources: list[str]
    confidence: float

class Draft(BaseModel):
    subject: str
    body: str
    user_addendum: str | None
    version: int
```

**API (draft):** `POST /reports` (photo, lat, lon), `GET /reports/{id}`, `GET /reports`, `POST /reports/{id}/actions` (approve, revise, wrong_authority, close).

**Swift structure (start):** `Models/`, `Services/` (`ReportService` protocol + `MockReportService`), `Capture/`, `Privacy/` (Anonymizer, ImageResizer), `Views/`. The app runs against the mock first, the real API follows later.

---

## 4. Changes from the team meeting (2026-10-26)

Status: The team's official architecture overview is still pending. This section records what is known so far.

**Direction: framework instead of just an app.** Ortsbild becomes an intermediary layer between the reporting medium and the authority. The iOS app is an add-on for new users. Existing apps, forms and reporting systems are connected through connectors. All inputs are prepared and processed uniformly before they reach the authority.

- **MVP inputs:** our own app and email. More media later.
- **Connector:** thin adapter that converts the raw data of a source into a uniform input contract (`IncomingReport`). The agents know no source, only this contract.
- **Output:** analogously one adapter per target channel (Open311, email, web form). Not planned yet, but the interface should become visible.
- **`IncomingReport` (draft):** text, attachments (images), optional geodata, source, sender data, reference to the raw data. An email often provides text without a photo and coordinates, the app provides photo and location. Both must be processable.

**Agent team: 6 to 7 agents, each with a very specific task.** The first two are settled:

1. Detect and classify the problem
2. Policy and privacy

The remaining agents are not settled yet. The research and drafting concept from section 3 is a candidate for them.

**Same template per agent:** `state`, `tools`, `prompts`, `graph`, tests. Each agent returns structured output (Pydantic) and plugs in as a node in the overall graph (LangGraph).

---

## 5. Decision: privacy before further processing

The privacy stage runs **before** all other agents, including classification. Raw images and raw texts must never go to an external model provider.

**Why:** With email and third-party systems, data arrives unprotected at the server. Anonymization on the device is then no longer enough. It remains an additional protection layer for the app but is no longer a prerequisite.

**Split of the privacy stage (agent 2):**

1. **Deterministic part in our own backend, no external model call:**
   - Text: patterns and checksums (email, phone, IBAN, license plate), plus a small local NER model for names and addresses (candidates: Presidio, GLiNER).
   - Image: remove EXIF, find faces with the small local detector YuNet (CPU), cover them with black bars (Pillow). Text in images and license plates are optional (OCR plus the text step, see the decision log).
   - Result: sanitized report plus a log of what was removed.
2. **Model-assisted part, only with sanitized material:** decisions that need context, e.g. whether an address is the defect location or a private address.

**Gateway and raw data:** The connector gateway receives raw data and processes it inside our own backend. For geocoding it sends only the extracted address to the external geocoder, without sender, user identifier or other text, so nothing links the address to a user. A report without a location is not forwarded (the location is mandatory in `IncomingReport`).

**Rejected:**
- A vision language model for finding faces and license plates. That would require sending the raw image to the model provider.
- Self-hosted large models (e.g. Mistral Small 24B via Ollama). They scale poorly and add operational effort. Small detectors in the backend do not have this problem.

**Model layer:** One configuration entry per agent (provider, model, endpoint). A European API is planned for agents after the privacy stage (candidate: Mistral, EU endpoint only, hard-wired in the configuration, never the global default). The provider stays interchangeable until the team has decided.

**Known limits:**
- Crowd test (2026-10-29, a public photo of a crowd): YuNet found the many small faces in the background, but missed a large face cut off at the image edge and a face looking down, and it drew two large boxes on the pavement and an arm. A different threshold does not fix the misses. Answer: reject crowds, ask the user to keep people out of the photo, plan a second layer (Apple Vision on the device, a stronger server model such as EgoBlur, not tested).
- No detector finds everything (faces turned away, name tags, house numbers, handwriting). Measure the hit rate with real examples and document it.
- Addresses are the weakest class for NER models.
- The result is usually pseudonymization, not full anonymization in the GDPR sense.
- Whether small detectors work well enough on photos of potholes, graffiti and litter is untested.

**Text detector: why GLiNER2-PII (decision 2026-10-28, open to revision after an evaluation)**

Model `fastino/gliner2-privacy-filter-PII-multi` (GLiNER2-PII, May 2026), Python package `gliner2`. The first candidate was `urchade/gliner_multi_pii-v1` (April 2024), which is outdated.

Why this one:
- Small (about 205M parameters), runs on the CPU inside our own backend, no external call. It fits the decision against self-hosted large models.
- German is one of 7 supported languages. It knows 42 entity types, including person, street address, email, phone number, license number and IBAN, so one model covers most of the text step.
- Labels are passed at inference time (zero-shot), new kinds need no retraining.
- License Apache 2.0.
- In the vendor's paper it has the best recall of the compared GLiNER detectors (average 0.718) and the best overall F1 on the SPY benchmark. The old candidate has higher precision but the lowest recall. For us a missed name is worse than a redacted word too many.

Caveats, to be kept in mind:
- The benchmark comes from the vendor itself, is mostly English (legal and medical texts) and all scores are low. It says little about German reports.
- Low precision (0.35 to 0.37): it over-predicts names, sometimes labeling common nouns, organizations or product names as persons. Over-redaction is acceptable for us, but it can blur useful words.
- Trained on synthetic data without human review.
- There is no label for organizations. License plates are covered by `license_number`, not verified for German plates.
- Cost: installing `gliner2` needs `torch` and `transformers` (virtual environment about 1 GB). The first load downloads the model (took about 3.7 minutes here), later calls are fast (about 0.07 s for one report text on the CPU).

Smoke test (one German example, not an evaluation): person, street address, email, phone number and license plate were all found with confidence 0.88 or higher.

TODO: Build a small evaluation set of German reports (email with names, defect address, plates, phone in the signature) and compare against `urchade/gliner_multi_pii-v1` and a plain pattern baseline.

**A detector alone is not the safeguard.** No detector anonymizes reliably, a small model even less. Therefore the privacy layer never relies on one model: patterns with checksums for structured data (email, phone, IBAN) run in addition, low confidence leads to blocking (fail closed), over-redaction is preferred, the redaction log makes every run auditable, and the detector sits behind an interface so it can be replaced. What remains is a residual risk that must be covered legally (pseudonymization, DPAs with the hoster and model providers, EU hosting, data protection sign-off, see section 6).

---

## 6. Legal assessment (state of the discussion, not legal advice)

These points must be signed off by a person with data protection expertise before real citizen data is used, e.g. the university's data protection officer.

- **Controllers** are the operators of the framework (or the authority on its behalf), not the users. The operators conclude the data processing agreement (DPA, German: AVV) with their service providers.
- **Processors:** hoster and storage (IONOS), model provider. A DPA is needed with each.
- **Photographed third parties** do not sign a DPA. A legal basis is needed (typically legitimate interest, Art. 6(1)(f) GDPR, possibly (e) when acting for an authority), plus transparency and data minimization.
- **Users:** Responsibility should lie with the operator, not the user. Relevant for photos are the right to one's own image (KUG §§ 22, 23, 33) and § 201a StGB. The gray area around the user's co-responsibility is open.
- **Mistral (candidate):** according to third-party sources EU endpoint `api.eu.mistral.ai`, DPA for business customers, no training on API data, 30-day retention by default, zero data retention only in certain plans and only for stateless calls. Must be verified against the official documentation.

---

## 7. Hosting

Local is enough for development. As soon as real data flows (at the latest from TestFlight, see section 8):

- Location in the EU (candidates: Hetzner, IONOS, OVH, Scaleway or the EU region of a hyperscaler). With US companies a residual risk remains because of US law.
- DPA with the hoster.
- IONOS: the Cube and the object storage are in Germany (Frankfurt), conclude a DPA with IONOS.
- Build the backend in a container (Docker), do not hard-wire hoster-specific services, so the hoster stays replaceable.
- Deletion concept: delete raw data after sanitization, no unintended backups containing raw data.

**Decision (2026-10-29): move to IONOS (Germany) for the MVP**, for storage, database and the container of the backend. Supabase was dropped afterwards (project deleted, code and SQL removed).

Why IONOS and not STACKIT, Google Cloud, Supabase or Vercel:
- Self-service with a trial account (200 USD credit for 30 days for object storage, payment details needed). STACKIT is, according to one source, only available to companies, its startup program needs an EU company. A student group is not one.
- Cost: object storage about 0.007 EUR per GB and month. Managed PostgreSQL costs noticeably at both providers (STACKIT about 142 to 206 EUR per month, IONOS roughly 50 EUR for a small instance, check the price list). For the MVP PostgreSQL runs as a container next to the backend, a managed instance with backups comes before real operation.
- PostgreSQL with PostGIS (needed for the duplicate check), S3-compatible object storage and managed Kubernetes are available.
- A German provider is not subject to US access law (the CLOUD Act risk that applies to Google Cloud, Vercel and, as far as we know, to Supabase through its US parent and cloud provider). A DPA with one provider is enough.
- STACKIT is better in certification (BSI C5 Type 2 vs Type 1) and tooling (CLI, API-first). Worth a second look before real operation with authorities. The move would be small because all access sits behind interfaces.
- Vercel (serverless) does not fit the backend: package size, cold start with the models. It would fit the authority dashboard.

Open: whether the trial credit also covers servers and the database, the server size (probably 4 GB RAM, to be measured with the finished container), managed PostgreSQL before real operation.

Code changes (done, untested against the real stack until Docker runs): `S3PhotoStore` (boto3) for every S3-compatible storage, PostgreSQL stores (psycopg) instead of the Supabase API, `Dockerfile` (CPU build of torch, model shipped in the image) and `docker-compose.yml` (backend, PostgreSQL, MinIO as a local S3), health checks for storage and database. No data has to be moved, nothing real is stored in Supabase yet.

---

## 8. Goal: TestFlight for fellow students

As soon as fellow students upload real photos, real personal data flows. Minimum requirements for the closed test:

1. Backend, database and storage in an EU region (IONOS, Germany).
2. DPAs with IONOS and the model provider.
3. Privacy notice in the app (what happens, that sending is simulated). TestFlight requires a privacy URL and test information for external testers.
4. Explicit consent from testers at first launch, with a note about the test status.
5. No real sending to authorities. Sending stays simulated.
6. Deletion concept: delete test data after the test, fixed deadline, delete button in the app.
7. Rules for testers: no photos of recognizable people, no children, no private property.

**Input in the test:** the app only. Image sanitization runs on the device (Apple Vision), the raw image never leaves the phone. Server-side image sanitization (for email and further connectors) can be pushed back. Text sanitization should be included, because users write names in free text.

---

## 9. Open items

The sorted plan with owners, effort and dependencies is in [plan.md](plan.md). This list is the raw collection.

- Wait for the team's architecture overview, then replace section 3.
- Clarify order and scope of agents 3 to 7.
- Categories: do the six MVP categories stay or become configurable per municipality?
- Choose the model provider for agents after the privacy stage.
- Hosting: create the IONOS account, check what the trial credit covers, measure the memory of the container to choose the server size, conclude the DPA with IONOS. Decide when to switch from PostgreSQL in a container to a managed instance with backups. Revisit STACKIT before real operation with authorities.
- Have the legal assessment signed off by an expert (section 6), including pseudonyms as personal data and the license plate question (decision log, 2026-10-29).
- Second layer for faces: Apple Vision on the device before the upload, and/or a stronger server model (spike with EgoBlur). Warn the user in the app before the upload if faces are visible.
- Show the photo tips as an overlay in the camera view of the app, with a hint when a photo was rejected.
- Run `backend/sql/postgres/003_status_rejected.sql` on the server database once (it allows the status `rejected`).
- Test the face detector (YuNet) on realistic photos, in particular small and turned away faces. Decide on a dedicated license plate detector after that test. Optional spike: EgoBlur (needs the model license form).
- Use word boxes instead of line boxes for text in images, so only the personal word is covered.
- Check the license of YuNet's training data (WIDER FACE is research-only) before a production use.
- Test the text detector and the image detectors on realistic German examples (evaluation set).
- Decide which addresses in a text are the defect and which are private (addresses are not redacted for now).
- May the authority contact the reporter? Decides whether the identifier must be stored encrypted, today only its hash is kept.
- Gateway: extract the place from an email text, lowercase the mime type, check that a file really is an image.
- Deletion concept: deadline, raw message (email file) and backups.
- Test the local compose stack with Docker Desktop (`docker compose up --build`, `make test-integration`). Run the backend with its own database user instead of the database owner.
- Build the operator view of blocked reports (the store has `list_blocked`, an endpoint and a way to retry or discard are missing).
- Send the log to a safe central place with alerts (today terminal and `backend/logs/` only).
- Real authentication of the app and a limit of requests per device instead of one shared API key (the key inside the app can be extracted).
- End-to-end test on a real iPhone: API (FastAPI), app connection, location permission (section 10).
- Licenses (section 12): let the app send JPEG instead of HEIC, replace MinIO, ask for a legal view on the training data of YuNet and GLiNER2-PII before real operation, include notices on any delivery.
- Example municipality, check the name (App Store, domain), authority dashboard.

---

## 10. Plan: end-to-end test with the iOS app

Goal: take a photo and write a text on a real iPhone, send both through the privacy layer and get the sanitized report back into the chat as proof ("Daten anonymisiert", cleaned photo and text next to the original).

The app already has the `ReportService` protocol with `MockReportService`, so the app gets a second implementation (`BackendReportService`) and the UI stays.

Backend: the privacy layer is complete (faces, optional text in images, pseudonym, assemble) and the endpoint `POST /reports` exists (done, see the decision log) (photo, text, location, device id) that stores the photo in the bucket `raw`, runs the graph and returns the `SanitizedReport` with the clean photo.
App: ask for the location (mandatory in `IncomingReport`, needs `NSLocationWhenInUseUsageDescription`), `BackendReportService`, an exception for plain HTTP in the local network (App Transport Security) for the test.
Reachability: iPhone and Mac in the same Wi-Fi, no tunnel for real photos (the image would pass a third party).
Test data: own photos only, no recognizable third parties.

---

## 11. Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-26 | Framework with connectors instead of just an app, 6 to 7 agents | Team meeting. Existing apps and forms connect through connectors. |
| 2026-10-27 | Privacy runs before everything else, raw data never goes to an external model provider | Email and third-party sources arrive unprotected. |
| 2026-10-27 | The privacy layer is mostly rules and small local models, not an LLM. Detectors run inside our own backend (CPU, no GPU server) | Self-hosted large models do not scale, small detectors do. |
| 2026-10-27 | Fail closed: if a step fails or is unsure the report is blocked, the raw data stays for the operator | A half-sanitized report must never get through. |
| 2026-10-27 | `location` is mandatory in `IncomingReport`, the gateway rejects reports without one | A report without a place is meaningless. |
| 2026-10-27 | The gateway receives raw data inside our backend. The external geocoder only gets the extracted address, without sender or other text | Nothing may link the address to a user. |
| 2026-10-27 | Strict data contracts: one base class with strict types, no unknown fields, frozen objects. Raw `IncomingReport` and `SanitizedReport` are separate types, the latter has no user field | The type system enforces that no plain identifier survives the privacy layer. |
| 2026-10-27 | The location is NOT coarsened, it passes unchanged | It is the location of the defect, the authority needs it exactly. The reporter is protected by the pseudonym. Open: many exact locations of one pseudonym could form a movement profile (sign-off). |
| 2026-10-28 | Text detector GLiNER2-PII plus patterns with checksums | See section 5. |
| 2026-10-28 | Addresses in text are not redacted by default | The street in a report is often the defect location. Needs the model-assisted step to tell them apart. |
| 2026-10-28 | Photos live in Supabase Storage, buckets `raw` and `clean`, both private. A reference has the form `<bucket>/<path>` | Raw photos need stricter protection and are deleted after sanitizing. Access goes through a `PhotoStore` interface (in-memory variant for tests). |
| 2026-10-28 | HEIC/HEIF photos are accepted and converted to JPEG while EXIF is stripped | Most photos from the iOS app are HEIC. Later steps then see one format. |
| 2026-10-28 | Steps only run when their input exists, a router in the graph picks the next step that applies | No face detection on a report without photos, no text detector without text. |
| 2026-10-29 | Pseudonyms: only a keyed hash (HMAC with `PSEUDONYM_SECRET`) of the identifier is stored, in its own table with row level security and no policy (`backend/sql/001_pseudonyms.sql`) | A database leak must not reveal the reporters. Open: contact by the authority would need the identifier stored encrypted. |
| 2026-10-29 | Faces in photos are mandatory to blur. License plates in photos are optional and off by default. License plates in text are always redacted | Faces identify directly. A plate identifies only through the keeper register, so the risk is lower. For some reports (illegal dumping) the plate can be the evidence the authority needs. Detection of plates has no standard model and costs a lot. Rule for testers: no cars with readable plates. Open for sign-off: blur or keep when the plate is the evidence. |
| 2026-10-29 | Faces in photos: YuNet (OpenCV Zoo, MIT, 227 KB) with a low score threshold (0.3), tiles for big photos and a 30 % margin around each box. Measured on an Apple M4 Pro CPU: 5 ms for 640x480, 81 ms for a full 12 MP photo | Recall counts more than precision. Considered and rejected: MediaPipe (made for close frontal faces), SCRFD (pretrained weights are research-only), YOLO face models (AGPL), cloud APIs (raw image would leave our backend). |
| 2026-10-29 | Faces are covered with black bars, not blurred | A blur can partly be undone, a bar cannot. |
| 2026-10-29 | Text in images: RapidOCR (PP-OCRv6 small, Apache 2.0, models ship with the package) reads the text, OUR text step decides what is personal, only those lines are covered. Off by default (`ImageOptions.text_in_image`) | One OCR model covers name tags, notes and readable plates. Not all text is covered because graffiti and street signs are often the defect. OCR costs time, so it is a switch. |
| 2026-10-29 | No dedicated license plate detector for now | The OCR path covers plates that can be read. A dedicated detector finds plates even when they cannot be read, but adds a model. Decide after a test with realistic photos. Candidates (researched, not decided): `open-image-models` YOLOv9-t (about 8 MB, license to check), open-lpr (Apache 2.0, about 20 MB). EgoBlur (Apache 2.0 per its README, but two models of about 400 MB each, weights only after an email form and a license agreement aimed at researchers, built for Aria glasses data) was not tested. |
| 2026-10-29 | Retry only for transient errors of storage and database (network, timeout, 5xx, 429): 3 tries, pause 0.5 s then 1 s. No retry for model or file errors | A short network error must not block a report. A broken image or a detector bug fails the same way again. |
| 2026-10-29 | A blocked report is logged with report id, step and error type, never the error message or traceback | The message can contain raw data. |
| 2026-10-29 | Fail closed blocks on errors, not on "nothing found" and not on low scores | A photo without faces is the normal case. Low-score findings are covered instead of blocked. A miss without an error cannot be detected by the code (residual risk). |
| 2026-10-29 | Technical log: Python logger `ortsbild` to the terminal and to `backend/logs/ortsbild.log` (rotating, 5 MB, 3 old files, not in git). Level from `LOG_LEVEL` | Fast to read for developers. The log does not belong in the database (volume, cost). Later a central log service with alerts once the backend is hosted. |
| 2026-10-29 | Status of every report in a Supabase table `reports` (processing, sanitized, blocked_privacy, with the reason), SQL in `backend/sql/002_reports.sql`, row level security without policy. `process_report` keeps it up to date, also when the graph crashes | The operator must find blocked reports and the status has to survive a restart. The table holds no personal data. |
| 2026-10-29 | `GET /health` (FastAPI): 200 if all models answer and Supabase (buckets, both tables) is reachable, 503 with the failing parts otherwise. The same checks run at startup, the app starts even if one fails | A missing model or table is noticed before the first real report. Only error types and our own safe messages are shown, never secrets. |
| 2026-10-29 | Move storage, database and backend hosting to IONOS (Germany) for the MVP, PostgreSQL first as a container next to the backend | See section 7: self-service access, cost, PostGIS and S3 available, no US parent company. Supabase is dropped after the move. |
| 2026-10-29 | The server (IONOS Cube, Ubuntu 24.04) is set up with `deploy/bootstrap-ubuntu.sh`: update, automatic security updates, user `deploy` with the SSH key only, no root or password login, Docker from the official repository, 2 GB swap, firewall (ufw) and fail2ban. Network: the IONOS security group allows inbound TCP 22, 80 and 443 only | Minimal rights, two firewall layers, no password to guess. The default security group of IONOS blocks all inbound traffic until rules are added. |
| 2026-10-29 | Production stack: Caddy (HTTPS, automatic certificate), backend and PostgreSQL as containers (`deploy/docker-compose.prod.yml`). Neither the backend nor the database publishes a port. Deploy by `deploy/deploy.sh` (rsync from the Mac, the image is built on the server because the Mac is ARM and the Cube x86). `.env.prod` with the secrets lives only on the server, a new `PSEUDONYM_SECRET` is created for it | Only Caddy is reachable from outside. No registry and no git credentials on the server needed. Secrets never travel with the code. |
| 2026-10-29 | IONOS Object Storage for the photos: contract-owned buckets in Frankfurt (`eu-central-4`, endpoint `https://s3.eu-central-4.ionoscloud.com`) or Berlin (`eu-central-3`), signature version 4, bucket names unique across IONOS | The S3 code works with any S3 compatible provider, only the endpoint, region and keys differ. |
| 2026-10-29 | `POST /reports` (multipart: lat, lon, device_id, optional text and photo) is the entry of the app and `GET /reports/{id}/photos/{photo}` returns the sanitized photo. The photo type is detected from the content (JPEG, PNG, HEIC), never from the header the client claims. At most 15 MB, 5000 characters. The answer is the sanitized report or `blocked` without any reason | The gateway rules (image only, location mandatory) are enforced at the border. A blocked report must not tell the client what was found. |
| 2026-10-29 | Every report endpoint needs the header `X-API-Key`. A server without a configured `API_KEY` rejects everything (503). `/health` stays open | The server is public on the internet, without a key anyone could fill our storage. One shared key is not real authentication, it is only protection against drive-by use (TODO in the code). |
| 2026-10-29 | A photo with more than `MAX_FACES` (default 10) faces is **rejected**: status `rejected` (reason `too_many_faces`), raw and clean copies are deleted at once, the app gets only the reason code. Only faces with a score of at least 0.5 count, the weaker boxes are still covered | The face detector misses faces that are turned away, cut off or tiny (seen on a crowd test photo: a large cut-off face at the edge was not found), so a crowd cannot be made safe. A weak box on a texture must not turn a normal street photo into a "crowd". A rejected photo is no case for an operator, nothing is kept. |
| 2026-10-29 | The same face found by the full image pass and the tiles is counted once (overlapping boxes are merged). Boxes completely outside the image are ignored | The log showed 186 faces for one crowd photo, about 130 of them were duplicates. |
| 2026-10-29 | Prevention at the source: the app tells the user to keep people and license plates out of the photo and to take the defect from close by (text in the first chat message, more to come as an overlay in the camera view and a warning with Apple Vision before the upload) | The best protection is data that is never taken (data minimization). It also lowers the load on the detectors. |
| 2026-10-29 | First deployment to the IONOS Cube (plain HTTP on the IP, no domain yet) tested end to end with the real parts: `/health` all ok, no key gives 401, a text with a name, phone number and plate comes back with placeholders, a portrait photo comes back with the whole face covered and the raw photo deleted (only the clean copy is left in the bucket), a crowd photo is rejected with `too_many_faces` and nothing is left in either bucket, the status table shows `sanitized` and `rejected` | Proof that image, models, object storage, database and the status handling work together on the server. Still open: HTTPS with a domain (photos and the API key travel unencrypted until then), the app connection. |
| 2026-10-29 | Supabase is dropped: the project is deleted, its code (`Supabase*Store`, `supabase_checks`), its SQL (`sql/supabase/`) and its tests are removed. The earlier decision rows about Supabase above are history | Not needed after the move to IONOS. The Supabase key that was shown in a chat once is dead with the project. |
| 2026-11-04 | HTTPS on the Cube with the free name `217-154-175-68.sslip.io` (a public service that turns the IP written in the name into that IP). Caddy gets the Let's Encrypt certificate on its own (valid until 2027-02-02, renewed automatically), plain HTTP redirects to HTTPS. Set by `SITE_ADDRESS` in `~/ortsbild/deploy/.env.prod` | iOS and the privacy goal need an encrypted connection and the certificate needs a name. A bought domain is not needed for the MVP. A real domain replaces it later by changing one line on the server and one setting in the app. Risk: the name depends on a third party service and contains the IP. |
| 2026-11-04 | The API key was renewed on the server (the first one had travelled over plain HTTP during the early tests). The old key gets 401, the new one is accepted, the proof was done without printing a key. `/health` shows only `ok` or `degraded` to strangers, the names of the checks and the reasons need the API key. The checks run at most every 15 seconds | The first key had to be treated as known. Right after the certificate was issued, strangers started to probe the server, so the details of `/health` must not be public, and a public endpoint must not make the server call storage and database on every request. |
| 2026-10-29 | The privacy layer stays on LangGraph although it is mostly plain code | Fail closed as a branch, the pause for an operator later, one node type for the overall graph, and the graph can draw itself (`make graph`). |

---

## 12. License review (2026-10-29, not legal advice)

Checked from the model cards and repositories, the license files inside the installed packages and the wheels of the Linux build (the platform of the Docker image). Everything marked "to verify" comes from a secondary source or from general knowledge.

**Hosting is not distributing.** Most open-source duties (license texts, source offers for GPL/LGPL code) start when software is handed to someone. Running it as a service on our own server is not that, the exception is the AGPL. The iOS app contains none of the libraries below (no Swift packages in the project). It becomes relevant if the backend is ever delivered to a third party, for example an authority that hosts it itself.

### Models

| Model | License | What to know | Risk |
|---|---|---|---|
| **GLiNER2-PII** (`fastino/gliner2-privacy-filter-PII-multi`) | Apache 2.0 (model card) | Based on GLiNER2 (code Apache 2.0, the license of its base weights is not stated on the repo page) with a DeBERTa-v3 / mDeBERTa-v3 encoder (MIT according to our knowledge, to verify). Trained on 4,910 synthetic texts generated with GPT-5.4, without human review. The card does not address the terms of use of the generating model. | low to medium (provenance of the training data) |
| **YuNet** (OpenCV Zoo, `face_detection_yunet_2023mar.onnx`) | MIT | Comes from the project libfacedetection.train. The model README does not name the training data. The performance is measured on WIDER FACE. The WIDER FACE dataset is listed as CC BY-NC-ND 4.0 on its Hugging Face card (other sources: academic use only). Whether weights trained on it are a derivative is an unsettled legal question. MIT requires that the copyright notice is kept. | medium (training data), fine for the MVP |
| **PP-OCRv6 small (detection and recognition)** and the text angle classifier `ch_ppocr_mobile_v2.0_cls` via RapidOCR | Apache 2.0 | The license file `MODEL_LICENSES.md` inside the package states Apache 2.0, copyright of the weights with Baidu and the PaddleOCR rights holders, no non-commercial restriction found. | low |

### Libraries and binaries

| Part | License | What to know | Risk |
|---|---|---|---|
| **pillow-heif** (HEIC) | code BSD-3, but the **binary wheel is GPL-2.0 as a whole** | The Linux wheel bundles `libx265` (GPL-2.0), `libheif` and `libde265` (LGPL-3.0). We only decode, but the library is in the image. HEIC is HEVC, which has patent pools (to verify). | **highest**, only if we hand the image to others |
| **OpenCV** (`opencv-python-headless`) | Apache 2.0 | The Linux wheel bundles FFmpeg parts (`libavcodec`, `libswscale`, `libswresample`, LGPL) and no x264/x265. The macOS wheel on the dev machine also bundles GPL codecs, it is never used for a delivery. | low |
| **psycopg** (PostgreSQL driver) | LGPL-3.0 | Used unmodified as a library, fine. License text must be kept on distribution. | low |
| certifi, orjson, tqdm | MPL-2.0 | File-level copyleft, unmodified use is fine. | low |
| torch, transformers, langgraph, pydantic, fastapi, onnxruntime, boto3, huggingface_hub and about 100 more | MIT, BSD, Apache 2.0 | Permissive. License and notice texts have to be included on distribution (`make notices`). | low |
| **MinIO** (local S3 in `docker-compose.yml`) | AGPL-3.0 | The community edition is **archived** since April 2026, no patches. Only used on the dev machine, bound to 127.0.0.1, unmodified. | low for license, medium for security (dev only) |
| Docker base images (python, postgres) | various, standard | Debian packages (GPL/LGPL), PostgreSQL license. Normal for any container. | low |

The open points per model and the checklists are collected in [model-license.md](model-license.md).

### What we have to do

1. **Now, cheap:** keep the licenses and sources next to the model files (`backend/assets/README.md`), cite the YuNet paper, generate the notices with `make notices` before any delivery.
2. **HEIC (before TestFlight):** let the iOS app send JPEG (the app can convert before the upload). Then HEIC is only needed for email attachments. Keep pillow-heif for now because we host only. Before any delivery to a third party: remove `libx265` (build libheif without it, or drop HEIC at the connector).
3. **MinIO:** replace it in `docker-compose.yml` by an Apache-licensed S3 (SeaweedFS) or use the IONOS storage already in development.
4. **YuNet and GLiNER2 provenance:** accepted for the MVP. Before real operation with authorities ask a person with legal expertise (training data of YuNet, terms of use of the generated training data of GLiNER2-PII), or switch to a model with clear terms.
5. **Before any delivery to a third party:** all license texts and notices included, source offers for the LGPL/GPL libraries, MinIO not part of the delivery.
