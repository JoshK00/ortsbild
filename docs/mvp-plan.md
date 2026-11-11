# Plan: the MVP for the university presentation

Status: 2026-11-09. Written while the user was away, so it says what was decided without asking and what only the user can do.
Owner: **You** = needs your accounts, your money or your decision. **Claude** = built here without asking. Effort: S = under an hour, M = a few hours, L = a day or more.
The older lists are [plan.md](plan.md) (everything that is open) and [dashboard-plan.md](dashboard-plan.md) (the dashboard).

## 1. Where we stand

Works end to end and runs on the Cube (state of 2026-11-04, commit `81f440f`): photo and location in the iOS app, Sign in with Apple, the privacy layer on our own server (faces with YuNet, personal data in text), classification and drafting with Claude Haiku, research of the authority for any place with verification, the question when the picture is unclear, one chat per report, the draft with contact, share button.

Built on the branch `dashboard` and **not committed, not deployed**: the dashboard with a vector map from our own server (Stuttgart), the priority with explanation, icons and colours per category, photo placeholder, the public endpoint for the team's test accounts.

## 2. What the presentation needs

The user's goal: an app that takes the pictures, a solid privacy processing, and then the voting (duplicates raise the priority).

| Block | State | What is missing for the presentation |
|---|---|---|
| App takes pictures, sends them, shows the result | works, tested on a real iPhone | tips overlay in the camera view, a warning before the upload when a face is visible, the answer when the app is closed during processing |
| **Privacy of photos** | works, but the face detector misses small, turned and cut off faces; no plate detector (OCR is off) | **a stronger face layer (section 3)**, a measured face evaluation set, then a number to show |
| Privacy of text | works (GLiNER2-PII plus patterns), measured on a few examples | an evaluation with German examples |
| **Voting / duplicates** | not built | section 4 |
| Classification, research, draft | work | more photo cases, research measured on about 15 German towns |
| Dashboard | built locally | deploy, `DEMO_REPORTER_IDS`, the map file on the server, the SQL checked on the real database |
| Legal | open | data processing agreement with IONOS and Anthropic (EU against US provider), legal view on the training data of YuNet and GLiNER2. Say it as open, do not hide it. |
| Presentation | handout and talk notes exist | a backup: a screen recording of the whole flow, in case the network or the server fails |

## 3. Faces: a stronger layer, and does the server carry it?

**Findings from our own tests (docs, 2026-10-29):** YuNet (227 KB, MIT) finds many small faces but misses a large face cut off at the edge and a face looking down, and it draws boxes on pavement. A different threshold does not fix the misses. The 2026-11-04 iPhone test showed a false box on a concrete wall.

**Options, and what is known about them (licenses from `docs/model-license.md`, not legal advice):**

| Option | Strength | Licence and cost | Server load |
|---|---|---|---|
| Tune YuNet (more scales, upscaled copies for small faces, mirrored image) | cheap, quick | MIT, nothing new | a few hundred ms more per photo |
| ~~Apple Vision on the iPhone~~ | **Dropped 2026-11-11:** the connector gateway has channels without a phone, so the privacy layer stays on the server | | |
| MediaPipe BlazeFace | made for close frontal faces | Apache 2.0 | small, but lower recall far away |
| EgoBlur (Meta) | made for exactly this, strong | Apache 2.0 according to its README, **weights only after a form and a licence agreement aimed at researchers** | two models of about 400 MB each plus torch |
| SCRFD, RetinaFace (insightface) | strong | **pretrained weights are research only** | not allowed for us |
| YOLO face models | strong | **AGPL** | not allowed for us |

**Update 2026-11-10 (decision of the team):** the user releases the report at the end and so also the cleaned photo, and can delete it (`DELETE /v1/reports/{id}/photo`, full screen check in the app). The detectors stay the first layer and are still measured, but the plan below no longer needs a perfect result and step 6 (preview) is the release step itself. Said openly: other people in the photo did not agree, and a small face is easy to overlook.

**Decision of 2026-11-11 (team): no model on the phone, a stronger model on the server.** See section 3a for the candidates and what each one needs.

**Decision (taken without asking, reversible):**
1. First measure. Build a small evaluation set of photos with faces (public photos with a free licence, boxes drawn by hand) and write down the recall of YuNet as it is.
2. Tune YuNet and measure again. Keep a change only if the recall goes up and the false boxes stay low.
3. ~~Add Apple Vision on the iPhone as a second layer~~ **Dropped (2026-11-11).** The faces are covered on the server only. A stronger server model and a second server detector take its place (section 3a).
4. Only if the numbers still show misses that matter: apply for EgoBlur (needs you, a form) and test it. Then the server size matters.

**Does it work with the current hosting?** The Cube Basic S has 2 vCPU and 4 GB RAM plus 2 GB swap. Nobody has measured the real memory of the running stack yet (open since plan item 0.3). My estimate, not a measurement: the backend with torch and GLiNER2 needs roughly 2 to 3 GB, PostgreSQL and Caddy a few hundred MB. That fits YuNet (tiny) and the Vision layer (on the phone). **EgoBlur would not fit** next to that: two models of about 400 MB each and torch for a 12 MP photo would push it over 4 GB.
- **If we only tune YuNet and add a small second detector: no upgrade needed.**
- **If EgoBlur is needed: the next size (8 GB RAM, 4 vCPU) is the sensible step.** Do not buy it before the measurement and before the EgoBlur weights are granted, both can fail.
- **Measured 2026-11-10 (after the deploy, idle, models loaded):** the backend container 2.3 GiB of 3.77 GiB, Postgres 23 MiB, Caddy 12 MiB, the server 2.4 GB used and 184 MB swap. So about 1.4 GB are free for a photo in processing. Still not measured: the peak during a real report with a photo. Another model of 400 MB or more would not fit comfortably.
- The measurement itself is one command on the server: `docker stats --no-stream` while a photo is processed. I did not run it, the user decides when to touch the production server.

## 3a. The stronger face model on the server (decision of 2026-11-11)

The team decided: no model on the phone (the connector gateway has channels without a phone), a stronger model on the server. What was found out on 2026-11-11 (pages of the project, read that day, not legal advice):

| Candidate | Licence | Strength | Server cost | Verdict |
|---|---|---|---|---|
| **EgoBlur Gen 2 (Meta), face and license plate detector** | Apache 2.0 for the Gen 2 models (research and commercial use), the weights are downloaded from **projectaria.com/tools/egoblur** (the page asks for an email address; per the team nothing has to be signed, the page only links to the Apache licence; the page says that accessing the models means agreeing to that licence). The agreement page (read 2026-11-11) is the plain Apache 2.0 text, with no research-only and no non-commercial clause, and the project page says Gen 2 is available for research and commercial use. The sentence "if you are a researcher" is an invitation next to the form, not a licence condition. Gen 1 terms are not stated on the page, use only Gen 2. Not a legal opinion | made for blurring faces and plates, Faster R-CNN with a ResNeXt backbone, about 104 million parameters, no accuracy numbers published, tuned on Aria glasses data (Gen 2) | about 400 MB per model, about 1.5 s on the CPU for a 2 MP photo, needs torch (the backend has it for GLiNER2) | **Chosen.** It also gives the plate detector that is missing today. One open question: Gen 2 was tuned on egocentric camera data, so it must be measured on phone photos |
| YuNet (now) | MIT | small, finds many small faces, misses cut off and looking down | tiny | stays as the first, fast detector |
| MediaPipe BlazeFace (Apache 2.0) | Apache 2.0 | made for close faces, weaker far away | small | possible second detector, only if the measurement shows it adds recall |
| SCRFD, RetinaFace weights | research only | strong | medium | not allowed for us |
| YOLO face models | AGPL (a checkpoint may claim Apache, the code base is AGPL) | about as good as YuNet on the hard set | small | not allowed, unclear provenance |

**The plan (changed by the team on 2026-11-11): EgoBlur replaces YuNet, no union.** YuNet is deleted in the same change that brings EgoBlur in, so the privacy layer never runs without a working detector (it fails closed: no detector, no photo). EgoBlur also covers plates. Condition before YuNet goes: EgoBlur finds at least as many faces as YuNet on the test photos. Memory: YuNet is 227 KB, so deleting it saves nothing, the memory cost is EgoBlur (about 400 MB per model). The detector sits behind the same interface as YuNet (`FaceDetector`), switched by an environment variable, so the weights can be exchanged and the app does not change.

**What blocks it, and who has to do it:**
1. **You:** download the Gen 2 weights (face and license plate) on projectaria.com/tools/egoblur (the page asks for an email address and says it sends emails about the model; nothing is signed, the licence is Apache 2.0). Download the two `.jit` files and put them into `backend/models-private/` (git-ignored). **Do not commit the weights.**
2. **You:** the server. 2.3 GiB of 3.77 GiB are used when idle (measured 2026-11-10), one 400 MB model plus torch activations for a photo may fit, **two models do not**. Plan the next Cube size with 8 GB RAM and 4 vCPU before EgoBlur goes live (price at IONOS, not checked here).
3. **Claude, as soon as the weights are there:** the adapter `EgoBlurDetector`. What is known from `gen2/script/predictor.py` of the EgoBlur repository (Apache 2.0, read 2026-11-11): the `.jit` file is a scripted Detectron2 model, it is called as `model.inference([{"image": uint8 BGR tensor C x H x W}], do_postprocess=False)`, resized by the shortest edge (`min_size_test`, `max_size_test`), the result is scripted `Instances` (`pred_boxes`, `scores`, `pred_classes`), then NMS from torchvision and a score threshold. It needs `torchvision` (not in the backend yet) and a few small helper classes of the repository (`Instances`, `Boxes`, `detector_postprocess`), which must be copied with their licence notice. The exact shape of the output can only be seen with the weights, so the adapter is written against the real file, tests with a fake, the evaluation with the face photos (still needed: 15 to 20 photos with boxes drawn by hand, `scripts/eval_faces.py`), the measurement of peak memory and time on the Cube, then the decision about the union.

**Changed on 2026-11-11 (team): YuNet stays, EgoBlur is not used for now**; the threshold is 0.7 (`FACE_SCORE_THRESHOLD`) and the safety is three layers: the photo rules before the photo, YuNet, and the user's check at the release. This section stays as the option if the measurement shows misses that matter. Until the weights arrive nothing on the server changes. The adapter is not built before: without the model it could not be tested.

## 4. Voting: duplicates become one case with votes

Goal in the user's words: when the same request is sent twice from the same place, it is recognised as the same problem, and the second report counts as a vote that raises the priority. A broken playground is more relevant than graffiti.

**Decisions taken without asking:**

| Question | Decision | Why |
|---|---|---|
| What is "the same"? | Same category and at most **40 m** apart, the older report is the anchor, a case stays open for **30 days** | GPS on a phone is off by 5 to 20 m. Within 40 m the same defect is almost certain, a pothole 100 m further is another one. Fixed numbers in one place, easy to change. |
| What is a vote? | Every **released** report in the case counts once (the user pressed "Freigeben", since 2026-11-10), so `reports_count` is the number of votes. The same user can add a vote again (it is the user's own repeat, for example "still not fixed"). | The team tests with one account each, so the demo must show the vote. Risk: one user can push a case. The limit of 20 reports per hour per user stays. If it is abused, count one vote per user and day. |
| Where is it computed? | Backend, from the stored reports (no new table): `backend/cases.py`. The dashboard shows one marker per case. | No migration, works with what is in the database, testable. A real `cases` table with PostGIS comes only if the load needs it. |
| What does the user see? | The app tells the user: "This was reported before, your report counts as one more vote (now N)". The report is still stored with its own photo and text. | The user should see that the second report was not lost. |
| Priority | Rules, never a model, with the parts visible. Hazard lane 50, votes 20 (full at 5), age 15 (full at 15 days), **importance of the category 15, graded**: playground equipment 1.0, pothole 0.9, street light 0.8, tree 0.7, litter 0.35, graffiti 0.2, other 0. | Replaces the first yes or no "safety category". Playground above graffiti as asked. The weights can be moved in the dashboard. |

## 5. The work, in order

`[Claude]` is done without asking. `[You]` needs you. Nothing is committed, pushed or deployed by me.

| # | Step | Who | Size | Done when |
|---|---|---|---|---|
| 1 | ~~**Cases and votes in the backend** (`cases.py`: group by category, 40 m, 30 days; tests), dashboard shows one marker per case with the votes, graded category importance in the score~~ **Done** (2026-11-09, 21 tests) | Claude | M | tests green, dashboard shows votes |
| 2 | ~~**Duplicate answer in the API**: the report answer holds `case: {votes, first_reported_at, is_duplicate}`, the app shows the sentence above~~ **Done** (backend 7 tests, app 4 tests; the sentence is in `BackendReportService`) | Claude | M | tests green, app shows it |
| 3 | **Face evaluation set** from free public photos, boxes by hand, an evaluation script with recall and false boxes | Claude | M | **Half done:** six photos and `scripts/eval_faces.py` exist (section 7), the boxes by hand and a recall number are still open |
| 4 | **Tune YuNet**, measure again, keep what helps | Claude | M | **Not done:** without hand-drawn boxes a change cannot be judged. The look at six photos (section 7) showed few misses and many false boxes, so a change must be careful not to lose recall |
| 5 | ~~Apple Vision layer in the app~~ **Built, then removed on 2026-11-11** (decision: privacy stays on the server because of the connector gateway) | Claude | L | removed, 4 tests and the file are gone |
| 6 | Photo tips overlay in the camera view, the answer when the app was closed during processing (`GET /v1/reports/{id}`), "Keins davon" closes the report | Claude | M | tests green |
| 7 | **Deploy** the branch: `DEMO_REPORTER_IDS` in `.env.prod`, the map file `tiles/stuttgart.pmtiles` is sent by `deploy.sh`, run the dashboard SQL once against the real database, then `docker stats` to measure the memory | You (approval), Claude | M | dashboard live, memory numbers written down |
| 8 | Decide about the server size with the numbers of steps 4, 5 and 7 | You | S | decision written down |
| 9 | If needed: apply for EgoBlur (form, licence agreement), then test it | You, then Claude | M | recall measured |
| 10 | Evaluate the research on about 15 German towns, more photo cases for the classification (the team takes the photos) | Claude (API budget), Team | M | percentages in the documentation |
| 11 | A backup of the presentation: a screen recording of the whole flow (phone and dashboard) | You | S | video on the laptop |
| 12 | Legal: agreements with IONOS and Anthropic, the legal view | You, Team | L | answered, or named as open |

| 13 | **Release and dashboard in the app** (2026-11-10): "Freigeben" is stored (`approved_at`, migration `009`), the dashboard shows only released reports, the app has the tab "Karte" (web view), the dashboard has a mobile layout. **Built and tested** (backend 548, app 54, dashboard 23 tests, the SQL against a real PostgreSQL 16). Not seen on a real iPhone, not deployed: `009_approved.sql` must be run on the server first | Claude | L | done, deploy open |

Not for the MVP (kept in [plan.md](plan.md)): real sending to authorities (the dashboard replaces the letters, later a weekly mail), the revise and wrong-authority actions, the two level dashboard (public and authority), the outbox, the connector gateway.

## 6. Risks

- **Faces are never perfect.** The honest statement for the presentation: two layers, measured recall on a small set, crowds are refused, and the user is asked to keep people out of the photo.
- **Votes can be pushed by one user.** Limited by the hourly cap, easy to change to one vote per user and day.
- **The public dashboard shows exact positions and photos.** Only for the team's test accounts (allow list). It must not show real users before the two level design.
- **Nothing here is deployed.** If the server is not updated before the presentation, the dashboard and the votes exist only on the laptop. Step 7 is the one that matters for the day.
- **Memory is unmeasured.** Step 7 gives the numbers.

## 7. Face check of six photos (2026-11-09)

Six free photos from Wikimedia Commons (kept in `backend/eval/faces/`, not in git; the licences are CC BY, CC BY-SA, the authors are named on the Commons pages): Copenhagen street (CC BY-SA 4.0), a merry-go-round in Munich (CC BY-SA 3.0), kids on a swing (CC BY-SA 4.0), a playground ship (CC BY 2.0), a queue of cyclists (CC BY-SA 2.0), a cyclist in New York (CC BY 2.0). Wikimedia answered the next request with an error after these, so no more were fetched.

`PYTHONPATH=. python scripts/eval_faces.py eval/faces` draws the boxes of YuNet (threshold 0.3). I looked at four of the results:

- The faces in the foreground were found everywhere, also a profile (cyclist), a turned head (boy at the merry-go-round) and children on a swing.
- **There are many false boxes at the low threshold:** wheels, a hand, ground, a goat's head, the back of helmets. The crowd photos give 94 and 58 boxes, which the app refuses anyway (more than 10 faces).
- Not found in these photos: nothing that was clearly a face. The known misses (a face cut at the edge, a face looking down, from the crowd test of 2026-10-29) did not show up here, because none of the six has one.

So: this set shows no new weakness, but it also does not prove the recall. It needs hand-drawn boxes and photos with the hard cases (cut off, looking down, covered by a hood or a cap) before a number is shown.

## 8. What the user has to know when back

1. **Nothing is committed, pushed or deployed.** All of the above is in the working tree of the branch `dashboard`. Commit it when you have looked at it.
2. The iOS app has the sentence for duplicates, the release with the photo check and the tab Karte. Test on your iPhone: take a photo, check the photo in full screen, release, open the dashboard (the Apple Vision layer was removed again).
3. Step 7 (deploy) is the one that matters for the day of the presentation. It needs your approval, and then your `reporter_id`.
4. If the server is to be bigger, decide after the memory numbers of step 7, not before.
