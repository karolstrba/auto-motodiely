#!/usr/bin/env python3
"""Build a dynamic, stock-only AMDPRO supplier feed."""

from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIMIT = 44_000
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


def write_feed(source: Path, destination: Path, selected: set[str]) -> int:
    product_pattern = re.compile(
        rb"<product\s+id=([\"'])([^\"']+)\1>.*?</product>\s*", re.S
    )
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    count = 0
    with temporary.open("wb") as output:
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<xml>\n')
        for match in product_pattern.finditer(data):
            if match.group(2).decode("utf-8") in selected:
                output.write(match.group(0))
                count += 1
        output.write(b"</xml>\n")
    if count != len(selected):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Selected {len(selected)} products, wrote {count}")
    ET.parse(temporary)
    temporary.replace(destination)
    return count


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
        count = write_feed(source, args.output, selected)

    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "products": count,
                "in_stock_source_products": in_stock,
                "limit": args.limit,
                "language": "pl",
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
