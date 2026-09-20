import json
import unittest
from pathlib import Path


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "recon_app"
    / "reference"
    / "fund_category_catalog.json"
)


class FundCategoryCatalogTests(unittest.TestCase):
    def test_course_catalog_is_complete_unique_and_not_auto_enabled(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        items = [item for group in catalog["categories"] for item in group["items"]]
        self.assertEqual(len(catalog["categories"]), 7)
        self.assertEqual(len(items), 37)
        self.assertEqual(len({item["code"] for item in items}), 37)
        self.assertFalse(catalog["autoMatchEnabled"])
        self.assertIn("禁止据此自动记账或自动开票", catalog["warning"])


if __name__ == "__main__":
    unittest.main()
