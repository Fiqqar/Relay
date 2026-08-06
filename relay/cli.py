"""CLIHandler: the argparse entry point.

Usage:
    relay                      # solo mode (default)
    relay --solo               # explicit solo
    relay --team payments      # team mode -> branch feat/payments (type from AI)
    relay --team               # team mode, feature derived/prompted
    relay --provider ollama    # override the AI provider
    relay --dry-run --yes      # show the plan, change nothing
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .ai import build_provider
from .config import pr_open_browser
from .doctor import run_doctor
from .errors import RelayError, UserAbort
from .orchestrator import Orchestrator
from .pr import run_pr
from .undo import run_undo


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
        help="create & checkout <type>/<feature>, commit, and push it (feature optional)",
    )

    parser.add_argument("--provider", choices=["gemini", "ollama"],
                        help="AI provider (default: gemini, or RELAY_AI_PROVIDER)")
    parser.add_argument("--timeout", type=int, metavar="SECONDS",
                        help="seconds to wait for the AI response (default: 30, max: 120)")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the plan; change nothing")
    parser.add_argument("--no-push", action="store_true",
                        help="commit but do not push")
    parser.add_argument("--staged", action="store_true",
                        help="only commit what is already staged (skip `git add .`)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip git pre-commit and commit-msg hooks")
    parser.add_argument("--verbose", action="store_true",
                        help="print the git commands being run")

    # `relay doctor` is a separate subcommand; every other invocation runs the
    # solo/team workflow. Subparsers are optional, so existing flags keep working.
    subparsers = parser.add_subparsers(dest="command", metavar="")
    doctor = subparsers.add_parser(
        "doctor",
        help="diagnose this Relay installation (PATH, git, AI credentials)",
        description="Read-only self-diagnostic. Exits 0 when healthy, 1 when a fix is needed.",
    )
    doctor.add_argument("--provider", choices=["gemini", "ollama"],
                        help="AI provider to check (default: gemini, or RELAY_AI_PROVIDER)")
    doctor.add_argument("--verbose", action="store_true",
                        help="print the git commands being run")

    pr = subparsers.add_parser(
        "pr",
        help="open a GitHub pull request for the current branch",
        description="Opens a PR against --base (default: main). Title falls back to "
                    "the latest commit message; requires GITHUB_TOKEN.",
    )
    pr.add_argument("--base", default="main",
                    help="base branch to merge into (default: main)")
    pr.add_argument("--title", metavar="TITLE",
                    help="PR title (default: latest commit message)")
    pr.add_argument("-o", "--open", action="store_true",
                    help="open the PR in the default web browser")
    pr.add_argument("--yes", action="store_true",
                    help="act without prompting (implies --open)")
    pr.add_argument("--verbose", action="store_true",
                    help="print the git commands being run")

    undo = subparsers.add_parser(
        "undo",
        help="undo the last commit (soft reset; changes stay staged)",
        description="Moves HEAD back one commit with `git reset --soft HEAD~1`.",
    )
    undo.add_argument("--verbose", action="store_true",
                      help="print the git commands being run")

    amend = subparsers.add_parser(
        "amend",
        help="rewrite the last commit's message with a freshly generated one",
        description="Amends the last commit (never pushes; syncing a pushed "
                    "commit needs `git push --force-with-lease`).",
    )
    amend.add_argument("--provider", choices=["gemini", "ollama"],
                       help="AI provider (default: gemini, or RELAY_AI_PROVIDER)")
    amend.add_argument("--timeout", type=int, metavar="SECONDS",
                       help="seconds to wait for the AI response (default: 30, max: 120)")
    amend.add_argument("--yes", action="store_true",
                       help="skip the confirmation prompt")
    amend.add_argument("--staged", action="store_true",
                       help="only amend what is already staged (skip `git add .`)")
    amend.add_argument("--dry-run", action="store_true",
                       help="show the plan; change nothing")
    amend.add_argument("--verbose", action="store_true",
                       help="print the git commands being run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Subcommand routing: `relay doctor` never touches the git workflow.
    if getattr(args, "command", None) == "doctor":
        try:
            return run_doctor(provider=args.provider, verbose=args.verbose)
        except Exception as exc:  # noqa: BLE001 - doctor must never traceback
            print(f"[relay doctor] error: {exc}")
            return 1

    # `relay pr` posts to GitHub; errors fall through to the shared handlers
    # below (UserAbort/RelayError/KeyboardInterrupt/fallback).
    try:
        if getattr(args, "command", None) == "pr":
            return run_pr(
                base=args.base,
                title=args.title,
                open_browser=args.open or args.yes or pr_open_browser(),
                verbose=args.verbose,
            )

        # `relay undo` is a pure local, non-destructive git op (no AI involved).
        if getattr(args, "command", None) == "undo":
            return run_undo(verbose=args.verbose)

        # `relay amend` reuses the solo workflow but rewrites the last commit
        # instead of creating a new one; it never pushes.
        if getattr(args, "command", None) == "amend":
            ai = build_provider(args.provider, timeout=args.timeout)
            orchestrator = Orchestrator(
                mode="amend",
                feature=None,
                provider=ai,
                yes=args.yes,
                no_push=True,
                staged_only=args.staged,
                no_verify=False,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            return orchestrator.run()

        # Resolve mode. `--team` sets args.team to "" (no feature) or a feature name;
        # `--solo` / nothing leaves it None.
        mode = "team" if args.team is not None else "solo"
        feature = args.team or None

        ai = build_provider(args.provider, timeout=args.timeout)
        orchestrator = Orchestrator(
            mode=mode,
            feature=feature,
            provider=ai,
            yes=args.yes,
            no_push=args.no_push,
            staged_only=args.staged,
            no_verify=args.no_verify,
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
