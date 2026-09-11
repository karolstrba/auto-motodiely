#!/usr/bin/env python3
"""Merge the five public AMIO Base CSV parts into one stable feed."""

from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL_TEMPLATE = "https://amio-base-feed.vercel.app/api/feed?part={part}"


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
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Merged {len(rows)} AMIO rows from {args.parts} parts into {args.output}")


if __name__ == "__main__":
    main()
