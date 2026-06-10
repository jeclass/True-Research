"""Eval-set runner + model bake-off (CLAUDE.md §8 Phase 5).

Runs eval questions end-to-end through the real engine, then scores each
finished run with a fresh Opus judge, and writes a comparable scores.json.
The bake-off knobs (--worker-model/--worker-endpoint, --reader-model/
--reader-endpoint) re-point a single role per invocation, so comparing
Sonnet vs Haiku vs a local/cheap-API worker is one flag change and a diff of
two scores.json files — the empirical answer to "which model", per our plan.

Examples:
  # quick 4-question smoke, default routing
  python evals/run_evals.py --subset quick --out evals/results/baseline

  # bake-off: route the worker to a local Ollama model
  python evals/run_evals.py --subset quick --worker-endpoint local \\
      --worker-model gpt-oss:20b --out evals/results/worker-local

  # bake-off: cheaper worker model on the first-party endpoint
  python evals/run_evals.py --subset quick --worker-model claude-haiku-4-5 \\
      --out evals/results/worker-haiku
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from evals.judge import judge_run, mean_score, scores_dict  # noqa: E402
from src.errors import EngineError  # noqa: E402
from src.ledger import Ledger  # noqa: E402
from src.runspace import Runspace  # noqa: E402
from src.sessions import get_backend  # noqa: E402
from src.settings import Settings, load_settings  # noqa: E402

_QUESTIONS = Path(__file__).resolve().parent / "questions.yaml"


def load_questions(subset: str | None, only: str | None = None) -> list[dict]:
    items = yaml.safe_load(_QUESTIONS.read_text(encoding="utf-8"))
    if only:
        items = [q for q in items if q["id"] == only]
        if not items:
            raise SystemExit(f"no question with id {only!r}")
        return items
    if subset:
        items = [q for q in items if subset in (q.get("subsets") or [])]
    if not items:
        raise SystemExit(f"no questions match subset {subset!r}")
    return items


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    """Re-point worker/reader role model+endpoint for a bake-off run.
    Rebuilds the frozen Settings; validation still applies."""
    raw = settings.model_dump()
    raw["secrets"] = {
        k: v.get_secret_value() for k, v in settings.secrets.items()
    }
    for role, model_arg, endpoint_arg in (
        ("worker", args.worker_model, args.worker_endpoint),
        ("reader_subagent", args.reader_model, args.reader_endpoint),
    ):
        if model_arg:
            raw["roles"][role]["model"] = model_arg
        if endpoint_arg:
            raw["roles"][role]["endpoint"] = endpoint_arg
    return Settings.model_validate(raw)


def run_one(
    item: dict, settings: Settings, runs_dir: Path, console: Console
) -> dict:
    profile = item["profile"]
    console.rule(f"[bold]{item['id']}[/bold] ({profile})")
    run = Runspace.create(runs_dir, item["question"], profile)
    backend = get_backend(settings)
    ledger = Ledger(run)
    record: dict = {"id": item["id"], "profile": profile, "run_id": run.meta.run_id}
    try:
        # Lazy import to keep evals importable without the SDK in stub envs.
        from driver import _drive

        reason = _drive(backend, run, settings, ledger, console)
        record["finish_reason"] = reason
        judge, metrics = judge_run(run, settings, item.get("must_address", []))
        record["scores"] = scores_dict(judge)
        record["mean_score"] = mean_score(judge)
        record["overall_assessment"] = judge.overall_assessment
        record["metrics"] = metrics
        console.print(
            f"[green]{item['id']}[/green]: mean {record['mean_score']}/10, "
            f"{reason}, ${metrics['spend_usd']:.2f}, "
            f"citations resolve: {metrics['citation_resolution_ok']}"
        )
    except EngineError as exc:
        record["error"] = str(exc)
        console.print(f"[red]{item['id']} errored:[/red] {exc}")
    except Exception as exc:  # noqa: BLE001 — one bad question must not kill the batch
        # KeyboardInterrupt / SystemExit are BaseException and still propagate.
        record["error"] = f"unexpected: {type(exc).__name__}: {exc}"
        console.print(f"[red]{item['id']} crashed:[/red] {type(exc).__name__}: {exc}")
    finally:
        run.release_lock()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the eval set + judge scoring.")
    parser.add_argument("--subset", help="only questions tagged with this subset (e.g. quick)")
    parser.add_argument("--only", help="run a single question by id (e.g. sci-aspirin)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out", required=True, help="output dir for scores.json + per-run json")
    parser.add_argument("--max-cycles", type=int, dest="max_cycles")
    parser.add_argument("--max-budget-usd", type=float, dest="max_budget_usd")
    parser.add_argument("--max-wall-hours", type=float, dest="max_wall_hours")
    parser.add_argument("--worker-model")
    parser.add_argument("--worker-endpoint")
    parser.add_argument("--reader-model")
    parser.add_argument("--reader-endpoint")
    args = parser.parse_args()

    console = Console()
    overrides = {
        "max_cycles": args.max_cycles,
        "max_budget_usd": args.max_budget_usd,
        "max_wall_hours": args.max_wall_hours,
    }
    try:
        settings = load_settings(config_path=args.config, overrides=overrides)
        settings = apply_overrides(settings, args)
    except EngineError as exc:
        console.print(f"[red]config error:[/red] {exc}")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = Path(settings.runs_dir)

    items = load_questions(args.subset, args.only)
    console.print(
        f"running {len(items)} question(s); worker="
        f"{settings.roles['worker'].model}@{settings.roles['worker'].endpoint}, "
        f"reader={settings.roles['reader_subagent'].model}"
        f"@{settings.roles['reader_subagent'].endpoint}"
    )

    records = []
    for item in items:
        record = run_one(item, settings, runs_dir, console)
        records.append(record)
        (out_dir / f"{item['id']}.json").write_text(json.dumps(record, indent=2))

    scored = [r for r in records if "mean_score" in r]
    summary = {
        "config": args.config,
        "subset": args.subset,
        "worker": f"{settings.roles['worker'].model}@{settings.roles['worker'].endpoint}",
        "reader": f"{settings.roles['reader_subagent'].model}@{settings.roles['reader_subagent'].endpoint}",
        "n_questions": len(items),
        "n_scored": len(scored),
        "n_errored": len(records) - len(scored),
        "mean_overall": round(sum(r["mean_score"] for r in scored) / len(scored), 2)
        if scored
        else None,
        "total_spend_usd": round(
            sum(r.get("metrics", {}).get("spend_usd", 0) for r in records), 2
        ),
        "results": records,
    }
    (out_dir / "scores.json").write_text(json.dumps(summary, indent=2))

    table = Table(title=f"Eval scores — {summary['worker']} worker")
    for col in ("id", "profile", "mean", "finish", "$", "cites ok"):
        table.add_column(col)
    for r in records:
        if "mean_score" in r:
            m = r["metrics"]
            table.add_row(
                r["id"], r["profile"], str(r["mean_score"]), r["finish_reason"],
                f"{m['spend_usd']:.2f}", "yes" if m["citation_resolution_ok"] else "NO",
            )
        else:
            table.add_row(r["id"], r["profile"], "—", "ERROR", "—", "—")
    console.print(table)
    console.print(
        f"mean overall: {summary['mean_overall']}/10  "
        f"total spend: ${summary['total_spend_usd']:.2f}  "
        f"-> {out_dir / 'scores.json'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
