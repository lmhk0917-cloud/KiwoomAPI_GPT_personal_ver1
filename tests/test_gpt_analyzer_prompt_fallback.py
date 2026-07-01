import unittest

import gpt_analyzer


class GptAnalyzerPromptFallbackTest(unittest.TestCase):
    def test_builtin_fallback_prompts_are_readable_korean(self):
        self.assertIn("한국 주식시장", gpt_analyzer.DEFAULT_SYSTEM_PROMPT)
        self.assertIn("수익 대비 위험", gpt_analyzer.DEFAULT_SYSTEM_PROMPT)
        self.assertIn("한국 주식시장", gpt_analyzer.DEFAULT_USER_PROMPT)
        self.assertIn("[분석 데이터]", gpt_analyzer.DEFAULT_USER_PROMPT)
        self.assertIn("{data_json}", gpt_analyzer.DEFAULT_USER_PROMPT)
        self.assertNotIn("�", gpt_analyzer.DEFAULT_SYSTEM_PROMPT)
        self.assertNotIn("�", gpt_analyzer.DEFAULT_USER_PROMPT)

    def test_missing_prompt_file_uses_readable_fallback(self):
        prompt = gpt_analyzer._read_prompt_file(
            r"C:\path\that\does\not\exist\prompt.txt",
            gpt_analyzer.DEFAULT_USER_PROMPT,
        )
        self.assertIn("데이터가 없거나 신뢰도가 낮으면", prompt)
        self.assertIn("{data_json}", prompt)
        self.assertNotIn("�", prompt)

    def test_user_prompt_includes_shared_context_and_correlation_safety_rules(self):
        prompt = gpt_analyzer._read_prompt_file(
            gpt_analyzer.USER_PROMPT_PATH,
            gpt_analyzer.DEFAULT_USER_PROMPT,
        )
        required_phrases = [
            "shared_context.db",
            "latest_kiwoom_context_time",
            "latest_toss_context_time",
            "latest_relationship_context_time",
            "paired_sample_count",
            "correlation",
            "beta",
            "r_squared",
            "hit_ratio",
            "lead_score",
            "daily-only",
            "short_term_event_context",
            "gap_effect.status",
            "relationship_regime",
            "data_freshness",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
