"""Build the content of the server file .env.prod from backend/.env.

Takes the IONOS storage settings from backend/.env, creates a NEW database password and a NEW
PSEUDONYM_SECRET for the server and writes the file content to stdout (it is piped straight into
ssh by make-env-prod.sh, so no secret is shown or stored on this machine).

  python3 deploy/make_env_prod.py --check   only report which settings are there and how long they are
"""
import secrets
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "backend" / ".env"
STORAGE_KEYS = [
    "STORAGE_ENDPOINT_URL",
    "STORAGE_REGION",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
    "STORAGE_BUCKET_RAW",
    "STORAGE_BUCKET_CLEAN",
]
SECRET_KEYS = {"STORAGE_ACCESS_KEY", "STORAGE_SECRET_KEY"}


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    values = read_env(SOURCE)
    problems = [k for k in STORAGE_KEYS if not values.get(k)]
    if problems:
        print(f"missing in backend/.env: {', '.join(problems)}", file=sys.stderr)
        return 1
    if "ionoscloud.com" not in values["STORAGE_ENDPOINT_URL"]:
        print("STORAGE_ENDPOINT_URL in backend/.env does not point to IONOS", file=sys.stderr)
        return 1

    if "--check" in sys.argv:
        for key in STORAGE_KEYS:
            shown = f"length {len(values[key])}" if key in SECRET_KEYS else values[key]
            print(f"  {key:22} {shown}", file=sys.stderr)
        print("ok, the file for the server can be built", file=sys.stderr)
        return 0

    lines = [
        "# Created by deploy/make-env-prod.sh. Never commit it.",
        "SITE_ADDRESS=:80",
        f"DATABASE_PASSWORD={secrets.token_hex(24)}",
        *[f"{key}={values[key]}" for key in STORAGE_KEYS],
        f"API_KEY={secrets.token_hex(24)}",
        f"AUTH_SECRET={secrets.token_hex(32)}",
        f"GATEWAY_KEY={secrets.token_hex(32)}",
        f"PSEUDONYM_SECRET={secrets.token_hex(32)}",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
