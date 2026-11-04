# Plan: everything that is still open

Status: 2026-10-29. Sorted by what blocks what. Effort: S = under an hour, M = a few hours, L = a day or more.
Owner: **You** = needs your accounts or your decision, **Claude** = can be built here, **Team** = needs the team or an expert.

The backend runs on the IONOS Cube and passed a first end-to-end test (text, single face, crowd photo).
What is missing for a real test on an iPhone is the connection of the app and HTTPS.

## The critical path to the first iPhone test

```
Phase 0 housekeeping ──► Phase 1 domain and HTTPS ──► Phase 2 connect the app ──► iPhone test
                                                                      │
                              Phase 3 safety net for faces ◄──────────┘ (runs in parallel)
                                                                      ▼
                       Phase 4 hardening and legal ──► TestFlight with fellow students
                                                                      ▼
                                 Phase 5 the rest of the product (agents 3 to 7)
```

## Phase 0: Housekeeping (today)

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| 0.1 | ~~Rotate the leaked Supabase secret key~~ **Done**: the Supabase project is deleted, the key is dead | You | S | done |
| 0.2 | Cost control at IONOS: set a Cost Alert, check *Cost & Usage*, send the support question (trial credit, suspend, full version) | You | S | alert set, answer received |
| 0.3 | Check the swap on the server (`swapon --show`) and measure the memory (`docker stats`) to decide Basic S or M | You, Claude | S | numbers written into the documentation |
| 0.4 | Delete the debug images on the desktop | You | S | files gone |
| 0.5 | Open the pull request `vibe` to `main` (or merge) and agree with the team how to work with the branches | You, Team | S | PR open or merged |

## Phase 1: Domain and HTTPS (blocks the iPhone test)

iOS refuses plain HTTP, and until then photos and the API key travel unencrypted.

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| 1.1 | ~~A hostname for the Cube~~ **Done:** `217-154-175-68.sslip.io`. (Options were: Options: **free** hostname that points to the IP (for example `217-154-175-68.sslip.io`, no signup, works at once), a free named one (DuckDNS), or a **real domain** (a few euros a year, better for real operation). Point it to `217.154.175.68`) | You | S | done |
| 1.2 | ~~Put the name into `SITE_ADDRESS`, restart Caddy, check the certificate~~ **Done** | Claude | S | `https://217-154-175-68.sslip.io/health` shows ok (certificate until 2027-02-02) |
| 1.3 | ~~Create a **new** API key and swap it~~ **Done** (old key gives 401, new one is accepted) | Claude | S | done |
| 1.4 | ~~Restrict `/health`~~ **Done** (strangers see only the status, details need the key, checks are cached for 15 seconds) | Claude | S | done |
| 1.5 | ~~HTTP redirects to HTTPS~~ **Done** (Caddy answers 308) | Claude | S | done |

## Phase 2: Connect the app (the iPhone test)

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| 2.1 | `BackendReportService` in the app (multipart upload to `POST /reports`, the `ReportService` protocol already exists) | Claude | M | the app talks to the server |
| 2.2 | Ask for the location (`NSLocationWhenInUseUsageDescription`), it is mandatory in the report | Claude | S | coordinates are sent |
| 2.3 | Convert the photo to JPEG before the upload (also settles the HEIC license question) | Claude | S | server receives JPEG |
| 2.4 | A stable device id (random id in the Keychain) as `device_id` | Claude | S | same id after restart |
| 2.5 | Base URL and API key as a local setting that is not in git | Claude | S | no key in the repository |
| 2.6 | Show the answer in the chat: sanitized text, the cleaned photo, the line "Daten anonymisiert"; handle `blocked` and `rejected` with a clear German message | Claude | M | the three outcomes look right |
| 2.7 | Install on your iPhone (Xcode, signing with your Apple ID) and test with a photo and a text | You | M | you see the sanitized result in the chat |

## Phase 3: Safety net for faces and text in photos (parallel to phase 2)

The face detector misses faces that are cut off, turned away or tiny (seen on the crowd test).

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| 3.1 | Apple Vision on the device: warn before the upload if faces are visible, ask for a new photo | Claude | M | warning appears |
| 3.2 | Photo tips as an overlay in the camera view, hint after a rejected photo | Claude | S | overlay visible |
| 3.3 | Evaluation set: 20 to 30 realistic German cases (text with names, addresses, plates, photos with and without people) and a script that measures the hit rate | Claude, You | M | table with numbers in the documentation |
| 3.4 | Spike with a stronger server model (EgoBlur: fill the license form, measure time and hit rate on the evaluation set) | You, Claude | M | decision: keep YuNet only, or add a second detector |
| 3.5 | License plates in photos: decide between OCR only and a dedicated detector, based on 3.3 | Claude, Team | M | decision in the decision log |
| 3.6 | Cover only the personal word in photo text (word boxes instead of line boxes) | Claude | M | only the word is black |
| 3.7 | Decide which addresses in a text are the defect and which are private (model-assisted step on sanitized text only) | Claude, Team | L | rule and tests |

## Phase 4: Hardening and legal (before TestFlight with other people)

| # | What | Owner | Effort | Done when |
|---|---|---|---|---|
| 4.1 | Consent screen at first start, privacy notice with a URL, rules for testers (no people, no children, no private property) | Claude, Team | M | in the app and in TestFlight |
| 4.2 | Deletion concept: how long clean photos and pseudonyms are kept, backups, a delete button in the app | Team, Claude | M | written down and built |
| 4.3 | DPA (AVV) with IONOS, data protection sign-off by an expert: pseudonyms as personal data, plates, training data of YuNet and GLiNER2-PII, movement profile by many exact locations | Team | L | signed or answered |
| 4.4 | **Sign in with Apple** instead of the shared API key (decided 2026-11-04, developer membership exists, the capability is already in the Xcode project). Steps: 4.4a verify the Apple identity token (**done**, `backend/auth/apple.py`), 4.4b our own session tokens (short access token, refresh token with rotation in the database), 4.4c `POST /auth/apple` and the check on the report endpoints, 4.4d identifier type `apple_sub` in the data model, 4.4e the app side (button, Keychain), 4.4f delete the account in the app and revoke the token at Apple (App Store rule), 4.4g a limit of requests per user | Claude | L | a stolen key alone is not enough, every user has an own revocable session |
| 4.5 | Least privilege: own database user, a restricted storage key with a bucket policy instead of the admin key | You, Claude | M | no admin rights in production |
| 4.6 | Backups of PostgreSQL (dump to the object storage), a test of restoring | Claude | M | restore proven |
| 4.7 | Monitoring: uptime check on `/health`, the log to a safe place with alerts | Claude, You | M | alert reaches you |
| 4.8 | Operator view of blocked reports (list, retry, discard) | Claude | M | an endpoint and a simple page |
| 4.9 | ~~Remove the Supabase code~~ **Done.** Still to do: test the local compose stack with Docker Desktop | You | S | `make test-integration` runs against the local stack |
| 4.10 | Pin the dependency versions, tests in GitHub Actions on every push | Claude | M | green badge |
| 4.11 | Decide: stay on the Cube, or move to a managed PostgreSQL, revisit STACKIT | Team | M | decision |

## Phase 5: The rest of the product (agents 3 to 7)

Waits for the architecture overview of the team.

| # | What | Owner | Effort |
|---|---|---|---|
| 5.1 | Architecture overview of the team replaces section 3 of the documentation, order and scope of agents 3 to 7 | Team | M |
| 5.2 | Agent 1: classification of the sanitized report (category, lane, emergency) with the model provider chosen for it | Claude, Team | L |
| 5.3 | Choose the model provider for the agents after the privacy layer (EU API, DPA, endpoint hard-wired) | Team | M |
| 5.4 | Research agent (responsible authority and channel), drafting agent, policy code with levels | Claude, Team | L |
| 5.5 | Duplicate check by location (PostGIS image instead of the plain Postgres) | Claude | M |
| 5.6 | Approval pause (interrupt) and the actions approve, revise, wrong authority, close | Claude | L |
| 5.7 | Outbound connectors (Open311, email, web form), simulated sending first | Claude | L |
| 5.8 | Email connector as second input: extract the place from the text, attachments, lowercase the mime type | Claude | L |
| 5.9 | Categories fixed or configurable per municipality, example municipality | Team | M |
| 5.10 | Authority dashboard (a web view, for example on Vercel) | Claude, Team | L |
| 5.11 | Check the name (App Store, domain) | You | S |
| 5.12 | Open question: may the authority contact the reporter? (decides whether the identifier must be stored encrypted) | Team | M |

## Before the backend is handed to a third party (only then)

See [model-license.md](model-license.md): `make notices`, license texts, remove `libx265`, no MinIO, source offers for the LGPL parts, legal view on the training data.

## The next three actions

1. **You:** 0.1 and 0.2 (secret rotation and cost alert), they take minutes.
2. **You:** 1.1, get a domain. Everything after it depends on it.
3. **Claude:** 2.1 to 2.6 (the app connection) while the domain is being set up, so the iPhone test can start as soon as HTTPS runs.
