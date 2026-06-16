#!/usr/bin/env python
"""Gate A/B harness (architect review 2026-06-16): the one measurement left.

Question: is --accurate's Opus gate worth ~2x the gate cost over --cheap's Qwen
gate, or does Qwen's high abstention bias make it a wash (-> Qwen wins outright,
no Opus tier needed)? Decide it on data, not priors.

Method — REPLAY, not re-run. We don't run each question twice end-to-end (the two
runs would diverge on search paths and the gate would judge *different* findings,
confounding the comparison). Instead we freeze ONE terminal run-state per question
and replay only the final gate on it under each model. Same findings, same open
questions, same prompts — the gate model is the only variable. The replay is
strictly read-only: it builds the gate's prompts and asks for a verdict, but never
calls _apply_output / write_verdict, so running both arms on one run can't
contaminate it.

Workflow:
  1. Generate terminal states (needs keys + proxy), one per question:
       python driver.py "<question>" --cheap --profile <p>
     ...for each item in questions.yaml. (See README for a loop.)
  2. Replay the gate A/B over those run dirs:
       python experiments/gate_ab/run_gate_ab.py replay --runs <id> <id> ... --out results.csv
     Add --dry-run to validate wiring with no LLM spend (no keys needed).
  3. Mark ground truth: open results.csv, fill the `ground_truth` column with
     `fail` (the run had a real gap -> should have stayed open) or `pass`
     (genuinely conclusive). This is the human judgment the whole A/B rests on.
  4. Score it:
       python experiments/gate_ab/run_gate_ab.py score results.csv
     Reports each model's false-"conclusive" rate (the fatal error: PASSED a run
     whose ground truth is `fail`) and its false-open rate (abstention bias:
     FAILED a run whose ground truth is `pass`).
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys

# This script lives at experiments/gate_ab/; put the repo root on the path so
# `import src...` resolves when run as `python experiments/gate_ab/run_gate_ab.py`.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

GATES = ("opus", "qwen")
_GATE_TOOLS = ["Read", "Glob", "Grep"]


# --- Replay -----------------------------------------------------------------

def replay_gate(run, gate: str, *, dry_run: bool) -> dict:
    """Read-only: build the terminal gate's prompts on a frozen run and judge
    under `gate`'s model. Returns the verdict; mutates nothing on disk."""
    from src.ledger import Ledger
    from src.profiles import get_profile
    from src.sessions.base import run_role_session
    from src.sessions.evaluator import (
        EvaluatorOutput,
        _build_user_prompt,
        build_system_prompt,
    )
    from src.settings import load_settings

    settings = load_settings(overrides={"cheap": True, "gate": gate})
    role = settings.roles["final_evaluator"]
    profile = get_profile(run.meta.profile)
    ledger = Ledger(run)
    cycle = run.last_cycle()
    system_prompt = build_system_prompt(profile, final=True)
    user_prompt = _build_user_prompt(run, settings, ledger, cycle, final=True)

    label = f"{role.endpoint}/{role.model}"
    if dry_run:
        return {
            "gate": gate,
            "model": label,
            "sys_chars": len(system_prompt),
            "usr_chars": len(user_prompt),
            "passed": None,
            "unmet_n": None,
            "unmet": [],
        }

    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="evaluator",
        role="final_evaluator",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=_GATE_TOOLS,
        output_model=EvaluatorOutput,
    )
    out: "EvaluatorOutput" = spawn.structured
    return {
        "gate": gate,
        "model": label,
        "passed": bool(out.passed),
        "unmet_n": len(out.unmet_criteria),
        "unmet": list(out.unmet_criteria),
    }


def replay_runs(run_ids: list[str], *, dry_run: bool) -> list[dict]:
    """Replay both gates on each run dir; return one result row per run."""
    from src.runspace import Runspace
    from src.settings import load_settings

    runs_dir = pathlib.Path(load_settings().runs_dir)
    rows: list[dict] = []
    for run_id in run_ids:
        # Read-only: the replay never writes, and these are terminal (often
        # finished) runs, so we open without the lock / finished-guard.
        run = Runspace.open_readonly(runs_dir, run_id)
        findings = run.load_findings()
        if not findings:
            print(f"  ! {run_id}: 0 findings — not a terminal state; skipping", file=sys.stderr)
            continue
        row: dict = {"run_id": run_id, "findings_n": len(findings), "ground_truth": "", "note": ""}
        for gate in GATES:
            r = replay_gate(run, gate, dry_run=dry_run)
            if dry_run:
                print(f"  {run_id}  --gate {gate:4s} -> {r['model']:26s} "
                      f"sys={r['sys_chars']} usr={r['usr_chars']} chars")
            else:
                print(f"  {run_id}  --gate {gate:4s} -> {r['model']:26s} "
                      f"{'PASS' if r['passed'] else 'FAIL'} ({r['unmet_n']} unmet)")
            row[f"{gate}_passed"] = "" if r["passed"] is None else r["passed"]
            row[f"{gate}_unmet_n"] = "" if r["unmet_n"] is None else r["unmet_n"]
        rows.append(row)
    return rows


# --- Scoring (pure; unit-tested) --------------------------------------------

def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v in ("", None):
        return None
    return str(v).strip().lower() in ("true", "1", "pass", "passed", "yes")


def score_results(rows: list[dict]) -> dict:
    """Compute each gate's error rates against the human `ground_truth` column.

    ground_truth is `fail` (the run had a real gap — should have stayed OPEN) or
    `pass` (genuinely conclusive). Rows with a blank ground_truth are unscored.

      false_conclusive = P(model PASSED | ground_truth == fail)   # the fatal error
      false_open       = P(model FAILED | ground_truth == pass)   # abstention bias

    Lower false_conclusive is the load-bearing number; false_open is the cost of
    over-abstention. agreement = fraction of scored rows where both gates agree.
    """
    per_gate = {g: {"false_conclusive": _Rate(), "false_open": _Rate()} for g in GATES}
    scored = 0
    agree = 0
    for row in rows:
        truth = str(row.get("ground_truth", "")).strip().lower()
        if truth not in ("pass", "fail"):
            continue
        scored += 1
        verdicts = {}
        for g in GATES:
            passed = _as_bool(row.get(f"{g}_passed"))
            verdicts[g] = passed
            if passed is None:
                continue
            if truth == "fail":
                per_gate[g]["false_conclusive"].add(passed is True)
            else:  # truth == "pass"
                per_gate[g]["false_open"].add(passed is False)
        if verdicts.get("opus") is not None and verdicts["opus"] == verdicts.get("qwen"):
            agree += 1
    return {
        "scored": scored,
        "agreement": (agree / scored) if scored else None,
        "gates": {
            g: {
                "false_conclusive": per_gate[g]["false_conclusive"].as_dict(),
                "false_open": per_gate[g]["false_open"].as_dict(),
            }
            for g in GATES
        },
    }


class _Rate:
    __slots__ = ("num", "den")

    def __init__(self) -> None:
        self.num = 0
        self.den = 0

    def add(self, hit: bool) -> None:
        self.den += 1
        self.num += 1 if hit else 0

    def as_dict(self) -> dict:
        return {"hits": self.num, "of": self.den, "rate": (self.num / self.den) if self.den else None}


# --- CSV + CLI --------------------------------------------------------------

_FIELDS = ["run_id", "findings_n", "opus_passed", "opus_unmet_n",
           "qwen_passed", "qwen_unmet_n", "ground_truth", "note"]


def _write_csv(rows: list[dict], out: pathlib.Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _fmt_rate(r: dict) -> str:
    if r["rate"] is None:
        return "n/a (0 cases)"
    return f"{r['rate']*100:5.1f}%  ({r['hits']}/{r['of']})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Gate A/B: Opus vs Qwen on the terminal gate.")
    sub = p.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("replay", help="replay both gates on terminal run states")
    rp.add_argument("--runs", nargs="+", required=True, metavar="RUN_ID",
                    help="run-dir ids (terminal states) to replay the gate on")
    rp.add_argument("--out", default="experiments/gate_ab/results.csv", type=pathlib.Path)
    rp.add_argument("--dry-run", action="store_true",
                    help="validate wiring (resume + prompt build + routing) with no LLM spend")

    sc = sub.add_parser("score", help="score a results.csv whose ground_truth is filled in")
    sc.add_argument("csv", type=pathlib.Path)

    args = p.parse_args(argv)

    if args.cmd == "replay":
        print(f"Replaying gate A/B on {len(args.runs)} run(s) "
              f"{'(DRY RUN — no spend)' if args.dry_run else ''}")
        rows = replay_runs(args.runs, dry_run=args.dry_run)
        if not rows:
            print("No terminal states replayed.", file=sys.stderr)
            return 1
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(rows, args.out)
        print(f"\nWrote {len(rows)} row(s) -> {args.out}")
        if not args.dry_run:
            print("Next: fill the `ground_truth` column (fail|pass), then "
                  f"`score {args.out}`.")
        return 0

    if args.cmd == "score":
        rows = _read_csv(args.csv)
        result = score_results(rows)
        if not result["scored"]:
            print("No rows have a ground_truth of pass|fail yet — nothing to score.",
                  file=sys.stderr)
            return 1
        print(f"\nGate A/B — {result['scored']} scored run(s), "
              f"gate agreement {result['agreement']*100:.0f}%\n")
        print(f"{'gate':6s}  {'false-CONCLUSIVE (fatal)':28s}  false-open (abstention)")
        for g in GATES:
            gd = result["gates"][g]
            print(f"{g:6s}  {_fmt_rate(gd['false_conclusive']):28s}  {_fmt_rate(gd['false_open'])}")
        print("\nDecision: lower false-conclusive wins the gate. If Qwen ties or "
              "beats Opus here, Qwen wins outright (~2x cheaper) and no Opus tier "
              "is needed. If Opus is materially lower, --accurate earns its gate.")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
