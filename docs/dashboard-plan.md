# Dashboard: plan

Status: built on the branch `dashboard` (2026-11-09), not merged and not deployed. 516 backend tests and 9 score tests pass. See section 10 for what is checked and what is not.

## 1. Goal and scope

A web page served from our own server. Every report of the team's test accounts is a marker on a map, a list next to it is sorted by priority, and every priority can be explained. It shows the outlook of the project (visible progress, SDG 16 transparency) with real data from our database.

Out of scope: login, real users' reports, writing back a status, duplicate detection (the case concept is not built, see `docs/documentation.md`).

## 2. Decisions

| Decision | Why |
|---|---|
| **The page is served by the Cube itself, under `/dashboard`** | Same address as the API, so no CORS. One deploy with `deploy/deploy.sh`, HTTPS exists, no second repo. GitHub Pages is not used: it only serves files and cannot reach the database. The repo is private, so Pages would also need a paid plan. |
| **A read endpoint `GET /v1/public/cases` with a fixed list of fields** | The browser must never reach the database. The endpoint is the only door and it says exactly what leaves. |
| **Only reports of the team's own accounts are public** | The first endpoint without login must not show reports of real users. Position plus time can identify a person. An allow list of user keys in the environment (`DEMO_REPORTER_IDS`, the `reporter_id` the app shows) decides, checked at read time. No migration, no new column. |
| **Priority is rules, not a model** | Urgency is subjective (discussion of 2026-11-04). A transparent score with visible parts is explainable (competency #5) and the viewer can change the weights. |
| **Fallback with invented data in the same page** | If the server does not answer, or the URL has `?demo`, the page uses `demo-data.js`. It is a JS file and not JSON, so it also works when the page is opened from the laptop (browsers block `fetch` of local files). |

## 3. What is already in the database

Checked on 2026-11-09:

- `reports.sanitized_report` (jsonb) holds `location` unchanged: `lat`, `lon`, `accuracy_m`, `place`. So coordinates exist, no migration needed.
- `reports.classification` (jsonb) holds category, lane, confidence, emergency.
- `reports.research` (jsonb) holds the authority (public information).
- `reports.created_at`, `status`, `user_key` exist.
- Not there: number of bundled reports (no case concept), a status from the authority.

## 4. The endpoint

`GET /v1/public/cases`, no login. Returns a list, newest first, at most 200 entries.

| Field | Content |
|---|---|
| `id` | short hash of the report id, not the id itself |
| `category`, `lane` | from the classification |
| `status` | `received`, `in_progress`, `done`. Until authorities report back: `received` for every report that has a draft |
| `created_at` | timestamp |
| `lat`, `lon`, `accuracy_m` | exactly as stored: the authority needs the precise spot |
| `address` | the place parts of the location (street, number, town) |
| `draft` | the finished message as the app shows it (subject and body, with address, coordinates and map link) |
| `authority` | name from the research, if there is one |

| `text` | the sanitized description (placeholders like `<PHONE>` stay), at most 500 characters |
| `photo_url` | `/v1/public/cases/{id}/photo`, the cleaned photo only |

Never in it: the original photo, the user key, the real report id.

Photo route `GET /v1/public/cases/{id}/photo`: no login, serves the **clean** copy only, and only for a report that the allow list would show (the short id is looked up among the at most 200 visible reports, anything else is 404). Photos are served as they are in the app (`/v1/reports/{id}/photos/{photo_id}`), without the owner check.

The protection is the allow list, not the field list. Photos and text have passed the privacy layer, but the layer is good and not perfect (measured misses: a cut-off face, a face looking down, names the text detector does not know). The location is exact and the address is in it, because an authority cannot act on less. Together with the photo this tells where a person was. With the team's own accounts this is acceptable, with real users it is not: a page without login must never show exact data of strangers. Before real reports go on a dashboard, the two levels of section 9 are needed.

Rules: only reports whose `user_key` starts with a reporter id of `DEMO_REPORTER_IDS`; only status `classified`, `researched`, `drafted`; never blocked, rejected or `needs_input`; the answer is cached in memory for 30 seconds (protects the database, replaces a rate limit for the first version). If `DEMO_REPORTER_IDS` is empty the list is empty.

## 5. Priority score

A suggestion for the authority, never a decision.

| Part | Points | Source |
|---|---|---|
| Lane `hazard` | 50 (nuisance 0) | classification |
| Number of bundled reports | up to 20 | not available yet, counts as 1 in the live data, invented in the demo data |
| Age in days | up to 15 (1 per day, capped) | `created_at` |
| Safety relevant category (pothole, street light, playground, tree) | up to 15 | category table |

Tiers (share of the highest score, which follows the weights): 75 % and above high, 35 % to 74 % medium, below 35 % low. A report that is done is shown as done and is not ranked. A click shows the parts as a small bar. Three sliders (hazard, count, age) change the weights live, which answers "everybody sees urgency differently". The numbers are a first proposal, not a measured result. TODO: team confirms the weights.

## 6. Page layout

Redesigned on 2026-11-09 after a reference screenshot of the team: one dark map over the whole window with panels of frosted glass. The map is a vector map from our own server, see section 11 (a satellite image would need another provider with its own terms). The list is top left, the card of the selected report top right, place and the coordinates of the map centre bottom left, a small overview map and the buttons (zoom, show all, weights) bottom right, the filters behind the search button. On a phone the card becomes a sheet at the bottom. The text below describes the first version, the parts are the same.

- `backend/dashboard/` (it has to be inside `backend/`: the Docker build and `deploy.sh` copy only that folder): `index.html`, `style.css`, `app.js`, `score.js`, `demo-data.js`, Leaflet 1.9.4 in `vendor/` (no CDN, license included) with OpenStreetMap tiles and attribution.
- Left, wide: map, marker with the category icon and the priority dot, all markers the same size.
- Right: list sorted by score, filters for category and status.
- Click on a marker or a row highlights both and opens a card: the cleaned photo, the sanitized text, category, authority, status, age, score parts.
- Header: counts per tier, a visible label "Test data of the team" (or "Demo data" in fallback mode).
- Refreshes every 30 seconds. Works at 400 px (list below the map).

## 7. Steps

| # | Step | Who | Size | Done when |
|---|---|---|---|---|
| 1 | Read `deploy/deploy.sh`, the Dockerfile build context and the compose file: how does a static folder reach the container? Decide FastAPI `StaticFiles` or a Caddy `file_server` route | Claude | S | decision written down |
| 2 | Public endpoint with the field list, allow list, cache, tests (empty list without allow list, foreign user not shown, blocked and rejected not shown, no forbidden field in the answer (user key, real id, original photo), the photo route serves only the clean copy and only for visible reports, 404 for any other id) | Claude | M | tests green |
| 3 | `demo-data.js`: 30 invented cases in one German town | Claude | S | page loads without server |
| 4 | Map and list, synced selection | Claude | M | click works both ways |
| 5 | Score with breakdown and sliders | Claude | M | sliders re-sort the list |
| 6 | Filters, status, phone layout, fallback switch | Claude | S | usable at 400 px, `?demo` works |
| 7 | Add `DEMO_REPORTER_IDS` (comma separated) to `~/ortsbild/deploy/.env.prod` on the server (your `reporter_id` from the account sheet; the value is not a secret but stays out of git), deploy | You + Claude | S | your own report appears on the map |
| 8 | Team reads it once and confirms weights and wording | Team | S | no objection |

About one day of work in total, most of it in steps 2, 4 and 5.

## 8. Risks

- **First routes without login on the production server, now with photos.** Allow list, fixed field list, cache, tests that look for forbidden fields and for foreign ids. Review the endpoint on its own before the deploy. Before a teammate's account goes onto the list, the teammate agrees, and the first test photos show no people.
- **Test reports from home.** An exact location is the home address if the test is made there. Team members make test reports in public places and not from their own street.
- **Photo ids.** The short id must not be guessable into other reports, so it is a hash, and the lookup is limited to the visible ones.
- **Server down means dashboard down.** Keep the page with `demo-data.js` on the laptop as a backup for the day of the demo.
- **Looks like real usage.** The label says test data, and the talk says it too.
- **Weights look scientific.** The sliders and the word "suggestion" keep it honest.
- **Tile policy.** OSM tiles are for light use. If the demo gets traffic, switch provider.
- **Production load.** One cached query every 30 seconds is nothing for the Cube.

## 9. Later: real reports

Not part of this plan, listed so the work does not block it:

1. Case concept and duplicate check (PostGIS), without it no bundling.
2. Two levels instead of one: a **public view** for citizens (category, status, rounded location, no photo, no address) and an **authority view** with everything exact (address, precise spot, photo, message) behind a link only the authority has, as in the delivery discussion of 2026-11-04. Decide with the team (data protection check), then remove the allow list.
3. Status feedback from authorities (magic link buttons), see the delivery discussion of 2026-11-04.

## 10. What was built and checked (2026-11-09)

Built:

- `backend/api/public.py`: `GET /v1/public/cases` and `GET /v1/public/cases/{id}/photo`, the allow list, the 30 second cache.
- `list_visible` in both report stores (`report_status.py`, `postgres_stores.py`).
- The page in `backend/dashboard/`, served by the backend under `/dashboard/` (`api/main.py`).
- `backend/scripts/make_demo_dashboard_data.py` writes `demo-data.js`: since 2026-11-11 **four reports** around the Rotwildpark and Botnang in Stuttgart-West for the screen recording (a pothole on the Botnanger Straße with 4 votes, a broken seesaw on the playground Sommerhaldestraße 20 with 3 votes, graffiti on the Eltinger Straße, a street light on the Solitudestraße without a photo, the page shows the placeholder). The litter in the forest (Wapitiweg) is left out on purpose, the team reports it live in the recording. The places are real (OpenStreetMap), the reports, authorities and mail addresses (`example.org`) are invented. Three have a photo in `backend/dashboard/demo-photos/` (graffiti, pothole, playground). **That folder is not in git**: the pictures are not ours (the team put them in by hand, check the rights before they are shown outside the recording). The page loads photos only from `/v1/public/` and `/dashboard/demo-photos/`.
- Tests: `tests/test_api_public.py` (12) and `tests/dashboard_score.test.js` (9, run with `node --test tests/dashboard_score.test.js`).

Checked: all backend tests, the page in a headless Chrome with the demo data (desktop and 500 px, a click on a report opens the card with the priority parts).

**Not checked yet:**

- The SQL of `PostgresReportStatusStore.list_visible` was not run against a real PostgreSQL (the tests use the in-memory store). Run it once on the server before relying on it.
- The live mode with real reports and the photo on the map (needs the deploy and your `reporter_id`).
- The page on a real phone.
- The weights are a proposal of mine (section 5).

Deviations from the plan: the demo-data file is `backend/dashboard/demo-data.js` and not in a separate folder; the tier limit for high is 75 %, not 65 %, because with 65 % every hazard on a safety category was high at once (12 of 30 demo reports).

## 11. The map: vector tiles from our own server (2026-11-09)

Why: the first version used the public OpenStreetMap tiles. Their 256 px images are blurry on a Retina screen, and every visitor's browser asked a third party for the map section. A vector map is sharp at every size, the labels can be as big as we want, and it comes from our own server, so there is no third party at all.

What it is made of (all open source, pinned versions, licenses in `backend/dashboard/vendor/` and `backend/dashboard/map/`):

| Part | Version | License | What it does |
|---|---|---|---|
| MapLibre GL JS (CSP build) | 5.24.0 | BSD-3 | draws the vector tiles. 6.x is a module only and the plugin cannot find it, so 5.x |
| PMTiles | 4.5.0 | BSD-3 | reads one big map file with range requests |
| maplibre-gl-leaflet | 0.1.4 | ISC | puts the vector map under our Leaflet map, so markers, rings and list stay as they are |
| Protomaps basemap style (`@protomaps/basemaps`) | 5.7.2 | BSD-3 | the dark style, German labels (`backend/scripts/make_dashboard_style.cjs` makes `dashboard/map/style.json`, labels 1.35 times bigger) |
| Fonts (Noto Sans, glyph files) and symbols | from `protomaps/basemaps-assets` | OFL, MIT | copied into `dashboard/map/fonts` and `sprites`, so nothing is loaded from outside |
| Map data | OpenStreetMap, daily Protomaps build | ODbL | attribution "OpenStreetMap contributors" is on the map |

The page allows only our own address (CSP: scripts, worker, images, fonts, connections). There is **no fallback to a public map server**: without the map file the reports are shown on a plain background with a notice.

### Making the map file for Stuttgart

The file is not in git (hundreds of MB at most) and not in the image. It lives in `tiles/` next to `backend/` on your Mac, and in `~/ortsbild/tiles/` on the server (`deploy/deploy.sh` copies it, rsync sends nothing when it did not change; compose mounts it read only into the backend, which serves it under `/tiles/`).

Make it once with the `pmtiles` program (open source, github.com/protomaps/go-pmtiles). I could not run it myself, the permission was refused:

```
brew install pmtiles
mkdir -p tiles
# first see how big it is (nothing is downloaded):
pmtiles extract https://build.protomaps.com/20261108.pmtiles tiles/stuttgart.pmtiles --bbox=8.95,48.62,9.42,48.92 --dry-run
# then the real one:
pmtiles extract https://build.protomaps.com/20261108.pmtiles tiles/stuttgart.pmtiles --bbox=8.95,48.62,9.42,48.92
```

`20261108` is a build date that existed on 2026-11-09, take a newer one if the address answers 404. The box (west, south, east, north) is Stuttgart with about 15 km around it. Look at the size from the dry run before you start the real one. For all of Germany the same command with a bigger box would be several GB, check the free space on the Cube first.

Run it locally with `uvicorn --factory api.main:create_app` or just open the page through the backend: `http://127.0.0.1:8000/dashboard/` serves the map file from `tiles/` automatically.

### Checked and not checked

Checked: the style, the fonts and the symbols are served (tests), the file is served in pieces with range requests (tests), no other server appears in the style, the page starts in a browser with WebGL and does not crash without the map file.

**Not checked: the map with real tiles.** The public Protomaps build has no CORS header, and I did not want to get around its block of my test program. So how it looks (the label size, the colours of the dark style, the speed of the plugin with two small maps) is open until the map file exists. The page was only seen without tiles.

Open: the label size (`LABEL_SCALE` in `make_dashboard_style.cjs`), the colours of the dark style (the basemap package can change colours), the overview map in the corner (it is a second small WebGL map), whether the map stays smooth on a phone.

## 12. Icons (2026-11-09)

The categories have icons from Material Icons (Google, Apache License 2.0, license text in `backend/dashboard/vendor/LICENSE-material-icons.txt`). The paths are copied into `backend/dashboard/icons.js`, so nothing is loaded from Google. They are shown in a round badge in the colour of the priority: in the list, on the map (all badges have the same size and a black border) and in the card. To change one icon, replace its entry in `icons.js` with the path of another Material icon (source name in the file). A category that has no icon gets the icon of "other". Test: `node --test backend/tests/dashboard_icons.test.js`.

| Category | Material icon |
|---|---|
| litter | delete |
| graffiti | brush |
| street light | lightbulb |
| playground equipment | attractions |
| pothole | edit_road |
| tree | park |
| other | help |

Open: the pothole icon (a road with a pencil) and the street light (a light bulb) are the nearest Material icons, not exact. The team may want a better fit later.

## 13. Colours (2026-11-09)

- **White badge for every category:** the icon (dark) tells the category, the small corner dot tells the priority (red, yellow, green). Before, each category had its own colour (`--cat-*`); the user wanted the priority to be read only from the list and the dot, so the colours were removed. All badges have the same size and a black border; the votes are shown in the list and in the card.
- **The priority is the small dot in the corner of the badge** (red, orange, green, grey), the text "High / Medium / Low" in the list is in the same colour. A report that is done is faded. Category and priority now use different channels, so they do not mix up.
- **The map layer (TEST since 2026-11-11):** the dark map is turned into a light grey-white one with a CSS filter (`--map-filter: invert(1) grayscale(1) brightness(1.08) contrast(0.92)`), and the badges on top are inverted: dark badge, white icon, white border (`--badge-bg`, `--badge-fg`, `--badge-line`, and `--ring` for the open report). The dark look before (a filter `brightness(0.72)`, white badges with a black border) is written as a comment above the variables in `style.css`, going back is changing five values. Not seen with real map tiles yet.
- Not seen with real tiles: the test browser drew the map too late for the screenshot of this change, so how dark the map looks at 0.6 is open. If it is too dark or not dark enough, change the one number.

## 14. Photo placeholder (2026-11-09)

Every report has a picture slot: a small thumbnail (60 px) at the left of its row in the list, and a large one (16:9) at the top of the card when it is selected. While a report has no photo, or the photo cannot be loaded, both show a placeholder (the Material "image" icon on a dark panel, with "No photo yet" in the card). A real photo (`photo_url`, only an address of ours is accepted) replaces it by itself, the list loads thumbnails lazily. In the demo data there are no photos, so the placeholder is always shown. The code is `photoFrame()` in `backend/dashboard/app.js`.

## 15. Votes and category importance (2026-11-09)

- **Cases:** the endpoint groups the reports of the allow list into cases (`backend/cases.py`): same category, at most 40 m apart, a case stays open for 30 days from its first report. The dashboard shows one marker per case. `reports_count` is the number of votes (every report counts once), `last_reported_at` is the newest report. The oldest report gives text, draft, position and age. The photo is the first one in the case.
- **Score:** the part "category" is graded now (share of its weight): playground equipment 1.0, pothole 0.9, street light 0.8, tree 0.7, litter 0.35, graffiti 0.2, other 0. It replaces the yes or no "safety category". The slider is called "Importance of the category", the votes part "Votes".
- Plan and reasons: [mvp-plan.md](mvp-plan.md), section 4.

## 16. Phone first: the dashboard in the browser and in the app (2026-11-10)

The dashboard is one page for three places: the browser on a computer, the browser on a phone, and the web view inside the iOS app. Below 760 px width (and on a phone) the layout is the phone layout, above it the side panels stay as they were.

**Phone layout** (`style.css`, last block; `app.js`, section "sheets"; `sheet.js`):
- The map is the ground. Over it: a row of **filter chips** at the top (All, High, Medium, Low, then the categories; every chip is a switch with `aria-pressed`, 44 px high, the row scrolls sideways) and the mode pill ("Live" or "Demo data") under it.
- The **list is a bottom sheet** with three stops: *peek* (handle, title, count, the first report), *half*, *full*. Drag the handle with a finger, or tap it (next stop; from full back to peek), or use Enter, Space and the arrow keys. The list scrolls inside the sheet only at half and full (`overscroll-behavior: contain`). Escape at half or full goes back to peek.
- A tap on a marker or a row opens the **card as the same kind of sheet** at half height (photo, address, text, authority, "Why this priority", votes). It can be dragged to full, and dragged down (or flicked down) to close. The close button is 44 x 44. The focus goes to the close button and back to the row when it closes.
- **Priority settings** (the four weights) is a sheet over a dark scrim, opened with the sliders button, closed with its × button, the scrim or Escape. The sliders are 44 px high.
- The map buttons are *show all* and *priority settings* (two fingers zoom). They and the map credit sit above the sheet and follow its height (CSS variable `--sheet-h`). When the sheet is full they hide. `fitBounds` and the pan to a selected marker leave room for the sheet, so the markers are not hidden behind it.
- Markers are still 30 px badges (same size, black border), inside an invisible 44 x 44 area. The tooltip exists only where there is a mouse (`(hover: hover)`); the name of a marker for screen readers is a hidden text inside it.
- The small overview map is not built on a phone (one WebGL map less). The compass and the coordinates are hidden.

**Where the stops come from:** `sheet.js` holds the pure part (`snapPoints`, `nearest`, `velocityOf`, `next`, `clamp`), tested with `node --test backend/tests/dashboard_sheet.test.js`. Peek is 188 px plus the home bar, half is half the window, full is the window minus the chips. A drag rests at the stop nearest to where the finger would be 180 ms later, so a flick goes on to the next stop, a fast flick down on the card closes it.

**Touch and phone details:** `viewport-fit=cover` and `env(safe-area-inset-*)` on the sheets, the chips and the buttons (measured with the hidden `#insets` box); `100dvh` is not needed because the sheets use pixel heights from `window.innerHeight`; 16 px in form fields; `touch-action: manipulation` on controls and `touch-action: none` only on the handles; no tap highlight; `overscroll-behavior: none` on the page; `prefers-reduced-motion` switches all transitions off; `:focus-visible` rings; the mode pill is a live region (`role="status"`) and `#announce` says "N reports" when the list changes.

**States:** while the first answer is on its way the list shows four grey placeholder rows (`aria-busy`). If the server does not answer, the sheet says "The reports could not be loaded" with **Try again** and **Show the demo data**. If it answers with an empty list: "No reports yet" (and the demo button). If the filters match nothing: "Clear the filters". On an automatic refresh that fails, the last reports stay and the pill says "Live: no connection". *Changed:* the page used to switch to the demo data by itself when the server did not answer. That now happens only on the developer's own computer (`localhost`, `127.0.0.1`) and never inside the app, everywhere else the user sees the error and decides. `?live` turns the automatic demo off, `?demo` shows it at once.

**Links into the page (for the app):**
- `…/dashboard/#case=<id>` opens that case on load and when the address changes. The id is the `id` of `/v1/public/cases`. The case may not be in the data yet (the server keeps the list for 30 s), so it is tried again with every refresh until it is found or the user opens something else. The filters are cleared for it. Selecting a case writes the same address with `history.replaceState`, closing it removes it (no entries in the browser history).
- `?app=1` (or the text `OrtsbildApp` in the user agent) is the app mode: the page adds the class `in-app`, shows the position as plain text and not as a link, and blocks every link (also the map credit), so the web view cannot be taken away from the dashboard. The page has no title bar of its own, so the app can put its native one above it. Example for the app: `https://<server>/dashboard/?app=1#case=<id>`.

**Checked** (headless Chrome with touch emulation at 390 x 844, also at 2x, and 1440 x 900): peek, half and full by dragging, by tap and by keyboard; card by marker tap, row tap and deep link; swipe down closes; chips; priority settings with scrim; loading, error, retry and empty states; the desktop layout unchanged. **Not checked:** a real iPhone (the notch and home bar values are 0 in the emulation, so the safe-area padding is only read from the code), pinch zoom of the map with two fingers, the momentum of a real finger, `WKWebView` itself, and a screen reader.

**Open:** a case is shown by its first photo only; the sheet does not remember its stop between visits; the "Show the demo data" button and the `?demo` flag stay in the production page (they only show invented data, labelled as such).

## 17. No demo mode any more (2026-11-11)

Decision of the team: the dashboard does not tell between demo and real. The video of the presentation shows the whole way, with real reports in the real system: a report in the app (photo of rubbish in the forest at the Wapitiweg in the Rotwildpark, and a message), the privacy layer, the release, and then the dashboard.

- **Removed:** `demo-data.js`, the demo photos, `make_demo_dashboard_data.py`, `?demo`, the automatic demo on localhost and the buttons "Show the demo data". The page loads photos only from `/v1/public/`. If the server does not answer, the page shows the error and "Try again". The pill says "Live" and there is no banner while all is well.
- **The test reports of Stuttgart-West** (pothole, broken seesaw, graffiti, street light) are put into the database through the real API by `backend/scripts/seed_stuttgart_reports.py` (it runs inside the backend container, opens a session for its own test user, sends 7 reports, the second and third report of a place are votes, then releases them). The photos stay in `backend/eval/seed/` on the laptop and are not in git (the pictures are not ours, check the rights before the video is shown outside the university). The places are real (OpenStreetMap), the texts are written like citizens write them.
- **The allow list:** the reports show only if the reporter id of the test user and the ids of the team members are in `DEMO_REPORTER_IDS` (the script prints the id of its test user).
- **Why no test phase with fellow students:** the product is built for Germany and only two people of the course live there, so a test phase with the course would not say anything. The video shows the way, the rest is outlook.

## 18. Tiles with the number of reports, no filters, zoom buttons, German (2026-11-11)

- **Number of reports in the tile:** every row of the list has a pill with a people icon and "3 Meldungen" (singular "1 Meldung"), at the top right of the tile, also in the peek and half sheet on the phone. The name is "Meldungen": every report of a person is one vote for the case, and the list itself counts "Fälle" (one defect with all its reports). The same word is in the card ("Meldungen: 3 Meldungen zum selben Mangel"), in the priority parts and in the weight slider. The age moved to the grey line under the title: "Hoch · 85 Pkt. · vor 9 Tagen · Adresse".
- **No filters:** the selects, the chips on the phone, the filter button and all the code and CSS for them are gone. The counts per priority (Hoch, Mittel, Niedrig, Erledigt) stay as a legend on the desktop. The priority settings (weights) stay. The mode pill sits at the top left on the phone.
- **Zoom buttons:** "Vergrößern" and "Verkleinern" (44 px) are now also shown on the phone and in the app, in the column above the sheet with the locate and the settings buttons.
- **German:** the whole page (`lang="de"`): categories (Müll, Graffiti, Straßenlaterne, Spielgerät, Schlagloch, Baum, Sonstiges), priorities (Hoch, Mittel, Niedrig, Erledigt), "vor 9 Tagen", "gestern", messages, labels, aria labels, coordinates with a comma and "O" for east. Code, comments and CSS classes stay English.
- **Checked:** node tests (23), screenshots in headless Chrome at 1440x900 and at 500 px width with `?app=1` (the phone layout) against a scratch server with four cases. **Not checked:** the map tiles in the screenshots (the headless map is flaky), the large photo of the card on the desktop in one screenshot (it was still decoding), a real iPhone.

## 19. No points, no settings, a search for places and addresses (2026-11-11)

Decision of the team: the dashboard shows no score and no explanation of it, and the filter is replaced by a search.

- **Removed:** the points ("85 Pkt.") in the tiles, the block "Warum diese Priorität" with its four parts and the note, and the whole priority settings (sliders, sheet, button, scrim, their CSS). What stays is the **order of the list and the dot of the priority** (hoch, mittel, niedrig, erledigt): `score.js` keeps the tested functions and the fixed default weights as a hidden ranking, nothing in the page shows or changes them. The plain counts per priority stay as a legend on a big screen (they do not filter).
- **Search** (`search.js` for the parts without a page, the rest in `app.js`): one field "Ort oder Adresse suchen". On a big screen it sits above the list, on a phone and in the app a 44 px button at the top right opens it over the top of the map (it does not collide with the sheet or the zoom buttons). It lists first the **reports** that match (address, category name or text, every word, no care for capitals and accents, "strasse" finds "Straße"), shown at once from the loaded data; picking one opens its card. Then the **places and addresses** from our own server: `GET /v1/public/search?q=<text>` answers `{"results": [{"label": "Königstraße 1, 70173 Stuttgart", "lat": 48.78, "lon": 9.18}]}` (at most 5; 400 for fewer than 3 characters, 503 when the service is down). The page waits 300 ms after typing, cancels an older request, and checks every value of the answer before it uses it. Picking a place flies the map there (zoom 16, no animation with `prefers-reduced-motion`) and sets a temporary marker with the name; the clear button or the next search removes it. The browser calls no third party (the CSP `connect-src 'self'` stays).
- **Operating it:** `role="search"` and a combobox with a listbox, arrow keys and Enter, Escape closes the list (a second time it clears the field, on a phone it closes the field), the count of results is read out, input font 16 px.
- **Texts:** "Die Suche ist gerade nicht erreichbar.", "Nichts gefunden.", "Orte werden gesucht …", "Gib mindestens 3 Zeichen ein, um Orte zu suchen."
- **Checked:** `node --test backend/tests/*.test.js` (search.js has its own tests); headless Chrome driven over the DevTools protocol against a scratch server with the four Stuttgart cases and a fake search answer, at 1440x900 and at 390x844 (2x, `?app=1`): reports found, places found, keyboard pick with the pin, the case pick, error and empty states, the phone field and the phone pick. **Not checked:** the map tiles (headless Chrome shows none), the real search answer of our server, a real iPhone and the web view.

