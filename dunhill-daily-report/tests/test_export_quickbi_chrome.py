import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts.export_quickbi_chrome import QUICKBI_SOURCES, quickbi_action_code


class QuickBIMcpRoutingTests(unittest.TestCase):
    def test_dtc_order_uses_threshold_based_mcp_export(self):
        source = QUICKBI_SOURCES["dtc_order"]

        self.assertEqual(source["prefix"], "BI_dtc_t01_trade_order_line")
        self.assertFalse(source.get("force_export", False))
        self.assertIn("04bdfcf3-c547-42a5-8a43-3a80264ff3d1", source["url"])

    def test_dtc_refund_uses_threshold_based_mcp_export(self):
        source = QUICKBI_SOURCES["dtc_refund"]

        self.assertEqual(
            source["prefix"],
            "BI_dtc_t01_trade_refund_info_allsuc_filter",
        )
        self.assertFalse(source.get("force_export", False))
        self.assertIn("b08a2190-66d7-4004-8ca0-9a6a92857dff", source["url"])

    def test_generated_browser_action_skips_at_or_below_50_rows(self):
        code = quickbi_action_code(
            {
                "label": "test",
                "prefix": "BI_test",
                "url": "https://example.test",
            },
            "create",
        )

        self.assertIn("rowInfo.rows <= 50", code)
        self.assertIn("Step 2 crawler can capture it completely", code)


if __name__ == "__main__":
    unittest.main()
