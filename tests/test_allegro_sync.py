import tempfile
import unittest
from pathlib import Path

from allegro_sync import USER_AGENT, build_draft_payload, build_offer_patch, load_preview, summarize_missing_offers, target_price


class AllegroSyncTest(unittest.TestCase):
    def test_user_agent_identifies_the_integration(self):
        self.assertIn("AMDPRO-Allegro-Sync", USER_AGENT)
        self.assertIn("https://amdpro.eu", USER_AGENT)

    def test_target_price_uses_offer_currency(self):
        row = {"price_pln_plus_10pct": "110.00", "price_eur_plus_10pct": "25.30"}
        self.assertEqual(target_price(row, "PLN"), "110.00")
        self.assertEqual(target_price(row, "EUR"), "25.30")
        self.assertEqual(target_price(row, "USD"), "")

    def test_live_patch_changes_only_price_and_positive_stock(self):
        offer = {
            "publication": {"status": "ACTIVE"},
            "sellingMode": {"price": {"amount": "20.00", "currency": "EUR"}},
            "stock": {"available": 1, "unit": "UNIT"},
        }
        row = {"price_eur_plus_10pct": "25.30", "quantity": "4"}
        self.assertEqual(build_offer_patch(offer, row), {
            "sellingMode": {"price": {"amount": "25.30", "currency": "EUR"}},
            "stock": {"available": 4, "unit": "UNIT"},
        })

    def test_live_patch_skips_zero_stock_and_ended_offers(self):
        offer = {
            "publication": {"status": "ACTIVE"},
            "sellingMode": {"price": {"amount": "20.00", "currency": "EUR"}},
            "stock": {"available": 1, "unit": "UNIT"},
        }
        self.assertEqual(build_offer_patch(offer, {"price_eur_plus_10pct": "25.30", "quantity": "0"}), {})
        offer["publication"]["status"] = "ENDED"
        self.assertEqual(build_offer_patch(offer, {"price_eur_plus_10pct": "25.30", "quantity": "4"}), {})

    def test_draft_payload_is_explicitly_inactive_and_uses_eur_markup(self):
        row = {
            "sku": "ABC-1",
            "ean": "5901234123457",
            "name": "Test product",
            "quantity": "3",
            "price_eur_plus_10pct": "25.30",
            "price_pln_plus_10pct": "110.00",
            "image_urls": "https://example.com/1.jpg|https://example.com/2.jpg",
            "new_offer_status": "ready",
        }
        payload = build_draft_payload(row, "EUR", "65ca51de-3fa0-4e51-88d9-d13a29e3b8ea")
        self.assertEqual(payload["publication"]["status"], "INACTIVE")
        self.assertEqual(payload["external"]["id"], "ABC-1")
        self.assertEqual(payload["productSet"][0]["product"], {"id": "65ca51de-3fa0-4e51-88d9-d13a29e3b8ea"})
        self.assertEqual(payload["sellingMode"]["price"], {"amount": "25.30", "currency": "EUR"})
        self.assertEqual(payload["stock"]["available"], 3)

    def test_draft_payload_rejects_zero_stock(self):
        row = {
            "sku": "ABC-1", "ean": "5901234123457", "name": "Test",
            "quantity": "0", "price_eur_plus_10pct": "25.30",
            "image_urls": "https://example.com/1.jpg", "new_offer_status": "ready",
        }
        self.assertEqual(build_draft_payload(row, "EUR", "65ca51de-3fa0-4e51-88d9-d13a29e3b8ea"), {})

    def test_missing_offer_summary_separates_ready_and_blocked(self):
        preview = {
            "A": {"new_offer_status": "ready", "quantity": "2"},
            "B": {"new_offer_status": "needs_data", "quantity": "1"},
            "C": {"new_offer_status": "ready", "quantity": "0"},
        }
        self.assertEqual(summarize_missing_offers(preview, {"A"}), {
            "feed_products": 3,
            "missing_on_allegro": 2,
            "ready_to_create": 1,
            "blocked_to_create": 1,
            "missing_in_stock": 1,
        })

    def test_load_preview_is_keyed_by_sku(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.csv"
            path.write_text("sku,quantity,price_eur_plus_10pct\nABC,4,12.50\n", encoding="utf-8")
            self.assertEqual(load_preview(path)["ABC"]["quantity"], "4")


if __name__ == "__main__":
    unittest.main()
