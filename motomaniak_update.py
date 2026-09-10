#!/usr/bin/env python3
"""Build a Shoptet update feed from Moto-Maniak's hourly CSV."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

SOURCE_URL = "https://www.moto-maniak.eu/xml/stanymag12.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def decimal(value: str | None) -> Decimal:
    try:
        return Decimal((value or "0").strip().replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def stock_amount(value: str | None) -> Decimal:
    text = (value or "0").strip()
    if text.startswith(">"):
        return max(Decimal("0"), decimal(text[1:]))
    return max(Decimal("0"), decimal(text))


def markup(cost_eur: Decimal) -> Decimal:
    if cost_eur <= Decimal("10"):
        return Decimal("0.70")
    if cost_eur <= Decimal("20"):
        return Decimal("0.60")
    if cost_eur <= Decimal("30"):
        return Decimal("0.50")
    if cost_eur <= Decimal("50"):
        return Decimal("0.40")
    if cost_eur <= Decimal("100"):
        return Decimal("0.30")
    if cost_eur <= Decimal("200"):
        return Decimal("0.25")
    return Decimal("0.20")


def round_up_to_90(value: Decimal) -> Decimal:
    euros = value.to_integral_value(rounding=ROUND_CEILING) - 1
    candidate = euros + Decimal("0.90")
    if candidate < value:
        candidate += Decimal("1.00")
    return candidate.quantize(Decimal("0.01"))


def selling_price(gross_pln: Decimal, pln_per_eur: Decimal) -> Decimal:
    if gross_pln <= 0 or pln_per_eur <= 0:
        return Decimal("0")
    cost_eur = gross_pln / pln_per_eur
    return round_up_to_90(cost_eur * (Decimal("1") + markup(cost_eur)))


def exchange_rate() -> Decimal:
    override = os.environ.get("PLN_PER_EUR")
    if override and decimal(override) > 0:
        return decimal(override)
    request = urllib.request.Request(ECB_URL, headers={"User-Agent": "AMDPRO-feed/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    for node in root.iter():
        if node.attrib.get("currency") == "PLN":
            rate = decimal(node.attrib.get("rate"))
            if rate > 0:
                return rate
    raise RuntimeError("ECB response does not contain a PLN rate")


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "AMDPRO-feed/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 200:
            raise RuntimeError(f"Supplier returned HTTP {response.status}")
        destination.write_bytes(response.read())


def build_feed(source: Path, destination: Path, pln_per_eur: Decimal) -> dict[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    counts = {"products": 0, "visible": 0, "hidden": 0, "invalid": 0}
    with source.open(encoding="utf-8-sig", newline="") as handle, temporary.open("wb") as output:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"Nr_katalogowy", "Cena_brutto", "Ilosc_produktow"}
        if not required.issubset(reader.fieldnames or []):
            raise RuntimeError("Supplier CSV is missing required columns")
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<SHOP>\n')
        for row in reader:
            code = (row.get("Nr_katalogowy") or "").strip()
            gross_pln = decimal(row.get("Cena_brutto"))
            if not code or gross_pln <= 0:
                counts["invalid"] += 1
                continue
            amount = stock_amount(row.get("Ilosc_produktow"))
            visible = amount > 0
            item = ET.Element("SHOPITEM")
            ET.SubElement(item, "CODE").text = code[:64]
            ET.SubElement(item, "PRICE_VAT").text = f"{selling_price(gross_pln, pln_per_eur):.2f}"
            ET.SubElement(item, "CURRENCY").text = "EUR"
            ET.SubElement(item, "VISIBILITY").text = "visible" if visible else "hidden"
            stock = ET.SubElement(item, "STOCK")
            ET.SubElement(stock, "AMOUNT").text = str(amount.quantize(Decimal("1")))
            ET.SubElement(item, "AVAILABILITY_IN_STOCK").text = "Skladom"
            ET.SubElement(item, "AVAILABILITY_OUT_OF_STOCK").text = "Momentálne nedostupné"
            output.write(ET.tostring(item, encoding="utf-8"))
            output.write(b"\n")
            counts["products"] += 1
            counts["visible" if visible else "hidden"] += 1
        output.write(b"</SHOP>\n")
    ET.parse(temporary)
    temporary.replace(destination)
    return counts


def main() -> None:
    output = Path("public/motomaniak-update.xml")
    status = Path("public/motomaniak-status.json")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "stanymag12.csv"
        download(os.environ.get("MOTOMANIAK_STOCK_URL", SOURCE_URL), source)
        rate = exchange_rate()
        counts = build_feed(source, output, rate)
    status.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "Moto-Maniak hourly stock CSV",
                "pln_per_eur": str(rate),
                "price_vat_added_again": False,
                "rounding": "up to next EUR price ending .90",
                **counts,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {counts['products']} products to {output}")


if __name__ == "__main__":
    main()
