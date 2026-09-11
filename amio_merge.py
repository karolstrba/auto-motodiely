#!/usr/bin/env python3
"""Merge the five public AMIO Base CSV parts into one stable feed."""

from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DEFAULT_URL_TEMPLATE = "https://amio-base-feed.vercel.app/api/feed?part={part}"

MARKUPS = (
    (Decimal("10"), Decimal("0.70")),
    (Decimal("20"), Decimal("0.60")),
    (Decimal("30"), Decimal("0.50")),
    (Decimal("50"), Decimal("0.40")),
    (Decimal("100"), Decimal("0.30")),
    (Decimal("200"), Decimal("0.25")),
)
MARKUP_ABOVE_200 = Decimal("0.20")


def parse_csv(payload: bytes) -> tuple[list[str], list[list[str]], str]:
    text = payload.decode("utf-8-sig")
    sample = text[:65536]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ";"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows or not rows[0]:
        raise ValueError("AMIO part is empty or has no CSV header")
    header = rows[0]
    body = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    for number, row in enumerate(body, start=2):
        if len(row) != len(header):
            raise ValueError(
                f"CSV row {number} has {len(row)} columns; expected {len(header)}"
            )
    return header, body, delimiter


def merge_payloads(payloads: list[bytes]) -> tuple[list[str], list[list[str]], str]:
    if not payloads:
        raise ValueError("No AMIO parts supplied")
    header: list[str] | None = None
    delimiter: str | None = None
    merged: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for payload in payloads:
        part_header, rows, part_delimiter = parse_csv(payload)
        if header is None:
            header, delimiter = part_header, part_delimiter
        elif part_header != header:
            raise ValueError("AMIO parts have different CSV headers")
        for row in rows:
            key = tuple(row)
            if key not in seen:
                seen.add(key)
                merged.append(row)
    return header or [], merged, delimiter or ";"


def selling_price(purchase_price: str) -> str:
    raw = purchase_price.strip()
    if not raw:
        return ""
    try:
        price = Decimal(raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid AMIO purchase price: {purchase_price!r}") from exc
    if price < 0:
        raise ValueError(f"Negative AMIO purchase price: {purchase_price!r}")
    markup = MARKUP_ABOVE_200
    for limit, candidate in MARKUPS:
        if price <= limit:
            markup = candidate
            break
    return str((price * (Decimal("1") + markup)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def add_sale_prices(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    try:
        purchase_index = header.index("Price")
    except ValueError as exc:
        raise ValueError("AMIO feed has no Price column") from exc

    if "SalePrice" in header:
        sale_index = header.index("SalePrice")
        output_header = list(header)
        output_rows = [list(row) for row in rows]
        for row in output_rows:
            row[sale_index] = selling_price(row[purchase_index])
        return output_header, output_rows

    sale_index = purchase_index + 1
    output_header = list(header)
    output_header.insert(sale_index, "SalePrice")
    output_rows = []
    for row in rows:
        output_row = list(row)
        output_row.insert(sale_index, selling_price(row[purchase_index]))
        output_rows.append(output_row)
    return output_header, output_rows


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AMDPRO-AMIO-merge/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-template", default=DEFAULT_URL_TEMPLATE)
    parser.add_argument("--parts", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("public/amio-base-feed.csv"))
    parser.add_argument(
        "--status", type=Path, default=Path("public/amio-base-feed-status.json")
    )
    args = parser.parse_args()
    if args.parts < 1:
        raise SystemExit("--parts must be positive")

    payloads = [download(args.url_template.format(part=part)) for part in range(1, args.parts + 1)]
    header, rows, delimiter = merge_payloads(payloads)
    header, rows = add_sale_prices(header, rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)

    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "parts": args.parts,
                "products": len(rows),
                "delimiter": delimiter,
                "output": args.output.name,
                "purchase_price_column": "Price",
                "sale_price_column": "SalePrice",
                "vat_added": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Merged {len(rows)} AMIO rows from {args.parts} parts into {args.output}; "
        "added SalePrice from the agreed tiered markups"
    )


if __name__ == "__main__":
    main()
