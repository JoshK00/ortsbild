"""Put the team's test reports of Stuttgart-West into the system, through the real API, so they are no invented data.

Every report goes the same way a report from the app goes: photo and text through the privacy layer, classification,
research of the authority, draft, and then the release ("Freigeben"), so the dashboard shows it. The reports of one place
are several reports on purpose: the second and third one count as votes (docs/documentation.md, duplicates).

It runs INSIDE the backend container of the server, because it needs the secrets of the server to open a session for its own
test user (never a real user):

    docker cp seed-photos <backend container>:/tmp/seed-photos
    docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
        python scripts/seed_stuttgart_reports.py --photos /tmp/seed-photos

It prints the reporter id of the test user. Add it to DEMO_REPORTER_IDS in .env.prod (next to the ids of the team members),
or the dashboard does not show the reports. Running it twice creates nothing new (the ids of the reports are fixed, the server
answers a repeat with the first result). To remove everything: DELETE /v1/account with a session of that user.

The costs: one call of the classification, and of the research and the draft per new place, a few cents at most.
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

# (key, category the classifier should find, text, lat, lon, place, photo file or None). The places are real (OpenStreetMap, 2026-11-11),
# the texts are written like a citizen would write them.
BOTNANG = {"country_code": "DE", "state": "Baden-Württemberg", "municipality": "Stuttgart", "district": "Botnang", "postal_code": "70195"}
WEST = {"country_code": "DE", "state": "Baden-Württemberg", "municipality": "Stuttgart", "district": "Stuttgart-West"}

REPORTS = [
    ("pothole-1", "pothole", "Tiefes Schlagloch am Fahrbahnrand der Botnanger Straße. Nach Regen steht Wasser darin und man sieht die Tiefe nicht.",
     48.775555, 9.140017, {**WEST, "postal_code": "70193", "street": "Botnanger Straße"}, "pothole.jpg"),
    ("pothole-2", "pothole", "Das Schlagloch in der Botnanger Straße ist noch da und wird größer. Radfahrer weichen auf die Fahrbahn aus.",
     48.775575, 9.140040, {**WEST, "postal_code": "70193", "street": "Botnanger Straße"}, None),
    ("pothole-3", "pothole", "Schlagloch in der Botnanger Straße, bitte reparieren. Autos und Fahrräder müssen ausweichen.",
     48.775540, 9.139990, {**WEST, "postal_code": "70193", "street": "Botnanger Straße"}, None),
    ("playground-1", "playground_equipment", "Die Wippe auf dem Spielplatz ist in der Mitte durchgebrochen, die Bruchkanten sind scharf. Kinder spielen direkt daneben.",
     48.779051, 9.118504, {**BOTNANG, "street": "Sommerhaldestraße", "house_number": "20"}, "playground.jpg"),
    ("playground-2", "playground_equipment", "Spielplatz Sommerhaldestraße: Die Wippe ist kaputt, es besteht Verletzungsgefahr für Kinder.",
     48.779070, 9.118520, {**BOTNANG, "street": "Sommerhaldestraße", "house_number": "20"}, None),
    ("graffiti-1", "graffiti", "Graffiti an einer Hauswand, der Putz darunter bröckelt schon.",
     48.77973, 9.120389, {**BOTNANG, "street": "Eltinger Straße", "house_number": "87"}, "graffiti.jpg"),
    ("street-light-1", "street_light", "Die Straßenlaterne an der Haltestelle ist seit Tagen aus, der Weg ist abends dunkel.",
     48.786091, 9.086424, {**WEST, "postal_code": "70197", "street": "Solitudestraße"}, None),
]


def seed(client, headers: dict, photos: Path | None, reports=REPORTS, prefix: str = "seed-stuttgart") -> list[dict]:
    """Send the reports, answer a question of the app if the picture is not clear, release each one. Returns one line per report.

    `client` is an httpx client (or the test client of FastAPI, it has the same calls).
    """
    lines = []
    for key, expected, text, lat, lon, place, photo_name in reports:
        data = {"client_report_id": f"{prefix}-{key}", "text": text, "lat": str(lat), "lon": str(lon), "accuracy_m": "5", **place}
        files = None
        photo_path = (photos / photo_name) if photos and photo_name else None
        if photo_name and (photo_path is None or not photo_path.is_file()):
            print(f"  {key}: photo {photo_name} not found, sent without a photo")
            photo_path = None
        if photo_path:
            files = {"photo": (photo_path.name, photo_path.read_bytes(), "image/jpeg")}
        answer = client.post("/v1/reports", data=data, files=files, headers=headers)
        if answer.status_code != 200:
            lines.append({"key": key, "result": f"error {answer.status_code}"})
            continue
        body = answer.json()
        if body.get("clarification"):  # the picture was not clear, the team says what it is
            answer = client.post(f"/v1/reports/{body['id']}/answer", json={"category": expected}, headers=headers)
            body = answer.json() if answer.status_code == 200 else body
        result = "not released"
        if body.get("status") == "sanitized" and body.get("classification"):
            released = client.post(f"/v1/reports/{body['id']}/approve", headers=headers)
            if released.status_code == 200:
                body, result = released.json(), "released"
        category = (body.get("classification") or {}).get("category")
        lines.append({
            "key": key, "result": result, "category": category, "expected": expected,
            "authority": (body.get("research") or {}).get("authority"), "votes": (body.get("case") or {}).get("votes"),
            "photo": bool(body.get("photo_urls")),
        })
    return lines


def session_headers() -> tuple[dict, str]:
    """A session for the test user of this script (not a real person). Needs the secrets of the server in the environment."""
    from auth.postgres_store import PostgresRefreshTokenStore
    from auth.sessions import AuthManager
    from auth.tokens import TokenIssuer
    from privacy.pseudonyms import hash_identifier

    secret = os.environ["PSEUDONYM_SECRET"]
    manager = AuthManager(None, TokenIssuer(os.environ["AUTH_SECRET"]), PostgresRefreshTokenStore(os.environ["DATABASE_URL"]), secret)
    user_key = hash_identifier("stuttgart-test-reports", "apple_sub", secret)
    pair = manager._new_pair(user_key, uuid.uuid4().hex)  # private on purpose: an operator script, no endpoint can do this
    return {"Authorization": f"Bearer {pair.access_token}"}, pair.reporter_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--photos", type=Path, help="folder with pothole.jpg, playground.jpg and graffiti.jpg")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="the address of the backend")
    args = parser.parse_args()

    import httpx

    headers, reporter_id = session_headers()
    with httpx.Client(base_url=args.base, timeout=180) as client:
        lines = seed(client, headers, args.photos)
    for line in lines:
        print(line)
    problems = [line for line in lines if line.get("result") != "released" or line.get("category") != line.get("expected")]
    print(f"\nreporter id of the test user: {reporter_id}  -> add it to DEMO_REPORTER_IDS in .env.prod")
    if problems:
        print(f"{len(problems)} of {len(lines)} reports are not as expected, see above")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
