#!/usr/bin/env python3
"""Create a private translation inventory from the supplier feed."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "AMDPRO-translation-audit/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        destination.write_bytes(response.read())


def audit(source: Path, output: Path, categories: Path) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    category_counts: Counter[str] = Counter()
    count = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("supplier_id", "code", "name_pl", "brand", "category_pl"),
        )
        writer.writeheader()
        for _, product in ET.iterparse(source, events=("end",)):
            if product.tag != "product":
                continue
            supplier_id = product.attrib.get("id", "").strip()
            code = (
                (product.findtext("kod") or "").strip()
                or (product.findtext("symbol") or "").strip()
                or supplier_id
            )
            name = (product.findtext("name") or "").strip()
            brand = (product.findtext("marka") or "").strip()
            category = (product.findtext("category") or "").strip().replace(" / ", " > ")
            writer.writerow(
                {
                    "supplier_id": supplier_id,
                    "code": code,
                    "name_pl": name,
                    "brand": brand,
                    "category_pl": category,
                }
            )
            category_counts[category] += 1
            count += 1
            product.clear()

    with categories.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("category_pl", "products"))
        writer.writerows(category_counts.most_common())
    return count, len(category_counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("audit/products-for-translation.csv"))
    parser.add_argument("--categories", type=Path, default=Path("audit/categories-for-translation.csv"))
    args = parser.parse_args()
    url = os.environ.get("SOURCE_FEED_URL")
    if not url:
        raise SystemExit("SOURCE_FEED_URL is required")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "supplier.xml"
        download(url, source)
        products, categories = audit(source, args.output, args.categories)
    print(f"Audited {products} products in {categories} categories")


if __name__ == "__main__":
    main()
