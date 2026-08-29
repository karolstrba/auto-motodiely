import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from generator import allegro_price, choose, write_allegro_preview, write_feed


XML = b'''<?xml version="1.0" encoding="utf-8"?>
<xml>
<product id="tyre"><name>Tyre</name><category>Opony / Szosowe</category><price>1</price><quantity>1</quantity></product>
<product id="glove"><name>Glove</name><category>Odziez i ochraniacze</category><price>1</price><quantity>2</quantity></product>
<product id="core"><name>Quality filter</name><category>Filtry / Oleju</category><price>10</price><quantity>4</quantity><ean>1</ean><marka>X</marka><imgs><i url="x"/></imgs></product>
<product id="empty"><name>Empty</name><category>Opony</category><price>1</price><quantity>0</quantity></product>
</xml>'''


class GeneratorTest(unittest.TestCase):
    def test_stock_and_limit_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xml"
            output = Path(directory) / "feed.xml"
            source.write_bytes(XML)
            selected, in_stock = choose(source, 2)
            self.assertEqual(in_stock, 3)
            self.assertEqual(selected, {"tyre", "core"})
            self.assertEqual(write_feed(source, output, selected, Decimal("4")), 2)
            root = ET.parse(output).getroot()
            self.assertEqual(root.tag, "SHOP")
            codes = {node.findtext("CODE") for node in root.findall("SHOPITEM")}
            self.assertEqual(codes, {"tyre", "core"})
            self.assertTrue(all(node.find("STOCK/AMOUNT") is not None for node in root))

    def test_allegro_preview_keeps_zero_stock_and_adds_ten_percent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xml"
            output = Path(directory) / "allegro.csv"
            source.write_bytes(XML)
            counts = write_allegro_preview(source, output, Decimal("4"))
            rows = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(counts["products"], 4)
            self.assertEqual(counts["in_stock"], 3)
            self.assertEqual(len(rows), 5)
            self.assertIn("empty", rows[-1])
            self.assertEqual(allegro_price(Decimal("100"), Decimal("4"), Decimal("10")), Decimal("27.50"))


if __name__ == "__main__":
    unittest.main()
