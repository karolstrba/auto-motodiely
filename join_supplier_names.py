#!/usr/bin/env python3
"""Join supplier names to an already selected Shoptet catalog.

The selected Shoptet export drives the output. Supplier-only products are never
emitted, so this tool cannot expand the merchant's curated assortment.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

GENERIC = re.compile(
    r"\b(alebo diel|motorový diel|diel podvozka|brzdový diel|elektrický diel|diel chladenia|"
    r"diel pohonu|diel riadenia|cyklistický produkt|diel palivovej sústavy)\b",
    re.I,
)


def supplier_index(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], set[str], set[str]]:
    by_code: dict[str, dict[str, str]] = {}
    by_ean: dict[str, dict[str, str]] = {}
    duplicate_codes: set[str] = set()
    duplicate_eans: set[str] = set()
    for _, product in ET.iterparse(path, events=("end",)):
        if product.tag != "product":
            continue
        row = {
            "supplier_id": product.attrib.get("id", "").strip(),
            "supplier_code": (product.findtext("kod") or product.findtext("symbol") or "").strip(),
            "supplier_ean": (product.findtext("ean") or "").strip(),
            "supplier_name_pl": (product.findtext("name") or "").strip(),
            "supplier_brand": (product.findtext("marka") or "").strip(),
            "supplier_category_pl": (product.findtext("category") or "").strip().replace(" / ", " > "),
        }
        for key, index, duplicates in (
            (row["supplier_code"], by_code, duplicate_codes),
            (row["supplier_ean"], by_ean, duplicate_eans),
        ):
            if not key:
                continue
            if key in index:
                duplicates.add(key)
            else:
                index[key] = row
        product.clear()
    for key in duplicate_codes:
        by_code.pop(key, None)
    for key in duplicate_eans:
        by_ean.pop(key, None)
    return by_code, by_ean, duplicate_codes, duplicate_eans


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("selected_export", type=Path)
    parser.add_argument("supplier_feed", type=Path)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    args.matches.parent.mkdir(parents=True, exist_ok=True)
    args.review.parent.mkdir(parents=True, exist_ok=True)
    by_code, by_ean, duplicate_codes, duplicate_eans = supplier_index(args.supplier_feed)
    stats: collections.Counter[str] = collections.Counter()
    fields = (
        "shop_code", "shop_ean", "shop_name", "shop_manufacturer", "shop_default_category",
        "match_method", "supplier_id", "supplier_code", "supplier_ean", "supplier_name_pl",
        "supplier_brand", "supplier_category_pl",
    )
    with args.matches.open("w", encoding="utf-8", newline="") as matched_file, args.review.open("w", encoding="utf-8", newline="") as review_file:
        matched_writer = csv.DictWriter(matched_file, fieldnames=fields)
        review_writer = csv.DictWriter(review_file, fieldnames=fields + ("problem",))
        matched_writer.writeheader()
        review_writer.writeheader()
        for _, item in ET.iterparse(args.selected_export, events=("end",)):
            if item.tag != "SHOPITEM":
                continue
            stats["selected_products"] += 1
            code = (item.findtext("CODE") or "").strip()
            ean = (item.findtext("EAN") or "").strip()
            name = (item.findtext("NAME") or "").strip()
            code_match = by_code.get(code)
            ean_match = by_ean.get(ean) if ean else None
            conflict = bool(code_match and ean_match and code_match["supplier_id"] != ean_match["supplier_id"])
            match = None if conflict else code_match or ean_match
            method = "code" if code_match and not conflict else "ean" if ean_match and not conflict else ""
            base = {
                "shop_code": code,
                "shop_ean": ean,
                "shop_name": name,
                "shop_manufacturer": (item.findtext("MANUFACTURER") or "").strip(),
                "shop_default_category": (item.findtext("./CATEGORIES/DEFAULT_CATEGORY") or "").strip(),
                "match_method": method,
                **(match or {key: "" for key in fields if key.startswith("supplier_")}),
            }
            if match:
                matched_writer.writerow(base)
                stats["matched"] += 1
                stats[f"matched_by_{method}"] += 1
                if GENERIC.search(name):
                    stats["generic_matched"] += 1
            else:
                problem = "code_ean_conflict" if conflict else "no_unique_match"
                review_writer.writerow({**base, "problem": problem})
                stats[problem] += 1
                if GENERIC.search(name):
                    stats["generic_unmatched"] += 1
            item.clear()
    args.summary.write_text(
        json.dumps(
            {
                **stats,
                "supplier_unique_codes": len(by_code),
                "supplier_unique_eans": len(by_ean),
                "supplier_duplicate_codes": len(duplicate_codes),
                "supplier_duplicate_eans": len(duplicate_eans),
                "safety": "selected-export-driven; supplier-only products are never emitted",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
