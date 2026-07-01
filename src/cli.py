"""`true-research` console entrypoint (pyproject [project.scripts]).

Thin routing only — all real logic lives in driver.py / src/launcher.py:
    true-research run "question" [driver flags] [--detach]   -> supervised launch
    true-research resume <run-id> [driver flags]             -> driver --resume
    true-research "question" [driver flags]                  -> plain driver.main
"""

from __future__ import annotations

import sys


def _driver_main(argv: list[str]) -> int:
    import driver

    return driver.main(argv)


def _launcher_main(argv: list[str]) -> int:
    from src.launcher import main as launcher_main

    return launcher_main(argv)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "run":
        return _launcher_main(args[1:])
    if args and args[0] == "resume":
        return _driver_main(["--resume", *args[1:]])
    return _driver_main(args)


if __name__ == "__main__":
    sys.exit(main())
