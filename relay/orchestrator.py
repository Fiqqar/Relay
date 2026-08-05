"""The Orchestrator: drives the solo/team workflow and owns the AI fallback.

Mirrors docs/FLOW.md:
    STAGE -> COLLECT_DIFF -> GENERATE -> [fallback: MANUAL_INPUT] -> CONFIRM
        -> BRANCH (team) -> COMMIT -> PUSH

The AI fallback is the heart of the product: if generation throws ANY AIError,
the workflow does NOT abort. It asks the user for a message with input() and
continues from the commit step, so a rate limit or an offline machine can
never leave the developer stranded.
"""
from __future__ import annotations

from .commit import (
    build_branch_name,
    extract_commit_type,
    sanitize_ai_message,
    validate_conventional,
)
from .config import DEFAULT_BRANCH_TEMPLATE
from .errors import AIError, GitError, UserAbort
from .git_manager import GitManager
from .prompt import CONFIRM_PROMPT, interpret_choice


class Orchestrator:
    def __init__(
        self,
        *,
        mode: str = "solo",
        feature: str | None = None,
        provider=None,  # AIManager, injected so tests can pass a fake
        git: GitManager | None = None,
        yes: bool = False,
        no_push: bool = False,
        staged_only: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        branch_template: str = DEFAULT_BRANCH_TEMPLATE,
    ):
        self.mode = mode
        self.feature = feature
        self.ai = provider
        self.git = git or GitManager(verbose=verbose)
        self.yes = yes
        self.no_push = no_push
        self.staged_only = staged_only
        self.dry_run = dry_run
        self.branch_template = branch_template

    # ---- Public entry point -------------------------------------------------

    def run(self) -> int:
        early = self._preflight()
        if early is not None:
            return early

        # --staged: honor the developer's own staging instead of `git add .`.
        # Skip only the staging step — the diff is still read from the index.
        if not self.staged_only:
            self.git.stage_all()

        diff = self.git.staged_diff()
        stat = self.git.staged_stat()
        if not diff.strip():
            label = "amend" if self.mode == "amend" else "commit"
            print(f"[relay] nothing to {label}: staged diff is empty.")
            return 0

        branch = self.git.current_branch()

        # GENERATE (with built-in fallback to manual input). The message is
        # produced BEFORE the team branch name is resolved, because the branch
        # prefix (feat/, fix/, docs/, ...) is derived from the commit type.
        message = self._obtain_message(diff, stat, branch)

        # AMEND (mode only): rewrite the last commit instead of adding a new
        # one. Never pushes — amending a pushed commit is a history rewrite.
        if self.mode == "amend":
            return self._run_amend(message, branch)

        # Resolve the team-mode branch name BEFORE any mutation so --dry-run
        # can report the plan without creating the branch.
        team_branch = None
        if self.mode == "team":
            team_branch = self._resolve_team_branch_name(message)

        if self.dry_run:
            target = team_branch if self.mode == "team" else branch
            print(f"[relay] dry-run (mode={self.mode}): commit & push to '{target}'")
            print(f"[relay]     message: {message}")
            return 0

        # BRANCH (team mode only): create & check out the feature branch.
        if self.mode == "team":
            self.git.create_branch(team_branch)
            branch = team_branch

        # COMMIT — the irreversible point. Everything before it is reversible.
        self.git.commit(message)

        if self.no_push:
            print(f"[relay] committed (--no-push): {message}")
            return 0

        # PUSH — if this fails the commit is already safe; report the exact
        # command to finish the job instead of pretending nothing happened.
        try:
            self.git.push(branch, set_upstream=self.mode == "team")
        except GitError as exc:
            print(f"[relay] committed, but push failed:\n{exc.stderr or exc}")
            upstream = "-u " if self.mode == "team" else ""
            print(f"[relay] retry with: git push {upstream}origin {branch}")
            return 1

        print(f"[relay] done: pushed to '{branch}'")
        return 0

    def _run_amend(self, message: str, branch: str) -> int:
        """Rewrite the last commit with the confirmed message.

        Deliberately never pushes: amending an already-pushed commit rewrites
        history, so the force-push decision stays with the developer. If the
        previous tip is on the remote, we say so and show the exact command.
        """
        old_tip = self.git.rev_parse("HEAD")
        if self.dry_run:
            print(f"[relay] dry-run (mode=amend): amend last commit on '{branch}'")
            print(f"[relay]     message: {message}")
            return 0
        self.git.commit(message, amend=True)
        print(f"[relay] amended last commit on '{branch}'")
        if old_tip and self.git.is_ancestor(old_tip, f"origin/{branch}"):
            print(
                "[relay] note: the amended commit was already pushed; syncing the "
                "remote needs `git push --force-with-lease`"
            )
        return 0

    # ---- Steps --------------------------------------------------------------

    def _preflight(self) -> int | None:
        """Fail fast BEFORE git add . so a misconfiguration never mutates state.

        Returns an exit code when the run should stop early, else None.
        """
        if not self.git.is_repo():
            raise GitError("not a git repository - run Relay from inside a work tree")
        if not self.git.has_changes():
            print("[relay] nothing to commit, working tree clean.")
            return 0
        if self.mode == "solo" and not self.git.has_remote():
            print("[relay] warning: no remote configured; push may fail.")
        return None

    def _obtain_message(self, diff: str, stat: str, branch: str) -> str:
        """Generate a message via AI with a hard fallback to manual input.

        Guarantees: never raises on AI failure; always returns a validated,
        user-approved message string.
        """
        attempts = 0
        while True:
            attempts += 1
            try:
                raw = self.ai.generate(diff, stat, branch)
                message = sanitize_ai_message(raw)
                valid, reason = validate_conventional(message)
                if not valid:
                    # A garbage response is treated exactly like an AI failure —
                    # the user should never have to look at nonsense.
                    print(f"[relay] AI response rejected ({reason}); falling back to manual input.")
                    return self._manual_input()
                print(f"[relay] AI message: {message}")
            except AIError as exc:
                # THE FALLBACK: catch any AI exception, ask the user for the
                # message with plain input(), and continue the workflow.
                print(f"[relay] AI unavailable ({exc}); falling back to manual input.")
                return self._manual_input()

            # Confirmation gate (skippable with --yes).
            if self.yes:
                return message
            action = interpret_choice(input(CONFIRM_PROMPT))
            if action == "accept":
                return message
            if action == "edit":
                return self._manual_input()
            if action == "retry" and attempts < 3:
                print("[relay] regenerating...")
                continue
            raise UserAbort("workflow aborted by user")

    def _manual_input(self) -> str:
        """The exact fallback we designed: a plain input() prompt, no exit.

        Supports a Conventional Commits body: type the subject on the first
        line, add body lines below, then press Enter on an empty line to
        finish. An immediately empty answer aborts; anything typed is
        committed (subject + optional body, blank line separated) verbatim.
        """
        print("Enter your commit message (subject, then optional body;")
        print("blank line to finish, Ctrl-C to abort):")
        lines = []
        while True:
            line = input("> ")
            if not line.strip():
                break
            lines.append(line.rstrip())
        message = "\n".join(lines).strip()
        if not message:
            raise UserAbort("aborted - no commit message provided")
        # Keep the subject as the first line and separate a body with a blank
        # line, so git (and changelog tools) treat the first line as subject.
        first, _, rest = message.partition("\n")
        if rest:
            return f"{first}\n\n{rest}"
        return message

    def _resolve_team_branch_name(self, message: str) -> str:
        """Feature-name precedence: --team <name> > prompt > current branch.

        The branch prefix is the Conventional Commit type extracted from the
        (already confirmed) message — ``feat(auth): ...`` -> ``feat/...`` —
        falling back to ``feat/...`` when the message has no valid type.
        """
        feature = self.feature
        if not feature:
            current = self.git.current_branch()
            feature = current.split("/")[-1] if current else None
            if not feature:
                feature = input("Feature name (for branch): ").strip()
        commit_type = extract_commit_type(message) or "feat"
        return build_branch_name(self.branch_template, feature, commit_type=commit_type)
