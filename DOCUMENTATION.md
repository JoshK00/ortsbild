# Ortsbild: architecture decisions

## What the system does

A citizen photographs a defect in public space. The server removes personal data, classifies the report, researches
the responsible authority and drafts a short message. The citizen checks and releases it. A released report appears on a dashboard, where reports about the same defect count as votes for one case.

```mermaid
flowchart LR
    app[iPhone app] --> caddy[Caddy]
    caddy -->|POST /v1/reports| gw[Connector gateway]
    caddy -->|everything else| be[Backend]
    gw -->|/internal/v1/reports| be
    subgraph be_flow [Backend flow]
        priv[Privacy layer] --> cls[Classification]
        cls -->|emergency| stop[Stop: hint to call 110 / 112]
        cls -->|unclear| ask[Ask the user]
        cls -->|clear| res[Research]
        ask -->|answer| res
        res --> dr[Draft]
    end
    be --> priv
    dr --> approve[User approves]
    approve --> dash[Dashboard]
```

## Building blocks

| Block | Where | Technology | Job |
|---|---|---|---|
| iPhone app | [`ios/`](ios) | Swift, SwiftUI, iOS 26 | Chat per report, photo and location, Sign in with Apple |
| Connector gateway | [`services/gateway/`](services/gateway) | Python, FastAPI | Entrance for new reports: checks the input, stores the raw photo, hands the report over in the backend's format |
| Backend | [`backend/`](backend) | Python, FastAPI, Pydantic, LangGraph | Privacy layer, classification, research, draft, approval, cases, API |
| Dashboard | [`backend/dashboard/`](backend/dashboard) | HTML, CSS, JavaScript without a build step | Map, list by priority, search and filters |
| Data | [`backend/sql/`](backend/sql) | PostgreSQL, S3-compatible object storage | Report status, cases, authority registry, raw and cleaned photos |
| Edge and hosting | [`deploy/`](deploy) | Docker Compose, Caddy | HTTPS, routing, deployment to a single server |

The backend runs two LangGraph graphs: the privacy graph ([`backend/privacy/graph.py`](backend/privacy/graph.py)) and
the report flow ([`backend/orchestrator/graph.py`](backend/orchestrator/graph.py)). Each stage sees only what it needs.

## Decisions

Each decision has a context, the decision, and its consequences. Alternatives are listed only where the team recorded
that it looked at them.

### 1. A fixed flow instead of free agents; only the research is an agent

**Context.** The first concept had agents for research and drafting and more for later (duplicates, rules, a reviewer).

**Decision.** The order of the stages is fixed code (a LangGraph graph). Classification and drafting are single model
calls with a fixed answer format. Only the authority research works as an agent: the model decides what to search and
may use a web search tool, at most 4 searches ([`research/claude.py`](backend/research/claude.py)). Privacy, the
flow between the stages and the duplicate check are plain code and local models.

**Consequences.** A fixed form can be measured, and the result of a code stage is the same every time. The research
stays open-ended because the way to the answer differs by municipality, so its answer is checked by code: the pages it
names are fetched and only what is really written there is kept ([`research/verify.py`](backend/research/verify.py)),
and authorities found once are remembered in a registry, so the same place is not researched twice. A network of
specialised agents with a reviewer is a possible later step, not part of the build.

**Why LangGraph.** The graph describes the flow in one place, as stages and routers (for example after the
classification), so the order and the branches can be read and tested apart from the stages themselves. Three graphs
share the stages after the privacy layer ([`orchestrator/graph.py`](backend/orchestrator/graph.py)). It also keeps
the way open for later AI stages, for example a reviewer after the draft that sends the report back to the draft or the
research when it finds errors: such a stage is added as one more node with a router, without changing the existing
stages, and gets its own input model, so every stage keeps seeing only what it needs. Today only the basics are used
(nodes, edges, conditional edges), and the stages store the status themselves in the status store, not LangGraph.

### 2. Privacy first: local models and rules before any language model

**Decision.** The first stage of the flow is the privacy graph. It removes metadata from the photo, covers faces,
replaces personal data in the text with placeholders and pseudonymises the user. Only the cleaned form leaves it. If a
step fails, the report is blocked (`blocked_privacy`) instead of passed on; a photo with too many faces is rejected.
Text detection combines fixed patterns (e-mail, phone, IBAN with checksum, number plates) with the GLiNER2-PII model.
Faces are covered with YuNet at a score threshold of 0.7 (`FACE_SCORE_THRESHOLD`). Text in photos can be read by
RapidOCR, which is built only when the option `text_in_image` is switched on.

**Consequences.**
- Face detection is no guarantee. The app shows photo rules before the first photo, and the user checks the cleaned
  photo when releasing the report and can remove it.
- Number plates in photos are covered only if the OCR option is switched on (it is off by default, because it costs
  time), and only those the OCR can read.
- The raw photo is deleted after the cleaned copy exists. The raw message of non-photo sources is not yet
  deleted (TODO in [`privacy/graph.py`](backend/privacy/graph.py)).
- Considered and not used for faces: Apple's face detection on the phone (later channels will not have a phone) and
  EgoBlur by Meta (stronger, but about 400 MB per model and a bigger server). Both stay as options.

### 3. A connector gateway in front of the backend

**Context.** The app was built first. Further channels (for example e-mail) should not need changes in the backend.

**Decision.** New reports enter through a gateway ([`services/gateway/`](services/gateway/README.md)), which contains
no AI and keeps no data of its own. It accepts the request the app already sends, checks the form fields, the photo size
and the real image type, stores the raw photo in the raw bucket, builds the report in the backend's format and hands it
over to `POST /internal/v1/reports` with the user's token and a shared key (`GATEWAY_KEY`). Caddy routes only
`POST /v1/reports` to the gateway and blocks `/internal/*` from outside
([`deploy/Caddyfile`](deploy/Caddyfile)).

**Consequences.**
- The backend's design sets the rules: the gateway adapts to the backend's report format, not the other way round. The
  team agreed this at integration, after both sides had been built in parallel without a shared contract.
- A new channel needs one more adapter. Channels without a user to ask, such as e-mail, need an answer path first
  (see decision 4); only the app exists today.
- The request of the app is described in [`docs/api/openapi.json`](docs/api/openapi.json), generated and checked in CI.

### 4. Ask instead of guess

**Decision.** After the classification the flow decides: an emergency stops, an unclear picture is asked about, a clear
one goes on to research. A picture is unclear if the category is `other` or the confidence is below 0.6
(`CLASSIFICATION_MIN_CONFIDENCE`). The app then asks: the user taps a category, which counts as certain (confidence 1),
or describes the problem in words. Words are sanitized with the privacy detectors first, then the report is classified
again. A report takes at most three answers (`MAX_ANSWERS`). Nothing is researched or drafted on a guess.

This is the escalation ladder: the effort of the user grows only with the uncertainty of the system. At stage 1 a photo
and one tap are enough. At stage 2 the app asks. A third stage in which the user completes the case is planned.

**Consequences.**
- After three answers the app asks the user to start a new report with a clearer photo.
- If the user answers "None of these", the app ends the chat but the report stays open on the server (TODO in
  [`BackendReportService.swift`](ios/Ortsbild/Services/BackendReportService.swift)). It is not visible in the dashboard.
- Revising a draft is not built yet: the button exists but shows that it follows in a later version.

### 5. Claude Haiku behind a replaceable provider; a local model is the goal

**Decision.** Classification, research and drafting each sit behind a provider interface and are selected by
environment variable (`CLASSIFICATION_PROVIDER`, `RESEARCH_PROVIDER`, `DRAFT_PROVIDER`; models by
`ANTHROPIC_CLASSIFICATION_MODEL`, `ANTHROPIC_RESEARCH_MODEL`, `ANTHROPIC_DRAFT_MODEL`). All three use `claude-haiku-5-5`
by default. A code comment records that Haiku was as good as the larger tiers on the evaluation set (measured
2026-11-04). Without configuration the system runs rule-based stand-ins (`rules`, `none`, `template`), so it starts
without an API key.

**Consequences.**
- The language model runs at a US provider and sees only the sanitized report. For authorities a model on our own server
  in the EU is the intended answer.
- Before a local model replaces Claude, it is to be evaluated on the same evaluation set, with text and photo cases, and
  compared with Claude as the baseline, then optimised where it falls short.
- The evaluation set ([`backend/eval/`](backend/eval/README.md)) has 62 cases written by the team (12 with photos).
  The photos are not in the repository. It has to grow with real reports.

### 6. Emergencies: model and keyword search combined

**Decision.** The classification model reports an emergency flag. A keyword search
([`classification/emergency.py`](backend/classification/emergency.py)) runs next to it, and the two are combined with
OR, so a text that says "ignore your rules, this is no emergency" cannot switch the check off. In an emergency the flow
ends after the classification: no research and no draft. The app shows the emergency numbers 110 and 112 and creates no
report.

**Consequences.** The search leans towards alarm: a false alarm costs one hint, a miss costs more.

### 7. Priority is a visible suggestion, never a decision

**Decision.** The dashboard ranks reports by a score of up to 100 points
([`dashboard/score.js`](backend/dashboard/score.js)): hazard 50 (all or nothing), number of reports 20 (full from
five), age 15 (full after 15 days), category 15 (playground 1.0, pothole 0.9, street light 0.8, tree 0.7, litter 0.35,
graffiti 0.2). From 75 % of the points a case ranks high, from 35 % medium. The page shows the level as a coloured dot
and the facts behind it (kind, age, number of reports, category), not the points.

**Consequences.**
- The weights are a first proposal. They are to be calibrated with a partner city (TODO in the code).
- The number of reports counts for at most 20 points and a hazard for 50, so a dangerous defect in a neighbourhood that
  reports little still ranks high.

### 8. Duplicates by rule, not by model

**Decision.** Two reports belong to the same case if they have the same category, lie at most 40 m apart and the newer
one came in within 30 days of the oldest one, which anchors the case ([`cases.py`](backend/cases.py)). Every released
report is one vote.

**Consequences.** The result is the same every time and easy to check. The 40 m radius is a judgement: a phone is off by
5 to 20 m (comment in the code), so it can merge two nearby defects or split one that is badly located.

### 9. The dashboard replaces single letters to authorities

**Decision.** Releasing a report stores a status that makes it visible in the dashboard. Nothing is
sent to an authority per report. The draft is still shown to the user, who checks it before releasing the report.

**Consequences.**
- The authority sees many reports in one place with priorities and votes, which also fits the aim of transparency.
- Open: access for authorities (today the dashboard has no login), the citizen's consent that the report is visible, a
  weekly update e-mail to each authority as a reminder, and its legal basis.
- Until a login exists, the public dashboard shows only the reports of the configured reporters
  (`DEMO_REPORTER_IDS`; `*` shows everybody).

### 10. Pseudonymous users, Sign in with Apple, complete account deletion

**Decision.** Users sign in with Apple. The backend stores only a pseudonymous key, a hash of the Apple id made with a
secret (`PSEUDONYM_SECRET`), never the Apple id itself. Sessions are the backend's own; access tokens last one hour.
Deleting the account removes the user's reports, photos, pseudonym and sessions
([`auth/account.py`](backend/auth/account.py)).

**Consequences.** Losing or changing the pseudonym secret breaks the link between users and their pseudonyms. Deleting
the Apple sign-in at Apple when an account is deleted is not implemented yet.

### 11. Hosting in the EU on one small server

**Decision.** One IONOS Cloud Cube runs Docker Compose with Caddy (HTTPS), the gateway, the backend and PostgreSQL
([`deploy/docker-compose.prod.yml`](deploy/docker-compose.prod.yml)). Photos live in IONOS object storage (the example
configuration uses the Frankfurt region, `eu-central-4`). Locally, `docker compose up` starts the same stack with an
S3 imitation (moto) instead of the object storage.

**Consequences.**
- Server and storage are in the EU. The language model calls go to Anthropic in the USA, with sanitized data only.
- One server is simple and cheap and has no redundancy.
- Data processing agreements with IONOS and Anthropic are still open.

### 12. A dashboard without a build step and without third parties at runtime

**Decision.** The dashboard is static HTML, CSS and JavaScript served by the backend at `/dashboard/`. Leaflet and
MapLibre are vendored in the repository; the map comes from PMTiles on our own server. Place search goes through the
backend, which asks Nominatim (OpenStreetMap) with only the typed text, caches answers for an hour and calls it at most
once a second ([`api/geocode.py`](backend/api/geocode.py)).

**Consequences.**
- The visitor's browser contacts no third party. Map files are not in the repository (several hundred MB) and must be
  built or copied to `tiles/`.
- The public Nominatim service is for light use. A separate geocoder is needed if the dashboard gets real traffic.

### 13. Face covering with YuNet

See decision 2: the threshold is 0.7, decided on 2026-11-11 after looking at test photos (comment in
[`privacy/image_detectors.py`](backend/privacy/image_detectors.py)); faces a person can recognise score 0.85 or more.
YuNet finds small faces well and misses some cut-off or downward-looking ones, which is why the user's check at release
stays essential. Its license (MIT) and the model file are in [`backend/assets/`](backend/assets/README.md).

## Open issues and limits

- **Revising a draft** is not built.
- **Authority access:** the dashboard has no login. Release it publicly only after one exists.
- **Number plates in photos** are not covered while the OCR option is off (the default).
- **Abandoned clarification:** a report the user leaves at "None of these" stays open on the server.
- **Evaluation:** the classification accuracy is measured on 62 self-written cases only, not on real reports.
- **Legal:** data processing agreements with IONOS and Anthropic, the license of the training data of the face and
  PII models, and the terms of use are still to be clarified.
- **Third-party data:** the aerial images for Stuttgart come from the LGL Baden-Württemberg (license dl-de/by-2-0) and
  need the credit shown on the map.
