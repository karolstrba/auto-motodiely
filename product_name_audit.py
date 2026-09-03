#!/usr/bin/env python3
"""Report suspicious Shoptet product names for manual or controlled correction."""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

POLISH_CHARS = re.compile(r"[ąćęłńśźż]", re.I)
POLISH_WORDS = re.compile(r"\b(części|pozostałe|przód|tył|łożysk|zestaw|układ|odzież|kierownic|sprzęgł|uszczelk|nowa|kolor|rozmiar)\w*\b", re.I)
GENERIC = re.compile(r"\b(alebo diel|motorový diel|diel podvozka|brzdový diel|elektrický diel|diel chladenia|diel pohonu|diel riadenia|cyklistický produkt)\b", re.I)
NUMBERED = re.compile(r"^\s*\d{1,3}[.)]\s*")


def issues(name: str) -> list[str]:
    found = []
    letters = [c for c in name if c.isalpha()]
    if POLISH_CHARS.search(name) or POLISH_WORDS.search(name):
        found.append("possible_polish")
    if GENERIC.search(name):
        found.append("generic_name")
    if NUMBERED.search(name):
        found.append("numbered_prefix")
    if "!!!" in name or re.search(r"\bnov[aý]\s*!", name, re.I):
        found.append("marketing_noise")
    if len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.85:
        found.append("all_caps")
    if len(name.strip()) < 8:
        found.append("too_short")
    if len(name) > 250:
        found.append("too_long")
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts: collections.Counter[str] = collections.Counter()
    products = flagged = 0
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("code", "name", "manufacturer", "issues", "default_category"))
        writer.writeheader()
        for _, item in ET.iterparse(args.source, events=("end",)):
            if item.tag != "SHOPITEM":
                continue
            products += 1
            name = (item.findtext("NAME") or "").strip()
            found = issues(name)
            if found:
                flagged += 1
                counts.update(found)
                writer.writerow({
                    "code": (item.findtext("CODE") or "").strip(),
                    "name": name,
                    "manufacturer": (item.findtext("MANUFACTURER") or "").strip(),
                    "issues": "|".join(found),
                    "default_category": (item.findtext("./CATEGORIES/DEFAULT_CATEGORY") or "").strip(),
                })
            item.clear()
    args.summary.write_text(json.dumps({"products": products, "flagged_products": flagged, "issues": counts.most_common()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
