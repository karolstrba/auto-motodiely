import unittest

from amio_merge import add_sale_prices, merge_payloads, parse_csv, selling_price


class AmioMergeTests(unittest.TestCase):
    def test_merges_parts_with_one_header_and_removes_exact_duplicates(self):
        first = b"sku;name;stock\nA1;Alpha;2\nA2;Beta;0\n"
        second = b"sku;name;stock\nA2;Beta;0\nA3;Gamma;5\n"
        header, rows, delimiter = merge_payloads([first, second])
        self.assertEqual(header, ["sku", "name", "stock"])
        self.assertEqual(delimiter, ";")
        self.assertEqual(
            rows,
            [["A1", "Alpha", "2"], ["A2", "Beta", "0"], ["A3", "Gamma", "5"]],
        )

    def test_accepts_utf8_bom_and_quoted_delimiter(self):
        header, rows, delimiter = parse_csv(
            "\ufeffsku;name\nA1;\"Pneu; predna\"\n".encode("utf-8")
        )
        self.assertEqual(header, ["sku", "name"])
        self.assertEqual(rows, [["A1", "Pneu; predna"]])
        self.assertEqual(delimiter, ";")

    def test_rejects_different_headers(self):
        with self.assertRaisesRegex(ValueError, "different CSV headers"):
            merge_payloads([b"sku;name\nA;One\n", b"code;name\nB;Two\n"])

    def test_selling_price_tiers_and_rounding(self):
        cases = {
            "4.81": "8.18",
            "10": "17.00",
            "10.01": "16.02",
            "20": "32.00",
            "20.01": "30.02",
            "30": "45.00",
            "30.01": "42.01",
            "50": "70.00",
            "50.01": "65.01",
            "100": "130.00",
            "100.01": "125.01",
            "200": "250.00",
            "200.01": "240.01",
            "": "",
        }
        for purchase, expected in cases.items():
            with self.subTest(purchase=purchase):
                self.assertEqual(selling_price(purchase), expected)

    def test_adds_sale_price_after_purchase_price(self):
        header, rows = add_sale_prices(
            ["SKU", "Price", "Name"],
            [["A1", "4.81", "Adapter"], ["A2", "0,92", "Light"]],
        )
        self.assertEqual(header, ["SKU", "Price", "SalePrice", "Name"])
        self.assertEqual(
            rows,
            [["A1", "4.81", "8.18", "Adapter"], ["A2", "0,92", "1.56", "Light"]],
        )


if __name__ == "__main__":
    unittest.main()
