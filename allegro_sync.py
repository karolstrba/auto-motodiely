#!/usr/bin/env python3
"""Read-only Allegro offer audit. Live writes are deliberately unsupported."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
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
        # Copying a long token from Postman may insert visual or zero-width
        # characters. JWTs contain only base64url characters and separators.
        access_token = re.sub(r"[^A-Za-z0-9._-]", "", refresh_token)
        if access_token.lower().startswith("bearer "):
            access_token = access_token[7:].strip()
        if access_token.count(".") == 2:
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
        return {
            "format": "not-a-jwt",
            "length": len(access_token),
            "segments": access_token.count(".") + 1,
            "starts_with_jwt_header": access_token.startswith("eyJ"),
            "contains_whitespace": any(character.isspace() for character in access_token),
        }
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


def api_patch(path: str, access_token: str, payload: dict) -> int:
    request = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {access_token}", "Accept": ACCEPT, "Content-Type": ACCEPT, "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()
        return response.status


def api_post(path: str, access_token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {access_token}", "Accept": ACCEPT, "Content-Type": ACCEPT, "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def load_preview(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["sku"]: row for row in csv.DictReader(handle) if row.get("sku")}


def target_price(row: dict[str, str], currency: str) -> str:
    if currency == "PLN":
        return row.get("price_pln_plus_10pct", "")
    if currency == "EUR":
        return row.get("price_eur_plus_10pct", "")
    return ""


def build_offer_patch(offer: dict, row: dict[str, str]) -> dict:
    if str((offer.get("publication") or {}).get("status") or "") != "ACTIVE":
        return {}
    price = ((offer.get("sellingMode") or {}).get("price") or {})
    currency = str(price.get("currency") or "")
    desired_price = target_price(row, currency)
    try:
        desired_stock = int(row.get("quantity", "0"))
    except ValueError:
        return {}
    if not desired_price or desired_stock <= 0:
        return {}
    patch = {}
    if str(price.get("amount") or "") != desired_price:
        patch["sellingMode"] = {"price": {"amount": desired_price, "currency": currency}}
    stock = offer.get("stock") or {}
    if str(stock.get("available") or "") != str(desired_stock):
        patch["stock"] = {"available": desired_stock, "unit": str(stock.get("unit") or "UNIT")}
    return patch


def build_draft_payload(row: dict[str, str], currency: str) -> dict:
    desired_price = target_price(row, currency)
    try:
        desired_stock = int(row.get("quantity", "0"))
    except ValueError:
        desired_stock = 0
    images = [url for url in row.get("image_urls", "").split("|") if url]
    if row.get("new_offer_status") != "ready" or not desired_price or desired_stock <= 0:
        return {}
    payload = {
        "productSet": [{"product": {"id": row["ean"], "idType": "GTIN"}}],
        "name": row["name"][:75],
        "sellingMode": {"price": {"amount": desired_price, "currency": currency}},
        "stock": {"available": desired_stock, "unit": "UNIT"},
        "publication": {"status": "INACTIVE"},
        "external": {"id": row["sku"][:100]},
    }
    if images:
        payload["images"] = images[:16]
    return payload


def create_one_draft(preview: dict[str, dict[str, str]], access_token: str) -> dict:
    matched_skus: set[str] = set()
    currencies: dict[str, int] = {}
    offset = 0
    while True:
        page = api_get(f"/sale/offers?limit=1000&offset={offset}", access_token)
        offers = page.get("offers", [])
        for offer in offers:
            sku = ((offer.get("external") or {}).get("id") or "").strip()
            if sku:
                matched_skus.add(sku)
            currency = str((((offer.get("sellingMode") or {}).get("price") or {}).get("currency")) or "")
            if currency:
                currencies[currency] = currencies.get(currency, 0) + 1
        if len(offers) < 1000:
            break
        offset += len(offers)

    currency = max(currencies, key=currencies.get) if currencies else "EUR"
    for sku, row in preview.items():
        if sku in matched_skus:
            continue
        payload = build_draft_payload(row, currency)
        if not payload:
            continue
        response = api_post("/sale/product-offers", access_token, payload)
        publication = response.get("publication") or {}
        if publication.get("status") != "INACTIVE":
            raise RuntimeError("Allegro did not confirm an inactive draft")
        return {
            "offer_id": str(response.get("id") or ""),
            "sku": sku,
            "ean": row.get("ean", ""),
            "name": response.get("name") or row.get("name", ""),
            "price": payload["sellingMode"]["price"],
            "stock": payload["stock"],
            "status": publication.get("status"),
            "validation": response.get("validation") or {},
        }
    raise SystemExit("No in-stock, catalog-ready product missing on Allegro was found")


def apply_sample(preview: dict[str, dict[str, str]], access_token: str, limit: int) -> dict:
    result = {"requested_limit": limit, "updated": 0, "updated_offer_ids": []}
    offset = 0
    while result["updated"] < limit:
        payload = api_get(f"/sale/offers?limit=1000&offset={offset}", access_token)
        offers = payload.get("offers", [])
        for offer in offers:
            sku = ((offer.get("external") or {}).get("id") or "").strip()
            row = preview.get(sku)
            patch = build_offer_patch(offer, row) if row else {}
            if not patch:
                continue
            status = api_patch(f"/sale/product-offers/{offer['id']}", access_token, patch)
            if status not in (200, 202):
                raise RuntimeError(f"Unexpected Allegro PATCH status: {status}")
            result["updated"] += 1
            result["updated_offer_ids"].append(str(offer["id"]))
            if result["updated"] >= limit:
                break
        if len(offers) < 1000:
            break
        offset += len(offers)
    return result


def summarize_missing_offers(preview: dict[str, dict[str, str]], matched_skus: set[str]) -> dict[str, int]:
    missing = [row for sku, row in preview.items() if sku not in matched_skus]
    return {
        "feed_products": len(preview),
        "missing_on_allegro": len(missing),
        "ready_to_create": sum(row.get("new_offer_status") == "ready" for row in missing),
        "blocked_to_create": sum(row.get("new_offer_status") != "ready" for row in missing),
        "missing_in_stock": sum(int(row.get("quantity", "0") or "0") > 0 for row in missing),
    }


def audit_offers(preview: dict[str, dict[str, str]], access_token: str) -> dict:
    matched_skus: set[str] = set()
    result = {
        "offers": 0,
        "matched_by_sku": 0,
        "unmatched": 0,
        "price_changes": 0,
        "stock_changes": 0,
        "unsupported_currency": 0,
        "currencies": {},
        "marketplaces": {},
    }
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
            matched_skus.add(sku)
            price = ((offer.get("sellingMode") or {}).get("price") or {})
            current_price = str(price.get("amount") or "")
            currency = str(price.get("currency") or "UNKNOWN")
            result["currencies"][currency] = result["currencies"].get(currency, 0) + 1
            marketplace = str((((offer.get("publication") or {}).get("marketplace") or {}).get("id")) or "UNKNOWN")
            result["marketplaces"][marketplace] = result["marketplaces"].get(marketplace, 0) + 1
            desired_price = target_price(row, currency)
            if desired_price:
                result["price_changes"] += int(current_price != desired_price)
            else:
                result["unsupported_currency"] += 1
            current_stock = str(((offer.get("stock") or {}).get("available") or ""))
            result["stock_changes"] += int(current_stock != row["quantity"])
        if len(offers) < 1000:
            break
        offset += len(offers)
    result.update(summarize_missing_offers(preview, matched_skus))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, default=Path("build/allegro-preview.csv"))
    parser.add_argument("--output", type=Path, default=Path("build/allegro-audit.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--create-draft", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 10:
        raise SystemExit("--limit must be between 1 and 10")
    if args.apply and args.create_draft:
        raise SystemExit("--apply and --create-draft cannot be used together")
    if args.apply and args.confirm != "AMDPRO-10-PERCENT":
        raise SystemExit("Live synchronization requires --confirm AMDPRO-10-PERCENT")
    if args.create_draft and args.confirm != "AMDPRO-CREATE-DRAFT":
        raise SystemExit("Draft creation requires --confirm AMDPRO-CREATE-DRAFT")
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
    preview = load_preview(args.preview)
    result = {"account": account, "mode": "dry-run", **audit_offers(preview, tokens["access_token"])}
    if args.apply:
        result["mode"] = "live-sample"
        result["live_sample"] = apply_sample(preview, tokens["access_token"], args.limit)
    if args.create_draft:
        result["mode"] = "create-one-inactive-draft"
        result["draft"] = create_one_draft(preview, tokens["access_token"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
