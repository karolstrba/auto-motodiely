import tempfile, unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from motomaniak_update import build_feed, category_for, markup, round_up_to_90, selling_price, stock_amount

STOCK = """Nr_katalogowy;Cena_brutto;Ilosc_produktow
A;40.00;>30
B;100.00;0.00
"""
CATALOG = """Nr_katalogowy;Kod_ean;Cena_brutto;Nazwa_produktu;Opis;Producent;Zdjecie_glowne;Status;Kategoria_1_nazwa;Kategoria_2_nazwa;Kategoria_3_nazwa
A;12345678;40.00;Klocki hamulcowe;opis;X;https://example.com/a.jpg;tak;DO QUADÓW;HAMULCE;KLOCKI HAMULCOWE
B;;100.00;Nieznany element;opis;Y;;tak;DO QUADÓW;;
"""

class MotoManiakTest(unittest.TestCase):
 def test_prices(self):
  expected=[("10","0.70"),("20","0.60"),("30","0.50"),("50","0.40"),("100","0.30"),("200","0.25"),("201","0.20")]
  for cost,rate in expected: self.assertEqual(markup(Decimal(cost)),Decimal(rate))
  self.assertEqual(selling_price(Decimal("40"),Decimal("4")),Decimal("17.90"))
  self.assertEqual(round_up_to_90(Decimal("24.95")),Decimal("25.90"))
 def test_stock(self):
  self.assertEqual(stock_amount(">30"),Decimal("30")); self.assertEqual(stock_amount("0.00"),Decimal("0.00"))
 def test_complete_feed(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); catalog=d/"catalog.csv"; stock=d/"stock.csv"; output=d/"feed.xml"
   catalog.write_text(CATALOG,encoding="utf-8"); stock.write_text(STOCK,encoding="utf-8")
   counts=build_feed(catalog,stock,output,Decimal("4")); items=ET.parse(output).getroot().findall("SHOPITEM")
   self.assertEqual(counts["products"],2); self.assertEqual(counts["visible"],1); self.assertEqual(counts["hidden"],1)
   self.assertEqual(items[0].findtext("CODE"),"MM-A"); self.assertEqual(items[0].findtext("STOCK/AMOUNT"),"30")
   self.assertIn("Brzdové platničky",items[0].findtext("NAME")); self.assertNotIn("Klocki",items[0].findtext("NAME"))
   self.assertEqual(items[1].findtext("VISIBILITY"),"hidden")
 def test_existing_category(self):
  target,specific=category_for({"Nazwa_produktu":"Sworzeń wahacza","Kategoria_1_nazwa":"DO QUADÓW"})
  self.assertTrue(specific); self.assertEqual(target,"ATV/UTV diely / Riadenie a podvozok / Guľové čapy")

if __name__=="__main__": unittest.main()
