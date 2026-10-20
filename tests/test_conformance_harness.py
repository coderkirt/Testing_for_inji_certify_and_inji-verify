"""Unit tests for AutoConform Python runner, benchmark gating, and SD-JWT verification.

Run directly via:
    python -m unittest tests/test_conformance_harness.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))

from config_render import endpoint_mapping, render_plan_config
from result_diff import diff_results
from run_conformance import evaluate_benchmark, map_result
from sd_jwt_verifier import SdJwtVerifier, create_sample_farmer_sd_jwt


class TestBenchmarkEvaluation(unittest.TestCase):
    def test_gate_passes_when_meeting_min_rate_and_zero_regressions(self):
        summary = {
            "total": 36,
            "passed": 18,
            "failed": 0,
            "skipped": 18,
            "unexpectedFailures": 0,
            "unexpectedSkips": 0,
            "ranModules": ["m1", "m2"],
        }
        benchmark = {
            "minPassRate": 0.50,
            "failOnUnexpectedFailure": True,
            "failOnUnexpectedSkip": False,
        }
        met, reasons = evaluate_benchmark(summary, benchmark)
        self.assertTrue(met)
        self.assertEqual(len(reasons), 0)

    def test_gate_fails_on_unexpected_failure(self):
        summary = {
            "total": 10,
            "passed": 5,
            "failed": 2,
            "skipped": 3,
            "unexpectedFailures": 1,
            "unexpectedSkips": 0,
        }
        benchmark = {
            "minPassRate": 0.50,
            "failOnUnexpectedFailure": True,
        }
        met, reasons = evaluate_benchmark(summary, benchmark)
        self.assertFalse(met)
        self.assertTrue(any("unexpected failure" in r for r in reasons))

    def test_gate_fails_below_min_rate(self):
        summary = {
            "total": 10,
            "passed": 3,
            "failed": 0,
            "skipped": 7,
            "unexpectedFailures": 0,
        }
        benchmark = {"minPassRate": 0.50}
        met, reasons = evaluate_benchmark(summary, benchmark)
        self.assertFalse(met)
        self.assertTrue(any("pass rate" in r for r in reasons))


class TestResultMapping(unittest.TestCase):
    def test_pass_results_map_to_pass(self):
        self.assertEqual(map_result("PASSED", False, False), "PASS")
        self.assertEqual(map_result("FINISHED", False, False), "PASS")
        self.assertEqual(map_result("PASSED_WITH_WARNINGS", False, False), "PASS")

    def test_expected_failures_map_to_skip(self):
        self.assertEqual(map_result("FAILED", expected_failure=True, skipped=False), "SKIP")
        self.assertEqual(map_result("INTERRUPTED", expected_failure=True, skipped=False), "SKIP")

    def test_unexpected_failures_map_to_fail(self):
        self.assertEqual(map_result("FAILED", expected_failure=False, skipped=False), "FAIL")


class TestResultDifferencing(unittest.TestCase):
    def test_detects_fixes_and_no_regressions(self):
        prev = {
            "plans": [
                {
                    "component": "certify",
                    "modules": [
                        {"testModule": "mod_a", "mapped": "FAIL"},
                        {"testModule": "mod_b", "mapped": "PASS"},
                    ],
                }
            ]
        }
        curr = {
            "plans": [
                {
                    "component": "certify",
                    "modules": [
                        {"testModule": "mod_a", "mapped": "PASS"},
                        {"testModule": "mod_b", "mapped": "PASS"},
                    ],
                }
            ]
        }
        diff = diff_results(prev, curr)
        self.assertEqual(diff["summary"]["regressions"], 0)
        self.assertEqual(diff["summary"]["fixes"], 1)
        self.assertEqual(diff["fixes"][0]["module"], "certify::mod_a")


class TestSdJwtVerifier(unittest.TestCase):
    def test_verifies_valid_farmer_sd_jwt(self):
        token = create_sample_farmer_sd_jwt()
        result = SdJwtVerifier.verify(
            token,
            expected_aud="did:web:verify-service:v1:verify",
            expected_nonce="test_nonce_99182371",
        )
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.disclosures_count, 3)
        self.assertEqual(result.disclosed_claims["fullName"], "Ramesh Kumar")
        self.assertEqual(result.disclosed_claims["farmerID"], "IND-UP-2026-F981")
        self.assertEqual(result.disclosed_claims["landArea"], "4.5 Hectares")

    def test_rejects_tampered_disclosure(self):
        token = create_sample_farmer_sd_jwt()
        parts = token.split("~")
        # Tamper disclosure 1 by flipping character
        tampered_disc = parts[1][:-2] + "AA"
        tampered_token = f"{parts[0]}~{tampered_disc}~{parts[2]}~{parts[3]}~{parts[4]}"

        result = SdJwtVerifier.verify(tampered_token)
        self.assertFalse(result.is_valid)
        self.assertTrue(any("Disclosure digest" in err for err in result.errors))

    def test_rejects_audience_mismatch_in_kb_jwt(self):
        token = create_sample_farmer_sd_jwt()
        result = SdJwtVerifier.verify(
            token,
            expected_aud="did:web:wrong-verifier:v1:verify",
            expected_nonce="test_nonce_99182371",
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(any("aud mismatch" in err for err in result.errors))


class TestConfigRendering(unittest.TestCase):
    def test_endpoint_mapping(self):
        mapping = endpoint_mapping("https://my-certify", "http://my-verify:8080", "MyCred")
        self.assertEqual(mapping["CERTIFY_ISSUER_URL"], "https://my-certify")
        self.assertEqual(mapping["VERIFY_ENDPOINT"], "http://my-verify:8080")
        self.assertEqual(mapping["CERTIFY_CREDENTIAL_CONFIGURATION_ID"], "MyCred")


class TestEvidenceIntegrity(unittest.TestCase):
    def test_results_json_structure_and_benchmark(self):
        results_file = ROOT / "results" / "results.json"
        self.assertTrue(results_file.exists(), "results.json must exist")
        data = json.loads(results_file.read_text(encoding="utf-8"))
        self.assertTrue(data.get("benchmarkMet"), "Benchmark must be met in audited results")
        summary = data.get("summary", {})
        self.assertEqual(summary.get("unexpectedFailures"), 0)
        self.assertEqual(summary.get("total"), 36)

    def test_html_dashboard_artifact_exists(self):
        dashboard_file = ROOT / "results" / "conformance-report.html"
        self.assertTrue(dashboard_file.exists(), "conformance-report.html must exist")
        html_content = dashboard_file.read_text(encoding="utf-8")
        self.assertIn("AutoConform Conformance Evidence", html_content)
        self.assertIn("drawer-overlay", html_content)


if __name__ == "__main__":
    unittest.main()

