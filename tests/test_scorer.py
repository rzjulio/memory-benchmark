"""Unit tests for the deterministic scorer. Run: python -m unittest discover -s tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scorer
from adapters import extract, substitute


class TestRetrievalMetrics(unittest.TestCase):
    def test_precision_lenient_rewards_short_correct_lists(self):
        # tool returned 2 items, both relevant -> lenient 1.0, strict 0.4
        self.assertEqual(scorer.precision_at_k(["A", "B"], {"A", "B"}, 5), 1.0)
        self.assertEqual(scorer.precision_at_k(["A", "B"], {"A", "B"}, 5, strict=True), 0.4)

    def test_precision_none_when_no_expected(self):
        self.assertIsNone(scorer.precision_at_k(["A"], set(), 5))

    def test_recall(self):
        self.assertEqual(scorer.recall_at_k(["A", "X", "B"], {"A", "B"}, 5), 1.0)
        self.assertEqual(scorer.recall_at_k(["X", "Y"], {"A", "B"}, 5), 0.0)

    def test_mrr(self):
        self.assertEqual(scorer.mrr(["X", "A"], {"A"}), 0.5)
        self.assertEqual(scorer.mrr(["X"], {"A"}), 0.0)
        self.assertIsNone(scorer.mrr(["X"], set()))

    def test_scope_leak_detected(self):
        index = scorer.build_corpus_index([
            {"memory_id": "M1", "scope": "project", "namespace": "project://data-kb/a"},
            {"memory_id": "M22", "scope": "project", "namespace": "project://other-tool/a"},
        ])
        case = {"case_id": "Q", "namespace": "project://data-kb/a",
                "expected_memory_ids": ["M1"], "forbidden_memory_ids": ["M22"]}
        row = scorer.score_retrieval_case(case, ["M1", "M22"], index)
        self.assertEqual(row["scope_leaks"], ["M22"])
        self.assertEqual(row["forbidden_hits"], ["M22"])
        self.assertTrue(row["needs_human_review"])

    def test_min_recall_pass(self):
        index = scorer.build_corpus_index([
            {"memory_id": "M1", "scope": "project", "namespace": "project://x/a"}])
        case = {"case_id": "Q", "namespace": "project://x/a",
                "expected_memory_ids": ["M1"], "forbidden_memory_ids": [],
                "min_recall_at_5": 1.0}
        self.assertTrue(scorer.score_retrieval_case(case, ["M1"], index)["recall_at_5_pass"])
        self.assertFalse(scorer.score_retrieval_case(case, ["Z"], index)["recall_at_5_pass"])


class TestActionMatching(unittest.TestCase):
    def test_synonyms_normalize(self):
        self.assertEqual(scorer.normalize_action("Stored"), "save")
        self.assertEqual(scorer.normalize_action("REJECTED"), "reject")
        self.assertEqual(scorer.normalize_action("merge"), "merge")

    def test_compound_expected_actions(self):
        self.assertEqual(scorer.action_match("save_or_update", "update"), (True, False))
        self.assertEqual(scorer.action_match("merge_or_reject_duplicate", "reject"), (True, False))
        self.assertEqual(scorer.action_match("partial_save_metric_reject_secret", "save"), (False, False))

    def test_no_action_needs_review(self):
        matched, review = scorer.action_match("save", None)
        self.assertIsNone(matched)
        self.assertTrue(review)

    def test_unknown_vocabulary_flags_review(self):
        matched, review = scorer.action_match("totally_new_expected", "save")
        self.assertTrue(review)


class TestSecretScanning(unittest.TestCase):
    def test_extract_secret_tokens(self):
        toks = scorer.extract_secret_tokens(
            "key ghp_abcdefgh12345678 and sk-live-1234567890abcdef here")
        self.assertEqual(len(toks), 2)

    def test_scan_patterns(self):
        mems = [{"id": "A1", "content": "remember sk-live-123456789 please"}]
        hits = scorer.scan_patterns(mems, ["sk-live-123456789"])
        self.assertEqual(hits[0]["memory_id"], "A1")
        self.assertEqual(scorer.scan_patterns(mems, ["ghp_zzz"]), [])


class TestFactsCoverage(unittest.TestCase):
    def test_token_based_matching(self):
        ans = "data-kb supports PostgreSQL via asyncpg and SQLite."
        self.assertTrue(scorer.fact_covered("PostgreSQL asyncpg", ans))
        self.assertFalse(scorer.fact_covered("Django framework", ans))


class TestAdapterHelpers(unittest.TestCase):
    def test_extract_paths(self):
        data = {"memories": [{"id": "M1"}, {"id": "M2"}], "latency_ms": 12}
        self.assertEqual(extract(data, "memories[].id"), ["M1", "M2"])
        self.assertEqual(extract(data, "latency_ms"), 12)
        self.assertIsNone(extract(data, "missing.path"))

    def test_substitute_types_and_payloads(self):
        ctx = {"top_k": "10", "query": "hi", "memory": {"a": 1}}
        self.assertEqual(substitute("{top_k:int}", ctx), 10)
        self.assertEqual(substitute("{memory}", ctx), {"a": 1})
        self.assertEqual(substitute("q={query}!", ctx), "q=hi!")
        self.assertEqual(substitute({"k": "{top_k:int}"}, ctx), {"k": 10})


if __name__ == "__main__":
    unittest.main()
