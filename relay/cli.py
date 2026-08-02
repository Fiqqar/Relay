"""CLIHandler: the argparse entry point.

Usage:
    relay                      # solo mode (default)
    relay --solo               # explicit solo
    relay --team payments      # team mode -> branch status/payments
    relay --team               # team mode, feature derived/prompted
    relay --provider ollama    # override the AI provider
    relay --dry-run --yes      # show the plan, change nothing
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .ai import build_provider
from .errors import RelayError, UserAbort
from .orchestrator import Orchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="relay",
        description=(
            "Your Git workflow, on autopilot: AI Conventional Commits "
            "with a manual fallback."
        ),
    )
    parser.add_argument("--version", action="version", version=f"relay {__version__}")

    # Mutually exclusive mode switch. `--team` uses nargs='?' so it accepts an
    # optional feature name:  `relay --team "payments"`.
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--solo", action="store_true",
                       help="stage, commit and push to the current branch")
    group.add_argument(
        "--team",
        nargs="?",
        const="",
        metavar="FEATURE",
        help="create & checkout status/<feature>, commit, and push it (feature optional)",
    )

    parser.add_argument("--provider", choices=["gemini", "ollama"],
                        help="AI provider (default: gemini, or RELAY_AI_PROVIDER)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the plan; change nothing")
    parser.add_argument("--no-push", action="store_true",
                        help="commit but do not push")
    parser.add_argument("--verbose", action="store_true",
                        help="print the git commands being run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Resolve mode. `--team` sets args.team to "" (no feature) or a feature name;
    # `--solo` / nothing leaves it None.
    mode = "team" if args.team is not None else "solo"
    feature = args.team or None

    try:
        ai = build_provider(args.provider)
        orchestrator = Orchestrator(
            mode=mode,
            feature=feature,
            provider=ai,
            yes=args.yes,
            no_push=args.no_push,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        return orchestrator.run()
    except UserAbort as exc:
        # 130 is the conventional "interrupted by user" exit code (matches Ctrl-C).
        print(f"[relay] {exc}")
        return 130
    except RelayError as exc:
        print(f"[relay] error: {exc}")
        if args.verbose and getattr(exc, "stderr", None):
            print(exc.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[relay] aborted.")
        return 130
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never traceback
        print(f"[relay] unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
