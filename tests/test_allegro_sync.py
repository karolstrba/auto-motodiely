import tempfile
import unittest
from pathlib import Path

from allegro_sync import USER_AGENT, load_preview


class AllegroSyncTest(unittest.TestCase):
    def test_user_agent_identifies_the_integration(self):
        self.assertIn("AMDPRO-Allegro-Sync", USER_AGENT)
        self.assertIn("https://amdpro.eu", USER_AGENT)

    def test_load_preview_is_keyed_by_sku(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.csv"
            path.write_text("sku,quantity,price_eur_plus_10pct\nABC,4,12.50\n", encoding="utf-8")
            self.assertEqual(load_preview(path)["ABC"]["quantity"], "4")


if __name__ == "__main__":
    unittest.main()
