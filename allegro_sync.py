#!/usr/bin/env python3
"""Read-only Allegro offer audit. Live writes are deliberately unsupported."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.allegro.pl"
TOKEN_URL = "https://allegro.pl/auth/oauth/token"
ACCEPT = "application/vnd.allegro.public.v1+json"
USER_AGENT = "AMDPRO-Allegro-Sync/1.0 (+https://amdpro.eu)"


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        error_name = payload.get("error", "oauth_error")
        description = payload.get("error_description", "Allegro rejected the token refresh")
        # Postman can expose only the access token for some saved OAuth tokens.
        # During this read-only audit, allow that JWT to be supplied through the
        # existing secret so the audit can proceed without changing any offers.
        access_token = refresh_token.strip()
        if access_token.lower().startswith("bearer "):
            access_token = access_token[7:].strip()
        if error_name == "invalid_grant" and access_token.count(".") == 2:
            print("Refresh token unavailable; using the supplied access token for this read-only audit.")
            return {"access_token": access_token}
        raise SystemExit(f"Allegro OAuth error: {error_name}: {description}") from None


def safe_token_metadata(access_token: str) -> dict:
    """Decode only non-secret JWT claims for troubleshooting."""
    try:
        payload_part = access_token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_part + padding))
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {"format": "not-a-jwt"}
    allowed = ("iss", "aud", "exp", "iat", "client_id", "scope")
    return {key: payload[key] for key in allowed if key in payload}


def api_get(path: str, access_token: str) -> dict:
    request = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": ACCEPT,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def load_preview(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["sku"]: row for row in csv.DictReader(handle) if row.get("sku")}


def audit_offers(preview: dict[str, dict[str, str]], access_token: str) -> dict[str, int]:
    result = {"offers": 0, "matched_by_sku": 0, "unmatched": 0, "price_changes": 0, "stock_changes": 0}
    offset = 0
    while True:
        payload = api_get(f"/sale/offers?limit=1000&offset={offset}", access_token)
        offers = payload.get("offers", [])
        for offer in offers:
            result["offers"] += 1
            sku = ((offer.get("external") or {}).get("id") or "").strip()
            row = preview.get(sku)
            if not row:
                result["unmatched"] += 1
                continue
            result["matched_by_sku"] += 1
            current_price = str(((offer.get("sellingMode") or {}).get("price") or {}).get("amount") or "")
            current_stock = str(((offer.get("stock") or {}).get("available") or ""))
            result["price_changes"] += int(current_price != row["price_eur_plus_10pct"])
            result["stock_changes"] += int(current_stock != row["quantity"])
        if len(offers) < 1000:
            break
        offset += len(offers)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, default=Path("build/allegro-preview.csv"))
    parser.add_argument("--output", type=Path, default=Path("build/allegro-audit.json"))
    args = parser.parse_args()
    required = {name: os.environ.get(name, "") for name in ("ALLEGRO_CLIENT_ID", "ALLEGRO_CLIENT_SECRET", "ALLEGRO_REFRESH_TOKEN")}
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit("Missing GitHub Actions secrets: " + ", ".join(missing))
    tokens = refresh_access_token(required["ALLEGRO_CLIENT_ID"], required["ALLEGRO_CLIENT_SECRET"], required["ALLEGRO_REFRESH_TOKEN"])
    print("Token metadata:", json.dumps(safe_token_metadata(tokens["access_token"]), sort_keys=True))
    try:
        me = api_get("/me", tokens["access_token"])
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        account = "profile-scope-not-granted"
    else:
        account = me.get("login", "unknown")
        if account != "Automotodiely":
            raise SystemExit(f"Wrong Allegro account: {account}")
    result = {"account": account, "mode": "dry-run", **audit_offers(load_preview(args.preview), tokens["access_token"])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
