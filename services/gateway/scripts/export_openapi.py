"""Write the OpenAPI spec to docs/api/openapi.json (the contract between app and gateway).

Run from services/gateway:  python scripts/export_openapi.py
"""

import json
import tempfile
from pathlib import Path

from gateway.config import Settings
from gateway.main import create_app

OUT = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"

with tempfile.TemporaryDirectory() as tmp:
    app = create_app(Settings(_env_file=None, database_url=f"sqlite:///{tmp}/spec.db", storage_local_root=tmp))
    spec = app.openapi()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
