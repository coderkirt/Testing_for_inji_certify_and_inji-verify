"""Diffing two results.json files."""

from __future__ import annotations

import json

import pytest

from result_diff import diff_results, main


def _doc(*modules, component="certify"):
    return {
        "plans": [
            {
                "component": component,
                "modules": [
                    {"testModule": name, "mapped": mapped} for name, mapped in modules
                ],
            }
        ]
    }


def test_regression_and_fix_are_classified():
    previous = _doc(("a", "PASS"), ("b", "FAIL"))
    current = _doc(("a", "FAIL"), ("b", "PASS"))
    report = diff_results(previous, current)
    assert report["regressions"] == [{"module": "certify::a", "from": "PASS", "to": "FAIL"}]
    assert report["fixes"] == [{"module": "certify::b", "from": "FAIL", "to": "PASS"}]
    assert report["summary"]["regressions"] == 1
    assert report["summary"]["fixes"] == 1


def test_added_and_removed_modules():
    report = diff_results(_doc(("a", "PASS")), _doc(("a", "PASS"), ("new", "PASS")))
    assert report["added"] == ["certify::new"]
    assert report["removed"] == []
    assert report["regressions"] == []


def test_modules_disappearing_between_runs():
    report = diff_results(_doc(("a", "PASS"), ("gone", "PASS")), _doc(("a", "PASS")))
    assert report["removed"] == ["certify::gone"]


def test_unchanged_modules_are_not_regressions():
    report = diff_results(_doc(("a", "PASS")), _doc(("a", "PASS")))
    assert report["regressions"] == []
    assert report["summary"]["previousModules"] == 1
    assert report["summary"]["currentModules"] == 1


def test_skip_to_fail_counts_as_a_regression():
    report = diff_results(_doc(("a", "SKIP")), _doc(("a", "FAIL")))
    assert len(report["regressions"]) == 1


def test_multi_component_documents_are_indexed_separately():
    previous = {"plans": [
        {"component": "certify", "modules": [{"testModule": "m", "mapped": "PASS"}]},
        {"component": "verify", "modules": [{"testModule": "m", "mapped": "PASS"}]},
    ]}
    current = {"plans": [
        {"component": "certify", "modules": [{"testModule": "m", "mapped": "FAIL"}]},
        {"component": "verify", "modules": [{"testModule": "m", "mapped": "PASS"}]},
    ]}
    report = diff_results(previous, current)
    assert [item["module"] for item in report["regressions"]] == ["certify::m"]


def test_cli_exit_code_is_non_zero_only_on_regression(tmp_path, monkeypatch, capsys):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    previous.write_text(json.dumps(_doc(("a", "PASS"))), encoding="utf-8")
    current.write_text(json.dumps(_doc(("a", "PASS"))), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["result_diff.py", "--previous", str(previous), "--current", str(current)],
    )
    assert main() == 0

    current.write_text(json.dumps(_doc(("a", "FAIL"))), encoding="utf-8")
    capsys.readouterr()
    assert main() == 1


def test_cli_writes_the_report(tmp_path, monkeypatch):
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    output = tmp_path / "nested" / "diff.json"
    previous.write_text(json.dumps(_doc(("a", "PASS"))), encoding="utf-8")
    current.write_text(json.dumps(_doc(("a", "FAIL"))), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "result_diff.py",
            "--previous",
            str(previous),
            "--current",
            str(current),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit):
        raise SystemExit(main())
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["regressions"]
