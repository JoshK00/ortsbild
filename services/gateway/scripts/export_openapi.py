"""Write the OpenAPI spec of the gateway to docs/api/openapi.json (the request of the app as the gateway takes it).

Run from services/gateway:  python scripts/export_openapi.py
"""

import json
from pathlib import Path

from gateway.backend import BackendClient
from gateway.main import create_app
from gateway.raw_store import InMemoryRawPhotoStore

OUT = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"

app = create_app(raw_store=InMemoryRawPhotoStore(), backend=BackendClient("http://backend:8000", "unused", 1))
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
