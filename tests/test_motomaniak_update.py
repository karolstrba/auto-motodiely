import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from motomaniak_update import build_feed, markup, round_up_to_90, selling_price, stock_amount


CSV = """Nr_katalogowy;Cena_brutto;Id_produktu_magazyn;Ilosc_produktow;Nazwa_produktu;Producent;Vat;Cena_netto
A;40.00;;>30;A;X;23.00;32.52
B;100.00;;0.00;B;X;23.00;81.30
"""


class MotoManiakUpdateTest(unittest.TestCase):
    def test_markup_bands(self):
        expected = [("10", "0.70"), ("20", "0.60"), ("30", "0.50"), ("50", "0.40"), ("100", "0.30"), ("200", "0.25"), ("201", "0.20")]
        for cost, rate in expected:
            self.assertEqual(markup(Decimal(cost)), Decimal(rate))

    def test_rounding_is_never_down(self):
        self.assertEqual(round_up_to_90(Decimal("24.03")), Decimal("24.90"))
        self.assertEqual(round_up_to_90(Decimal("24.90")), Decimal("24.90"))
        self.assertEqual(round_up_to_90(Decimal("24.95")), Decimal("25.90"))

    def test_price_uses_gross_pln_without_second_vat(self):
        self.assertEqual(selling_price(Decimal("40"), Decimal("4")), Decimal("17.90"))

    def test_stock_parser_handles_supplier_cap(self):
        self.assertEqual(stock_amount(">30"), Decimal("30"))
        self.assertEqual(stock_amount("0.00"), Decimal("0.00"))

    def test_feed_hides_zero_stock(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            output = Path(directory) / "feed.xml"
            source.write_text(CSV, encoding="utf-8")
            counts = build_feed(source, output, Decimal("4"))
            self.assertEqual(counts, {"products": 2, "visible": 1, "hidden": 1, "invalid": 0})
            items = ET.parse(output).getroot().findall("SHOPITEM")
            self.assertEqual(items[0].findtext("CODE"), "MM-A")\n            self.assertEqual(items[0].findtext("STOCK/AMOUNT"), "30")
            self.assertEqual(items[0].findtext("VISIBILITY"), "visible")
            self.assertEqual(items[1].findtext("VISIBILITY"), "hidden")


if __name__ == "__main__":
    unittest.main()
