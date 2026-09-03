#!/usr/bin/env python3
"""Create a small, deterministic Shoptet import sample from a full export.

The source SHOPITEM elements are copied without intentionally changing their
contents. Selection favours category diversity and also includes products that
exercise sale, multi-category, out-of-stock, and hidden-product behaviour.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


ROOTS = ("Motodiely", "ATV/UTV", "Oblečenie", "Výstroj", "Príslušenstvo a náradie")
DEFAULT_CODES = ("HF204", "HE169L", "BBC-01G", "24-1069", "CS-03RD", "ESK-201")


def txt(node: ET.Element, path: str) -> str:
    value = node.findtext(path)
    return value.strip() if value else ""


def decimal(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


@dataclass(frozen=True)
class Product:
    order: int
    item_id: str
    code: str
    name: str
    default_category: str
    categories: tuple[str, ...]
    visibility: str
    amount: float | None
    price_vat: str

    @property
    def root(self) -> str:
        return self.default_category.split(" > ", 1)[0]

    @property
    def sale(self) -> bool:
        return any(c == "Výpredaj" or c.startswith("Výpredaj > ") for c in self.categories)

    @property
    def multi_category(self) -> bool:
        return len(self.categories) > 1

    @property
    def unavailable(self) -> bool:
        return self.amount is not None and self.amount <= 0

    @property
    def hidden(self) -> bool:
        return self.visibility.lower() not in {"", "visible", "1", "true"}


def product_from(item: ET.Element, order: int) -> Product:
    categories_node = item.find("CATEGORIES")
    categories: list[str] = []
    default_category = ""
    if categories_node is not None:
        categories = [((n.text or "").strip()) for n in categories_node.findall("CATEGORY")]
        categories = [c for c in categories if c]
        default_category = txt(categories_node, "DEFAULT_CATEGORY")
    visibility = txt(item, "VISIBILITY") or txt(item, "VISIBLE")
    return Product(
        order=order,
        item_id=item.get("id", ""),
        code=txt(item, "CODE"),
        name=txt(item, "NAME"),
        default_category=default_category,
        categories=tuple(categories),
        visibility=visibility,
        amount=decimal(txt(item, "STOCK/AMOUNT")),
        price_vat=txt(item, "PRICE_VAT"),
    )


def scan(path: Path) -> list[Product]:
    products: list[Product] = []
    order = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "SHOPITEM":
            continue
        products.append(product_from(elem, order))
        order += 1
        elem.clear()
    return products


def select(products: list[Product], limit: int, per_root: int, feature_limit: int,
           wanted_codes: tuple[str, ...]) -> tuple[set[int], dict[int, set[str]]]:
    chosen: set[int] = set()
    reasons: dict[int, set[str]] = defaultdict(set)

    def add(p: Product, reason: str, ignore_limit: bool = False) -> bool:
        if len(chosen) >= limit and not ignore_limit:
            return False
        chosen.add(p.order)
        reasons[p.order].add(reason)
        return True

    wanted_upper = {c.upper() for c in wanted_codes}
    for p in products:
        if p.code.upper() in wanted_upper:
            add(p, "known_code", ignore_limit=True)

    # First cover as many distinct default categories as possible per main root.
    root_counts: Counter[str] = Counter()
    seen_leaf: set[str] = set()
    for p in products:
        if p.root not in ROOTS or root_counts[p.root] >= per_root:
            continue
        if not p.default_category or p.default_category in seen_leaf:
            continue
        if add(p, "category_diversity"):
            root_counts[p.root] += 1
            seen_leaf.add(p.default_category)

    feature_checks = (
        ("sale", lambda p: p.sale),
        ("multi_category", lambda p: p.multi_category),
        ("unavailable", lambda p: p.unavailable),
        ("hidden", lambda p: p.hidden),
        ("unexpected_root", lambda p: bool(p.root) and p.root not in ROOTS),
    )
    for reason, check in feature_checks:
        count = 0
        for p in products:
            if not check(p):
                continue
            before = len(chosen)
            if not add(p, reason):
                break
            reasons[p.order].add(reason)
            if len(chosen) > before:
                count += 1
            if count >= feature_limit:
                break

    # Fill the remaining capacity while balancing the five roots.
    for p in products:
        if len(chosen) >= limit:
            break
        if p.root in ROOTS:
            add(p, "balanced_fill")

    return chosen, reasons


def write_sample(source: Path, output: Path, chosen: set[int]) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    order = 0
    with output.open("wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
        for _, elem in ET.iterparse(source, events=("end",)):
            if elem.tag != "SHOPITEM":
                continue
            if order in chosen:
                fh.write(ET.tostring(elem, encoding="utf-8", short_empty_elements=True))
                fh.write(b"\n")
                count += 1
            order += 1
            elem.clear()
        fh.write(b"</SHOP>\n")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--limit", type=int, default=220)
    parser.add_argument("--per-root", type=int, default=35)
    parser.add_argument("--feature-limit", type=int, default=10)
    parser.add_argument("--codes", nargs="*", default=list(DEFAULT_CODES))
    args = parser.parse_args()

    manifest = args.manifest or args.output.with_name(args.output.stem + "-manifest.csv")
    summary_path = args.summary or args.output.with_name(args.output.stem + "-summary.json")
    products = scan(args.source)
    chosen, reasons = select(products, args.limit, args.per_root, args.feature_limit, tuple(args.codes))
    selected = [p for p in products if p.order in chosen]
    written = write_sample(args.source, args.output, chosen)

    missing_required = Counter()
    for p in selected:
        for field, value in (("CODE", p.code), ("NAME", p.name),
                             ("DEFAULT_CATEGORY", p.default_category), ("PRICE_VAT", p.price_vat)):
            if not value:
                missing_required[field] += 1

    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(("id", "code", "name", "default_category", "categories",
                         "amount", "visibility", "reasons"))
        for p in selected:
            writer.writerow((p.item_id, p.code, p.name, p.default_category, " | ".join(p.categories),
                             "" if p.amount is None else p.amount, p.visibility,
                             " | ".join(sorted(reasons[p.order]))))

    summary = {
        "source_products": len(products),
        "selected_products": len(selected),
        "written_products": written,
        "roots": dict(sorted(Counter(p.root for p in selected).items())),
        "features": {
            "sale": sum(p.sale for p in selected),
            "multi_category": sum(p.multi_category for p in selected),
            "unavailable": sum(p.unavailable for p in selected),
            "hidden": sum(p.hidden for p in selected),
            "unexpected_root": sum(bool(p.root) and p.root not in ROOTS for p in selected),
        },
        "known_codes_found": sorted(p.code for p in selected if p.code.upper() in {c.upper() for c in args.codes}),
        "missing_required_fields": dict(sorted(missing_required.items())),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Final parse is deliberately separate: a malformed output must fail the run.
    parsed = sum(1 for _, elem in ET.iterparse(args.output, events=("end",)) if elem.tag == "SHOPITEM")
    if parsed != written or written != len(selected):
        raise SystemExit(f"Validation failed: selected={len(selected)}, written={written}, parsed={parsed}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
