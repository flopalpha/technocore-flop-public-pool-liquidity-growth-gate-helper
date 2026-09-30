"""Tests for pool liquidity-growth gate helper."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import pool_gate


def sample_snapshots():
    return [
        {"pool_id": "DUST", "timestamp": 1700000000, "liquidity": 10.0, "price": 0.5},
        {"pool_id": "DUST", "timestamp": 1700000900, "liquidity": 12.0, "price": 0.51},
        {"pool_id": "GOOD", "timestamp": 1700000500, "liquidity": 5000.0, "price": 1.0},
        {"pool_id": "GOOD", "timestamp": 1700001400, "liquidity": 8000.0, "price": 1.4},
        {"pool_id": "FLAT", "timestamp": 1700000600, "liquidity": 9000.0, "price": 2.0},
        {"pool_id": "FLAT", "timestamp": 1700001500, "liquidity": 9010.0, "price": 2.0},
    ]


class GateHelperTest(unittest.TestCase):
    def test_normalize_accepts_good_row(self):
        raw = {"pool_id": " A ", "timestamp": "1700000000", "liquidity": "10", "price": "1.5"}
        out = pool_gate.normalize_snapshot(raw)
        self.assertIsNotNone(out)
        self.assertEqual(out["pool_id"], "A")
        self.assertEqual(out["timestamp"], 1700000000)

    def test_normalize_rejects_bad_row(self):
        self.assertIsNone(pool_gate.normalize_snapshot({"pool_id": "", "timestamp": 1, "liquidity": 1, "price": 1}))
        self.assertIsNone(pool_gate.normalize_snapshot({"pool_id": "X", "timestamp": 1, "liquidity": -5, "price": 1}))
        self.assertIsNone(pool_gate.normalize_snapshot({"pool_id": "X", "timestamp": 1, "liquidity": 1, "price": -1}))

    def test_summarize_and_dust_flags(self):
        snaps = sample_snapshots()
        summary = pool_gate.summarize_pools(snaps)
        self.assertEqual(summary["GOOD"]["delta"], 3000.0)
        flags = pool_gate.flag_dust_pools(summary, min_liquidity=1000.0, min_delta=100.0)
        self.assertTrue(flags["DUST"]["is_dust"])
        self.assertFalse(flags["GOOD"]["is_dust"])
        self.assertTrue(flags["FLAT"]["is_dust"])

    def test_pearson_basic(self):
        self.assertAlmostEqual(pool_gate.pearson([1, 2, 3], [1, 2, 3]), 1.0)
        self.assertAlmostEqual(pool_gate.pearson([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertEqual(pool_gate.pearson([5, 5, 5], [1, 2, 3]), 0.0)
        self.assertEqual(pool_gate.pearson([1], [1]), 0.0)

    def test_score_pool_growth(self):
        grouped = pool_gate.group_by_pool(sample_snapshots())
        good = pool_gate.score_pool(grouped["GOOD"])
        flat = pool_gate.score_pool(grouped["FLAT"])
        self.assertGreater(good["score"], flat["score"])
        self.assertGreater(good["correlation"], 0.9)
        self.assertIn("liquidity and price grew together", good["reasons"])

    def test_ranking_comparison_exposes_dust_bias(self):
        snaps = sample_snapshots()
        comp = pool_gate.compare_rankings(snaps, window_minutes=15, top_n=2, min_liquidity=1000.0)
        self.assertIn("DUST", comp["earliest_top"])
        self.assertIn("GOOD", comp["weighted_top"])
        self.assertGreaterEqual(comp["dust_in_earliest_top"], 1)

    def test_gate_decisions(self):
        gate, _ = pool_gate.decide_gate(False, 80.0, 500.0, 0.9)
        self.assertEqual(gate, "PASS")
        gate2, _ = pool_gate.decide_gate(True, 80.0, 500.0, 0.9)
        self.assertEqual(gate2, "FAIL")
        gate3, _ = pool_gate.decide_gate(False, 10.0, -5.0, 0.0)
        self.assertEqual(gate3, "FAIL")

    def test_csv_and_json_load_with_tempfile(self):
        snaps = sample_snapshots()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "pools.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["pool_id", "timestamp", "liquidity", "price"])
                w.writeheader()
                for s in snaps:
                    w.writerow(s)
            loaded_csv = pool_gate.load_csv_snapshots(str(csv_path))
            self.assertEqual(len(loaded_csv), 6)
            json_path = Path(tmp) / "pools.json"
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(snaps, f)
            loaded_json = pool_gate.load_json_snapshots(str(json_path))
            self.assertEqual(len(loaded_json), 6)

    def test_report_export_with_tempfile(self):
        snaps = sample_snapshots()
        report = pool_gate.build_report(snaps, window_minutes=15, min_liquidity=1000.0, min_delta=100.0)
        self.assertEqual(report["snapshot_count"], 6)
        self.assertEqual(report["pool_count"], 3)
        self.assertIn("checksum", report)
        with tempfile.TemporaryDirectory() as tmp:
            jpath = Path(tmp) / "report.json"
            mpath = Path(tmp) / "report.md"
            pool_gate.write_json_report(report, str(jpath))
            pool_gate.write_markdown_report(report, str(mpath))
            self.assertTrue(jpath.exists())
            self.assertTrue(mpath.exists())
            with jpath.open("r", encoding="utf-8") as f:
                back = json.load(f)
            self.assertEqual(back["checksum"], report["checksum"])
            text = mpath.read_text(encoding="utf-8")
            self.assertIn("GOOD", text)
            self.assertIn("Ranked Pools", text)

    def test_checksum_stable(self):
        a = sample_snapshots()
        b = list(reversed(a))
        self.assertEqual(pool_gate.compute_checksum(a), pool_gate.compute_checksum(b))


if __name__ == "__main__":
    unittest.main()
