import unittest

from gpt_payload_compressor import compress_market_summaries_for_gpt


class GPTPayloadCostContextTests(unittest.TestCase):
    def test_cost_context_formats_krw_prices_without_digit_shift(self):
        summaries = [
            {
                "code": "005930",
                "name": "Samsung Electronics",
                "market_snapshot": {"current_price": 357000},
                "validation_signal": {
                    "current_price": 356000,
                    "target_1": 356500,
                    "target_2": 357000,
                    "stop_loss": 350000,
                },
                "timeframes": {},
            }
        ]

        compressed, _ = compress_market_summaries_for_gpt(summaries)
        cost_context = compressed[0]["cost_context"]

        self.assertEqual(cost_context["entry_price"], 356000)
        self.assertEqual(cost_context["entry_price_krw_text"], "356,000 KRW")
        self.assertEqual(cost_context["breakeven_exit_price"], 357104)
        self.assertEqual(
            cost_context["breakeven_exit_price_krw_text"],
            "357,104 KRW",
        )
        self.assertEqual(cost_context["target_1"]["price_krw_text"], "356,500 KRW")
        self.assertEqual(cost_context["target_2"]["price_krw_text"], "357,000 KRW")
        self.assertEqual(cost_context["stop_loss"]["price_krw_text"], "350,000 KRW")

    def test_global_context_lists_are_capped(self):
        summaries = [
            {
                "code": "005930",
                "name": "Samsung Electronics",
                "timeframes": {},
                "market_context": {
                    "macro_context": {
                        "summary": "macro",
                        "next_macro_events": [
                            {"title": "event1"},
                            {"title": "event2"},
                            {"title": "event3"},
                        ],
                        "notes": ["n1", "n2", "n3"],
                    },
                    "benchmark_etfs": {
                        "A": {"name": "ETF A", "snapshot": {"change_rate": 1, "extra": "drop"}},
                        "B": {"name": "ETF B", "snapshot": {"change_rate": 2}},
                        "C": {"name": "ETF C", "snapshot": {"change_rate": 3}},
                    },
                    "data_quality": {
                        "missing_sections": ["a", "b", "c"],
                    },
                },
            }
        ]

        compressed, _ = compress_market_summaries_for_gpt(
            summaries,
            settings={"GPT_INPUT_MAX_CONTEXT_ITEMS": 2},
        )
        context = compressed[0]["market_context"]

        self.assertEqual(2, len(context["macro_context"]["next_macro_events"]))
        self.assertEqual(2, len(context["macro_context"]["notes"]))
        self.assertEqual(["A", "B"], list(context["benchmark_etfs"].keys()))
        self.assertEqual(2, len(context["data_quality"]["missing_sections"]))


if __name__ == "__main__":
    unittest.main()
