#!/usr/bin/env python3
"""Stream a Shoptet export and summarize category quality without loading it into RAM."""

from __future__ import annotations

import argparse
import collections
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

POLISH = re.compile(r"[ąćęłńóśźż]|\b(?:pozostałe|układ|części|zestawy|łożyska|przód|tył|odzież|silnik|nadwozie|kierownice|sprzęgło|uszczelki)\b", re.I)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xml", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    categories: collections.Counter[str] = collections.Counter()
    defaults: collections.Counter[str] = collections.Counter()
    product_count = 0
    multi_category = 0
    samples: dict[str, list[dict[str, str]]] = collections.defaultdict(list)

    for _, item in ET.iterparse(args.xml, events=("end",)):
        if item.tag != "SHOPITEM":
            continue
        product_count += 1
        name = (item.findtext("NAME") or "").strip()
        code = (item.findtext("CODE") or "").strip()
        paths = [(node.text or "").strip() for node in item.findall("./CATEGORIES/CATEGORY")]
        default = (item.findtext("./CATEGORIES/DEFAULT_CATEGORY") or "").strip()
        multi_category += len(paths) > 1
        for path in paths:
            categories[path] += 1
            if len(samples[path]) < 3:
                samples[path].append({"code": code, "name": name})
        if default:
            defaults[default] += 1
        item.clear()

    top_levels = collections.Counter()
    for path, count in categories.items():
        top_levels[path.split(" > ", 1)[0]] += count

    report = {
        "products": product_count,
        "unique_category_paths": len(categories),
        "products_in_multiple_categories": multi_category,
        "top_levels": top_levels.most_common(),
        "obvious_polish_category_paths": sum(bool(POLISH.search(path)) for path in categories),
        "categories": [
            {
                "path": path,
                "product_assignments": count,
                "default_assignments": defaults[path],
                "obvious_polish": bool(POLISH.search(path)),
                "samples": samples[path],
            }
            for path, count in categories.most_common()
        ],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
