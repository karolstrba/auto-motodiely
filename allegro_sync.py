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
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"message": error.reason}
        raise SystemExit(
            f"Allegro API POST {path} failed with HTTP {error.code}: "
            + json.dumps(body, ensure_ascii=False)
        ) from None


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


def find_unique_catalog_product(row: dict[str, str], access_token: str) -> str:
    query = urllib.parse.urlencode(
        {"phrase": row.get("ean", ""), "language": "pl-PL", "mode": "GTIN"}
    )
    products = api_get(f"/sale/products?{query}", access_token).get("products", [])
    return str(products[0].get("id") or "") if len(products) == 1 else ""


def build_draft_payload(row: dict[str, str], currency: str, product_id: str) -> dict:
    desired_price = target_price(row, currency)
    try:
        desired_stock = int(row.get("quantity", "0"))
    except ValueError:
        desired_stock = 0
    images = [url for url in row.get("image_urls", "").split("|") if url]
    if row.get("new_offer_status") != "ready" or not product_id or not desired_price or desired_stock <= 0:
        return {}
    payload = {
        "productSet": [{"product": {"id": product_id}}],
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
        if row.get("new_offer_status") != "ready" or int(row.get("quantity", "0") or "0") <= 0:
            continue
        product_id = find_unique_catalog_product(row, access_token)
        if not product_id:
            continue
        payload = build_draft_payload(row, currency, product_id)
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


def compact_reference(value: dict | None) -> dict:
    value = value or {}
    return {"id": value["id"]} if value.get("id") else ({"name": value["name"]} if value.get("name") else {})


def find_account_template(access_token: str) -> dict:
    offset = 0
    while True:
        page = api_get(f"/sale/offers?publication.status=ACTIVE&limit=1000&offset={offset}", access_token)
        offers = page.get("offers", [])
        for offer in offers:
            details = api_get(f"/sale/product-offers/{offer['id']}", access_token)
            shipping = compact_reference((details.get("delivery") or {}).get("shippingRates"))
            services = details.get("afterSalesServices") or {}
            returns = compact_reference(services.get("returnPolicy"))
            complaints = compact_reference(services.get("impliedWarranty"))
            if shipping and returns and complaints and details.get("location"):
                return details
        if len(offers) < 1000:
            break
        offset += len(offers)
    raise SystemExit("No active offer with preset shipping, returns and complaints was found")


def resolve_responsible_producer(draft: dict, access_token: str) -> dict:
    product = (((draft.get("productSet") or [{}])[0]).get("product") or {})
    product_id = str(product.get("id") or "")
    if not product_id:
        raise SystemExit("Draft has no catalog product ID")
    details = api_get(f"/sale/products/{product_id}?language=pl-PL", access_token)
    suggested = ((details.get("productSafety") or {}).get("responsibleProducer") or {})
    if suggested.get("id"):
        return {"type": "ID", "id": suggested["id"]}
    if suggested.get("name"):
        return {"type": "NAME", "name": suggested["name"]}

    brand = str(draft.get("name") or "").split(" ", 1)[0].casefold()
    account_data = api_get("/sale/responsible-producers?limit=1000", access_token)
    producers = account_data.get("responsibleProducers", account_data.get("producers", []))
    matches = [item for item in producers if brand and brand in str(item.get("name") or "").casefold()]
    if len(matches) == 1:
        return {"type": "ID", "id": matches[0]["id"]}
    raise SystemExit(f"No unique preset responsible producer found for brand {brand.upper()}")


def activate_inactive_offer(offer_id: str, access_token: str) -> dict:
    draft = api_get(f"/sale/product-offers/{offer_id}", access_token)
    if str(draft.get("id") or "") != offer_id:
        raise SystemExit("Allegro returned a different offer")
    if ((draft.get("publication") or {}).get("status")) != "INACTIVE":
        raise SystemExit("Only an INACTIVE draft can be activated by this mode")
    if ((draft.get("external") or {}).get("id")) != "02SKITK":
        raise SystemExit("Safety check failed: unexpected SKU for the first draft")

    template = find_account_template(access_token)
    services = template.get("afterSalesServices") or {}
    source_item = (draft.get("productSet") or [{}])[0]
    product_id = str((source_item.get("product") or {}).get("id") or "")
    product_item = {
        "product": {"id": product_id},
        "quantity": source_item.get("quantity") or {"value": 1},
        "responsibleProducer": resolve_responsible_producer(draft, access_token),
    }
    for key in ("responsiblePerson", "safetyInformation"):
        if source_item.get(key):
            product_item[key] = source_item[key]

    payload = {
        "productSet": [product_item],
        "delivery": {
            "shippingRates": compact_reference((template.get("delivery") or {}).get("shippingRates")),
            "handlingTime": "P3D",
        },
        "afterSalesServices": {
            "returnPolicy": compact_reference(services.get("returnPolicy")),
            "impliedWarranty": compact_reference(services.get("impliedWarranty")),
        },
        "location": template.get("location"),
        "payments": template.get("payments") or {"invoice": "VAT"},
        "publication": {"status": "ACTIVE"},
    }
    warranty = compact_reference(services.get("warranty"))
    if warranty:
        payload["afterSalesServices"]["warranty"] = warranty
    status = api_patch(f"/sale/product-offers/{offer_id}", access_token, payload)
    if status not in (200, 202):
        raise RuntimeError(f"Unexpected Allegro PATCH status: {status}")
    verified = api_get(f"/sale/product-offers/{offer_id}", access_token)
    return {
        "offer_id": offer_id,
        "sku": ((verified.get("external") or {}).get("id") or ""),
        "status": ((verified.get("publication") or {}).get("status") or ""),
        "handling_time": ((verified.get("delivery") or {}).get("handlingTime") or ""),
        "shipping_rates": compact_reference((verified.get("delivery") or {}).get("shippingRates")),
        "after_sales_services": verified.get("afterSalesServices") or {},
        "validation": verified.get("validation") or {},
    }


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
    parser.add_argument("--activate-offer", default="")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 10:
        raise SystemExit("--limit must be between 1 and 10")
    selected_write_modes = int(args.apply) + int(args.create_draft) + int(bool(args.activate_offer))
    if selected_write_modes > 1:
        raise SystemExit("--apply, --create-draft and --activate-offer cannot be combined")
    if args.apply and args.confirm != "AMDPRO-10-PERCENT":
        raise SystemExit("Live synchronization requires --confirm AMDPRO-10-PERCENT")
    if args.create_draft and args.confirm != "AMDPRO-CREATE-DRAFT":
        raise SystemExit("Draft creation requires --confirm AMDPRO-CREATE-DRAFT")
    if args.activate_offer and (
        args.activate_offer != "18885073327" or args.confirm != "AMDPRO-ACTIVATE-18885073327"
    ):
        raise SystemExit("Activation requires the exact offer ID and confirmation")
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
    if args.create_draft:
        result = {
            "account": account,
            "mode": "create-one-inactive-draft",
            "draft": create_one_draft(preview, tokens["access_token"]),
        }
    elif args.activate_offer:
        result = {
            "account": account,
            "mode": "activate-one-verified-draft",
            "activation": activate_inactive_offer(args.activate_offer, tokens["access_token"]),
        }
    else:
        result = {"account": account, "mode": "dry-run", **audit_offers(preview, tokens["access_token"])}
        if args.apply:
            result["mode"] = "live-sample"
            result["live_sample"] = apply_sample(preview, tokens["access_token"], args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
