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

from .commit import build_branch_name, sanitize_ai_message, validate_conventional
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
        dry_run: bool = False,
        verbose: bool = False,
        branch_template: str = "status/<feature>",
    ):
        self.mode = mode
        self.feature = feature
        self.ai = provider
        self.git = git or GitManager(verbose=verbose)
        self.yes = yes
        self.no_push = no_push
        self.dry_run = dry_run
        self.branch_template = branch_template

    # ---- Public entry point -------------------------------------------------

    def run(self) -> int:
        early = self._preflight()
        if early is not None:
            return early

        self.git.stage_all()

        diff = self.git.staged_diff()
        stat = self.git.staged_stat()
        if not diff.strip():
            print("[relay] nothing to commit: staged diff is empty.")
            return 0

        branch = self.git.current_branch()

        # Resolve the team-mode branch name BEFORE any mutation so --dry-run
        # can report the plan without creating the branch.
        team_branch = None
        if self.mode == "team":
            team_branch = self._resolve_team_branch_name()

        # GENERATE (with built-in fallback to manual input).
        message = self._obtain_message(diff, stat, branch)

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

        An empty answer aborts; anything else is committed verbatim.
        """
        print("Enter your commit message (one line; empty to abort):")
        message = input("> ").strip()
        if not message:
            raise UserAbort("aborted - no commit message provided")
        return message

    def _resolve_team_branch_name(self) -> str:
        """Feature-name precedence: --team <name> > prompt > current branch."""
        feature = self.feature
        if not feature:
            current = self.git.current_branch()
            feature = current.split("/")[-1] if current else None
            if not feature:
                feature = input("Feature name (for branch): ").strip()
        return build_branch_name(self.branch_template, feature)
