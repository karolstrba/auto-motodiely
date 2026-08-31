#!/usr/bin/env python3
"""Build a dynamic, stock-only AMDPRO supplier feed."""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DEFAULT_LIMIT = 44_000
DEFAULT_ALLEGRO_MARKUP = Decimal("10")
PROTECTED_PREFIXES = (
    "Opony",
    "Dętki, Tubliss, mousse",
    "Odzież i ochraniacze",
    "Buty motocyklowe",
    "Kaski i gogle",
)
CORE_PREFIXES = (
    "Filtry",
    "Układ hamulcowy",
    "Układ napędowy",
    "Silnik",
    "Układ elektryczny",
    "Oleje i chemia",
    "Układ paliwowy",
    "Zawieszenie",
    "Nadwozie",
)


def number(value: str | None) -> float:
    try:
        return float((value or "0").strip().replace(",", "."))
    except ValueError:
        return 0.0


def quality_score(product: ET.Element, position: int) -> tuple[int, int]:
    category = (product.findtext("category") or "").strip()
    quantity = number(product.findtext("quantity"))
    price = number(product.findtext("price"))
    name = (product.findtext("name") or "").strip()
    points = min(int(quantity), 20) * 5
    points += 35 if product.find("./imgs/i") is not None else 0
    points += 20 if (product.findtext("ean") or "").strip() else 0
    points += 12 if (product.findtext("marka") or "").strip() else 0
    points += 8 if price > 0 else -100
    points += 8 if len(name) >= 12 else 0
    points += 25 if category.startswith(CORE_PREFIXES) else 0
    return points, -position


def choose(source: Path, limit: int) -> tuple[set[str], int]:
    protected: list[tuple[tuple[int, int], str]] = []
    candidates: list[tuple[tuple[int, int], str]] = []
    in_stock = 0
    for position, (_, product) in enumerate(
        ET.iterparse(source, events=("end",)), start=1
    ):
        if product.tag != "product":
            continue
        if number(product.findtext("quantity")) <= 0:
            product.clear()
            continue
        product_id = product.attrib.get("id", "").strip()
        if not product_id:
            product.clear()
            continue
        in_stock += 1
        category = (product.findtext("category") or "").strip()
        item = (quality_score(product, position), product_id)
        (protected if category.startswith(PROTECTED_PREFIXES) else candidates).append(item)
        product.clear()

    protected.sort(reverse=True)
    selected_protected = protected[:limit]
    remaining = max(0, limit - len(selected_protected))
    selected = selected_protected + heapq.nlargest(remaining, candidates)
    return {product_id for _, product_id in selected}, in_stock


def decimal(value: str | None) -> Decimal:
    try:
        return Decimal((value or "0").strip().replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def add_text(parent: ET.Element, tag: str, value: str | None) -> ET.Element | None:
    value = (value or "").strip()
    if not value:
        return None
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def load_category_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["pl_category"].strip(): row["sk_category"].strip() for row in csv.DictReader(handle) if row.get("pl_category") and row.get("sk_category")}


def load_name_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["code"].strip(): row["sk_name"].strip()
            for row in csv.DictReader(handle)
            if row.get("code") and row.get("sk_name")
        }


def to_shoptet_item(
    product: ET.Element,
    pln_per_eur: Decimal,
    category_map: dict[str, str],
    name_map: dict[str, str],
) -> ET.Element:
    item = ET.Element("SHOPITEM")
    code = (
        (product.findtext("kod") or "").strip()
        or (product.findtext("symbol") or "").strip()
        or product.attrib.get("id", "").strip()
    )
    source_name = (product.findtext("name") or "").strip()
    name = name_map.get(code, source_name)[:250]
    category = (product.findtext("category") or "").strip()
    price_pln = decimal(product.findtext("price"))
    quantity = decimal(product.findtext("quantity"))

    add_text(item, "NAME", name or code)
    add_text(item, "MANUFACTURER", (product.findtext("marka") or "")[:200])
    add_text(item, "ITEM_TYPE", "product")
    add_text(item, "UNIT", "ks")
    if category:
        categories = ET.SubElement(item, "CATEGORIES")
        source_category = category.replace(" / ", " > ")
        add_text(categories, "CATEGORY", category_map.get(source_category, source_category)[:255])
    image_urls = [node.attrib.get("url", "").strip() for node in product.findall("./imgs/i")]
    if any(image_urls):
        images = ET.SubElement(item, "IMAGES")
        for url in image_urls:
            add_text(images, "IMAGE", url)

    add_text(item, "CODE", code[:64])
    ean = (product.findtext("ean") or "").strip()
    if ean.isdigit() and 8 <= len(ean) <= 14:
        add_text(item, "EAN", ean)
    price_eur = (price_pln / pln_per_eur).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    add_text(item, "PRICE_VAT", f"{price_eur:.2f}")
    stock = ET.SubElement(item, "STOCK")
    add_text(stock, "AMOUNT", str(quantity.normalize()))
    add_text(item, "CURRENCY", "EUR")
    add_text(item, "AVAILABILITY_IN_STOCK", "Skladom")
    add_text(item, "AVAILABILITY_OUT_OF_STOCK", "Momentálne nedostupné")
    return item


def valid_ean(value: str) -> bool:
    return value.isdigit() and 8 <= len(value) <= 14


def allegro_price(price_pln: Decimal, pln_per_eur: Decimal, markup_percent: Decimal) -> Decimal:
    multiplier = Decimal("1") + markup_percent / Decimal("100")
    return (price_pln / pln_per_eur * multiplier).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def write_allegro_preview(
    source: Path,
    destination: Path,
    pln_per_eur: Decimal,
    markup_percent: Decimal = DEFAULT_ALLEGRO_MARKUP,
) -> dict[str, int]:
    """Write a complete, API-neutral Allegro synchronization preview.

    Zero-stock rows are intentionally retained so a later API synchronizer can
    pause an existing offer and restore it when supplier stock returns.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    counts = {"products": 0, "in_stock": 0, "new_offer_ready": 0, "needs_data": 0}
    fields = (
        "supplier_id", "sku", "ean", "name", "brand", "source_category",
        "price_pln", "price_pln_plus_10pct", "price_eur_plus_10pct", "quantity", "image_urls",
        "gpsr", "new_offer_status", "blocking_reason",
    )
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for _, product in ET.iterparse(source, events=("end",)):
            if product.tag != "product":
                continue
            supplier_id = product.attrib.get("id", "").strip()
            sku = (
                (product.findtext("kod") or "").strip()
                or (product.findtext("symbol") or "").strip()
                or supplier_id
            )
            ean = (product.findtext("ean") or "").strip()
            price_pln = decimal(product.findtext("price"))
            quantity = max(Decimal("0"), decimal(product.findtext("quantity")))
            images = [node.attrib.get("url", "").strip() for node in product.findall("./imgs/i")]
            images = [url for url in images if url]
            blockers = []
            if not supplier_id or not sku:
                blockers.append("missing_sku")
            if not valid_ean(ean):
                blockers.append("missing_or_invalid_ean")
            if price_pln <= 0:
                blockers.append("invalid_price")
            if not images:
                blockers.append("missing_image")
            status = "ready" if not blockers else "needs_data"
            writer.writerow(
                {
                    "supplier_id": supplier_id,
                    "sku": sku,
                    "ean": ean,
                    "name": (product.findtext("name") or "").strip()[:250],
                    "brand": (product.findtext("marka") or "").strip()[:200],
                    "source_category": (product.findtext("category") or "").strip(),
                    "price_pln": f"{price_pln:.2f}",
                    "price_pln_plus_10pct": f"{allegro_price(price_pln, Decimal('1'), markup_percent):.2f}" if price_pln > 0 else "",
                    "price_eur_plus_10pct": f"{allegro_price(price_pln, pln_per_eur, markup_percent):.2f}" if price_pln > 0 else "",
                    "quantity": str(quantity.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                    "image_urls": "|".join(images),
                    "gpsr": (product.findtext("gpsr") or "").strip(),
                    "new_offer_status": status,
                    "blocking_reason": "|".join(blockers),
                }
            )
            counts["products"] += 1
            counts["in_stock"] += int(quantity > 0)
            counts["new_offer_ready" if status == "ready" else "needs_data"] += 1
            product.clear()
    temporary.replace(destination)
    return counts


def write_feed(
    source: Path, destination: Path, selected: set[str], pln_per_eur: Decimal,
    category_map: dict[str, str] | None = None,
    name_map: dict[str, str] | None = None,
) -> int:
    category_map = category_map or {}
    name_map = name_map or {}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    count = 0
    with temporary.open("wb") as output:
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
        for _, product in ET.iterparse(source, events=("end",)):
            if product.tag != "product":
                continue
            if product.attrib.get("id", "") in selected:
                output.write(
                    ET.tostring(
                        to_shoptet_item(product, pln_per_eur, category_map, name_map),
                        encoding="utf-8",
                    )
                )
                output.write(b"\n")
                count += 1
            product.clear()
        output.write(b"</SHOP>\n")
    if count != len(selected):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Selected {len(selected)} products, wrote {count}")
    ET.parse(temporary)
    temporary.replace(destination)
    return count


def exchange_rate() -> Decimal:
    override = os.environ.get("PLN_PER_EUR")
    if override:
        rate = decimal(override)
        if rate > 0:
            return rate
    try:
        request = urllib.request.Request(
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
            headers={"User-Agent": "AMDPRO-feed/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
        for node in root.iter():
            if node.attrib.get("currency") == "PLN":
                rate = decimal(node.attrib.get("rate"))
                if rate > 0:
                    return rate
    except Exception as exc:
        print(f"ECB exchange-rate lookup failed, using fallback: {exc}")
    return Decimal("4.3365")


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "AMDPRO-feed/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"Supplier returned HTTP {response.status}")
        destination.write_bytes(response.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("public/feed-pl.xml"))
    parser.add_argument("--status", type=Path, default=Path("public/status.json"))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--category-map", type=Path, default=Path("translations/categories-sk.csv"))
    parser.add_argument("--name-map", type=Path, default=Path("translations/product-names-sk.csv"))
    parser.add_argument("--allegro-preview", type=Path, default=Path("build/allegro-preview.csv"))
    parser.add_argument("--allegro-markup", type=Decimal, default=DEFAULT_ALLEGRO_MARKUP)
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")

    with tempfile.TemporaryDirectory() as temp_dir:
        source = args.source
        if source is None:
            url = os.environ.get("SOURCE_FEED_URL")
            if not url:
                raise SystemExit("SOURCE_FEED_URL is required when --source is omitted")
            source = Path(temp_dir) / "supplier.xml"
            download(url, source)

        selected, in_stock = choose(source, args.limit)
        rate = exchange_rate()
        count = write_feed(
            source,
            args.output,
            selected,
            rate,
            load_category_map(args.category_map),
            load_name_map(args.name_map),
        )
        allegro_counts = write_allegro_preview(
            source, args.allegro_preview, rate, args.allegro_markup
        )

    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "products": count,
                "in_stock_source_products": in_stock,
                "limit": args.limit,
                "language": "pl",
                "pln_per_eur": str(rate),
                "allegro_preview": {
                    **allegro_counts,
                    "markup_percent": str(args.allegro_markup),
                    "live_sync": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {count} products to {args.output}")


if __name__ == "__main__":
    main()
