from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BASE_CONFIG: dict = {
    "runs_dir": None,  # filled per test
    "max_budget_usd": 10.0,
    "max_wall_hours": 6.0,
    "max_cycles": 40,
    "stall_cycles": 2,
    "profiles": ["general", "scientific", "visual"],
    "default_profile": "general",
    "endpoints": {
        "anthropic": {"base_url": None, "auth_env": "ANTHROPIC_API_KEY"},
        "local": {"base_url": "http://localhost:11434", "auth_env": "OLLAMA_AUTH"},
    },
    "roles": {
        "initializer": {"endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 16},
        "worker": {"endpoint": "anthropic", "model": "claude-sonnet-4-6", "max_turns": 50},
        "reader_subagent": {
            "endpoint": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "max_turns": 12,
        },
        "evaluator": {"endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 24},
        "synthesizer": {"endpoint": "anthropic", "model": "claude-opus-4-8", "max_turns": 40},
    },
    "session": {"backend": "stub", "max_budget_usd_per_session": 2.0},
    "stub": {
        "seed_questions": 3,
        "worker_no_delta": False,
        "sleep_seconds": 0.0,
        "cost_usd": 0.0,
    },
}


@pytest.fixture
def make_config(tmp_path: Path):
    """Write a config.yaml under tmp_path with overrides; returns its path.
    Overrides use dotted keys for nesting, e.g. {"stub.worker_no_delta": True}."""

    def _make(**overrides) -> Path:
        cfg = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))  # deep copy
        cfg["runs_dir"] = str(tmp_path / "runs")
        for dotted, value in overrides.items():
            node = cfg
            *parents, leaf = dotted.split(".")
            for key in parents:
                node = node[key]
            node[leaf] = value
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        return path

    return _make


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def only_run_dir(runs_dir: Path) -> Path:
    children = [p for p in runs_dir.iterdir() if p.is_dir()]
    assert len(children) == 1, f"expected exactly one run dir, found {children}"
    return children[0]
