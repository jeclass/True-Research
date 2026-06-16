"""Pins the gate A/B's load-bearing metric (architect review 2026-06-16).

The whole experiment rests on one definition: false-"conclusive" = the gate
PASSED a run whose human ground truth is `fail` (it should have stayed open).
If that math drifts, the A/B's conclusion is wrong. These tests lock it."""

import importlib.util
import pathlib

_HARNESS = pathlib.Path(__file__).resolve().parents[1] / "experiments" / "gate_ab" / "run_gate_ab.py"
_spec = importlib.util.spec_from_file_location("gate_ab_harness", _HARNESS)
gate_ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_ab)


def _row(rid, opus_passed, qwen_passed, ground_truth):
    return {
        "run_id": rid,
        "opus_passed": opus_passed,
        "qwen_passed": qwen_passed,
        "ground_truth": ground_truth,
    }


def test_false_conclusive_is_pass_on_a_should_fail_run():
    # Two runs that SHOULD have stayed open (ground_truth=fail). Opus correctly
    # FAILs both; Qwen wrongly PASSes one -> Qwen false-conclusive = 1/2.
    rows = [
        _row("a", opus_passed=False, qwen_passed=True, ground_truth="fail"),
        _row("b", opus_passed=False, qwen_passed=False, ground_truth="fail"),
    ]
    res = gate_ab.score_results(rows)
    assert res["scored"] == 2
    assert res["gates"]["opus"]["false_conclusive"] == {"hits": 0, "of": 2, "rate": 0.0}
    assert res["gates"]["qwen"]["false_conclusive"] == {"hits": 1, "of": 2, "rate": 0.5}


def test_false_open_is_fail_on_a_should_pass_run():
    # A genuinely conclusive run (ground_truth=pass). Qwen's abstention bias makes
    # it wrongly FAIL -> Qwen false-open = 1/1; Opus correctly passes -> 0/1.
    rows = [_row("c", opus_passed=True, qwen_passed=False, ground_truth="pass")]
    res = gate_ab.score_results(rows)
    assert res["gates"]["opus"]["false_open"] == {"hits": 0, "of": 1, "rate": 0.0}
    assert res["gates"]["qwen"]["false_open"] == {"hits": 1, "of": 1, "rate": 1.0}
    # a should-pass run contributes to false_open, never to false_conclusive
    assert res["gates"]["qwen"]["false_conclusive"]["of"] == 0


def test_blank_ground_truth_rows_are_unscored():
    rows = [
        _row("a", opus_passed=True, qwen_passed=True, ground_truth=""),
        _row("b", opus_passed=False, qwen_passed=False, ground_truth="fail"),
    ]
    res = gate_ab.score_results(rows)
    assert res["scored"] == 1  # only the labelled row counts


def test_agreement_counts_matching_verdicts_over_scored_rows():
    rows = [
        _row("a", opus_passed=True, qwen_passed=True, ground_truth="pass"),   # agree
        _row("b", opus_passed=True, qwen_passed=False, ground_truth="fail"),  # disagree
    ]
    res = gate_ab.score_results(rows)
    assert res["agreement"] == 0.5


def test_csv_string_booleans_parse():
    # results.csv round-trips bools as the strings "True"/"False"; scoring must
    # read them back correctly (and accept pass/fail synonyms).
    rows = [
        {"opus_passed": "True", "qwen_passed": "False", "ground_truth": "fail"},
    ]
    res = gate_ab.score_results(rows)
    assert res["gates"]["opus"]["false_conclusive"]["rate"] == 1.0  # "True" on a fail run
    assert res["gates"]["qwen"]["false_conclusive"]["rate"] == 0.0  # "False" -> correctly open
