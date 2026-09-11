import unittest

from amio_merge import merge_payloads, parse_csv


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


if __name__ == "__main__":
    unittest.main()
