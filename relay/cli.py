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
import os
import sys

from . import __version__
from .ai import PROVIDER_NAMES, build_provider
from .completions import generate as generate_completions
from .config import pr_open_browser
from .doctor import run_doctor
from .errors import RelayError, UserAbort
from .man import MAN_PAGE_TEMPLATE
from .orchestrator import Orchestrator
from .pr import run_pr
from .squash import run_squash
from .stage import run_stage
from .telemetry import is_enabled, report, set_enabled
from .undo import run_undo


def _run_telemetry(action: str) -> int:
    """Manage the opt-in telemetry marker: status (default), on, or off."""
    if action in ("on", "off"):
        path = set_enabled(action == "on")
        state = "enabled" if action == "on" else "disabled"
        print(f"[relay] telemetry {state} (marker: {path})")
        return 0
    if is_enabled():
        print("[relay] telemetry: enabled (anonymous usage reporting, opt-in)")
    else:
        print("[relay] telemetry: disabled by default")
    print("[relay] enable with `relay telemetry on`; no URL, no data is sent")
    return 0


def _report_run(args, provider_name: str | None, ok: bool) -> None:
    """Fire a telemetry event for the just-finished workflow run (if opted in)."""
    command = getattr(args, "command", None)
    if command in ("amend", "squash"):
        mode = command
    elif getattr(args, "team", None) is not None:
        mode = "team"
    else:
        mode = "solo"
    report(mode=mode, provider=provider_name or "", ok=ok)


def _detect_shell() -> str:
    shell = os.environ.get("SHELL", "")
    if shell:
        name = shell.rsplit("/", 1)[-1]
        if name in ("bash", "zsh", "fish"):
            return name
    if os.name == "nt" and os.environ.get("PROMPT"):
        return "powershell"
    return "bash"


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

    parser.add_argument("--provider", choices=PROVIDER_NAMES,
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
    parser.add_argument("--allow-protected", action="store_true",
                        help="allow team mode to target a protected branch (default-branch safety override)")
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
    doctor.add_argument("--provider", choices=PROVIDER_NAMES,
                        help="AI provider to check (default: gemini, or RELAY_AI_PROVIDER)")
    doctor.add_argument("--verbose", action="store_true",
                        help="print the git commands being run")

    pr = subparsers.add_parser(
        "pr",
        help="open a pull request / merge request for the current branch",
        description="Opens a PR against --base (default: main). Title falls back to "
                    "the latest commit message; requires GITHUB_TOKEN.",
    )
    pr.add_argument("--base", default="main",
                    help="base branch to merge into (default: main)")
    pr.add_argument("--title", metavar="TITLE",
                    help="PR title (default: latest commit message)")
    pr.add_argument("-o", "--open", action="store_true",
                    help="open the PR in the default web browser")
    pr.add_argument("-d", "--draft", action="store_true",
                    help="create the PR as a draft (visible, not ready for review)")
    pr.add_argument("--yes", action="store_true",
                    help="act without prompting (implies --open)")
    pr.add_argument("--verbose", action="store_true",
                    help="print the git commands being run")

    squash = subparsers.add_parser(
        "squash",
        help="fold the last N commits into a single one (local, never pushes)",
        description="Soft-resets the last N commits and re-commits their combined "
                    "diff as one Conventional Commit (AI message with a "
                    "manual fallback). Working tree is untouched; never pushes.",
    )
    squash.add_argument("--count", type=int, default=2, metavar="N",
                        help="how many commits to squash (default: 2)")
    squash.add_argument("--message", metavar="MESSAGE",
                        help="use this message instead of generating one")
    squash.add_argument("--provider", choices=PROVIDER_NAMES,
                        help="AI provider (default: gemini, or RELAY_AI_PROVIDER)")
    squash.add_argument("--timeout", type=int, metavar="SECONDS",
                        help="seconds to wait for the AI response (default: 30, max: 120)")
    squash.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    squash.add_argument("--dry-run", action="store_true",
                        help="show the plan; change nothing")
    squash.add_argument("--verbose", action="store_true",
                        help="print the git commands being run")

    undo = subparsers.add_parser(
        "undo",
        help="undo the last commit (soft reset; changes stay staged)",
        description="Moves HEAD back one commit with `git reset --soft HEAD~1`.",
    )
    undo.add_argument("--verbose", action="store_true",
                      help="print the git commands being run")

    stage = subparsers.add_parser(
        "stage",
        help="interactively stage a subset of changed files (or hunks)",
        description="Lists unstaged/untracked files and stages the ones you "
                    "select (`git add --`). `-p` launches git's real `git add "
                    "-p` hunk picker, so you can stage individual hunks of a "
                    "file before a normal `relay` run commits them.",
    )
    stage.add_argument("-p", "--patch", action="store_true",
                       help="run git's interactive patch (hunk) picker")
    stage.add_argument("--verbose", action="store_true",
                       help="print the git commands being run")

    completions = subparsers.add_parser(
        "completions",
        help="print a shell completion script (bash/zsh/fish/powershell)",
        description="Generates a completion script for the requested shell. "
                    "Pipe the output into your shell's completion directory, "
                    "e.g. `relay completions bash > ~/.bash_completion.d/relay`.",
    )
    completions.add_argument(
        "shell",
        nargs="?",
        choices=["bash", "zsh", "fish", "powershell"],
        default=None,
        help="target shell (default: auto-detect from $SHELL/$ComSpec, else bash)",
    )

    man = subparsers.add_parser(
        "man",
        help="print the relay(1) manual page (roff) to stdout",
        description="Prints the man page source for `relay`. Pipe it through "
                    "`gzip` into a man directory (e.g. "
                    "`relay man | gzip -9 > /usr/local/share/man/man1/relay.1.gz`) "
                    "to get `man relay`.",
    )

    telemetry = subparsers.add_parser(
        "telemetry",
        help="view or change opt-in usage telemetry",
        description="Relay is telemetry-free by default. `relay telemetry on` "
                    "opts in to anonymous usage reporting (mode, provider, "
                    "outcome — never diffs or messages). Off by default; "
                    "reporting additionally needs RELAY_TELEMETRY_URL.",
    )
    telemetry.add_argument(
        "action",
        nargs="?",
        choices=["status", "on", "off"],
        default="status",
        help="status (default), on, or off",
    )

    amend = subparsers.add_parser(
        "amend",
        help="rewrite the last commit's message with a freshly generated one",
        description="Amends the last commit (never pushes; syncing a pushed "
                    "commit needs `git push --force-with-lease`).",
    )
    amend.add_argument("--provider", choices=PROVIDER_NAMES,
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

    # `relay completions` prints a generated shell script to stdout and exits.
    if getattr(args, "command", None) == "completions":
        shell = args.shell or _detect_shell()
        try:
            print(generate_completions(shell), end="")
            return 0
        except ValueError as exc:
            print(f"[relay] {exc}")
            return 1

    # `relay man` prints the man page source (roff) to stdout and exits.
    if getattr(args, "command", None) == "man":
        print(MAN_PAGE_TEMPLATE.rstrip(), end="")
        return 0

    # `relay telemetry` reads or flips the opt-in marker and exits.
    if getattr(args, "command", None) == "telemetry":
        return _run_telemetry(args.action)

    # `relay pr` posts to GitHub; errors fall through to the shared handlers
    # below (UserAbort/RelayError/KeyboardInterrupt/fallback).
    try:
        if getattr(args, "command", None) == "pr":
            return run_pr(
                base=args.base,
                title=args.title,
                open_browser=args.open or args.yes or pr_open_browser(),
                draft=args.draft,
                verbose=args.verbose,
            )

        # `relay undo` is a pure local, non-destructive git op (no AI involved).
        if getattr(args, "command", None) == "undo":
            return run_undo(verbose=args.verbose)

        # `relay stage` sculpts the index (whole files or `git add -p` hunks).
        if getattr(args, "command", None) == "stage":
            return run_stage(patch=args.patch, verbose=args.verbose)

        # `relay squash` folds the last N commits into one; never pushes.
        if getattr(args, "command", None) == "squash":
            provider = build_provider(args.provider, timeout=args.timeout)
            code = run_squash(
                provider=provider,
                count=args.count,
                message=args.message,
                yes=args.yes,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            _report_run(args, getattr(provider, "provider_name", ""), ok=code == 0)
            return code

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
            code = orchestrator.run()
            _report_run(args, getattr(ai, "provider_name", ""), ok=code == 0)
            return code

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
            allow_protected=args.allow_protected,
        )
        code = orchestrator.run()
        _report_run(args, getattr(ai, "provider_name", ""), ok=code == 0)
        return code
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
