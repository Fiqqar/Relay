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

import os
import random
import shlex
import subprocess
import sys
import tempfile
import time

from .ai.base import filter_ignored_diff, filter_ignored_stat, split_diff_by_file
from .commit import (
    build_branch_name,
    extract_commit_type,
    sanitize_ai_message,
    validate_conventional,
)
from .config import DEFAULT_BRANCH_TEMPLATE
from .config import hook_post_push as get_post_push_hook
from .config import hook_pre_commit as get_pre_commit_hook
from .config import ignore_paths as get_ignore_paths
from .config import protected_branches as get_protected_branches
from .errors import AIError, GitError, UserAbort, sanitize_terminal
from .git_manager import GitManager
from .hooks import run_hook
from .prompt import CONFIRM_PROMPT, interpret_choice
from .protected import assert_branch_allowed, is_protected


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
        no_verify: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        hunks: bool = False,
        allow_protected: bool = False,
        protected_branches: list[str] | None = None,
        branch_template: str = DEFAULT_BRANCH_TEMPLATE,
        message: str | None = None,
    ):
        self.mode = mode
        self.feature = feature
        self.ai = provider
        self.git = git or GitManager(verbose=verbose)
        self.yes = yes
        self.no_push = no_push
        self.staged_only = staged_only
        self.no_verify = no_verify
        self.dry_run = dry_run
        self.verbose = verbose
        self.hunks = hunks
        self.allow_protected = allow_protected
        self.protected_branches = protected_branches or get_protected_branches()
        self.branch_template = branch_template
        self.message = message

    # ---- Public entry point -------------------------------------------------

    def run(self) -> int:
        early = self._preflight()
        if early is not None:
            return early

        # --staged: honor the developer's own staging instead of `git add .`.
        # Skip only the staging step — the diff is still read from the index.
        # --dry-run must never mutate the index: skip `git add .` and preview
        # via HEAD diff instead.
        if self.dry_run:
            if self.staged_only:
                diff = self.git.staged_diff()
                stat = self.git.staged_stat()
                is_binary = "Binary files" in diff and self.git.staged_diff_binary_only()
            else:
                diff = self.git.head_diff()
                stat = self.git.head_stat()
                is_binary = "Binary files" in diff and self.git.head_diff_binary_only()
        else:
            if not self.staged_only:
                self.git.stage_all()
            diff = self.git.staged_diff()
            stat = self.git.staged_stat()
            is_binary = "Binary files" in diff and self.git.staged_diff_binary_only()

        if not diff.strip():
            label = "amend" if self.mode == "amend" else "commit"
            print(f"[relay] nothing to {label}: staged diff is empty.")
            return 0

        # AI diff ignore paths: keep generated files out of the prompt without
        # hiding them from git. Env > file > default (no ignores).
        ignore_patterns = get_ignore_paths()
        diff_for_ai = filter_ignored_diff(diff, ignore_patterns)
        stat_for_ai = filter_ignored_stat(stat, ignore_patterns)
        if ignore_patterns and diff_for_ai.strip() != diff.strip():
            print(f"[relay] filtered {len(ignore_patterns)} ignore pattern(s) from AI prompt")
        if diff.strip() and not diff_for_ai.strip():
            print(
                "[relay] all staged changes match ignore patterns; "
                "AI prompt is empty — using manual input."
            )
            is_binary = False
            diff = ""
            stat = ""
        else:
            diff = diff_for_ai
            stat = stat_for_ai

        # TOCTOU guard: capture index tree before AI / confirmation
        tree_before: str | None = None
        if not self.dry_run:
            try:
                tree_before = self.git.write_tree()
            except GitError:
                tree_before = None

        branch = self.git.current_branch()

        # GENERATE (with built-in fallback to manual input). The message is
        # produced BEFORE the team branch name is resolved, because the branch
        # prefix (feat/, fix/, docs/, ...) is derived from the commit type.
        # An explicit --message skips AI entirely.
        if self.message and self.message.strip():
            msg = self.message.strip()
            valid, reason = validate_conventional(msg)
            if not valid:
                print(f"[relay] warning: '{msg}' is not a Conventional Commit ({reason})")
            if not self.yes and not self.dry_run:
                print(f"[relay] commit message: {msg}")
                action = interpret_choice(input(CONFIRM_PROMPT))
                if action == "accept":
                    message = msg
                elif action == "edit":
                    edited = self._open_in_editor(draft=msg)
                    message = edited if edited else self._manual_input(draft=msg)
                else:
                    raise UserAbort("workflow aborted by user")
            else:
                message = msg
        elif not diff.strip():
            print(
                "[relay] staged changes are binary-only or fully ignored; "
                "an AI cannot derive a commit message from them."
            )
            message = self._manual_input()
        elif is_binary:
            print(
                "[relay] staged changes are binary-only; an AI cannot derive a "
                "commit message from them."
            )
            message = self._manual_input()
        else:
            message = self._obtain_message(diff, stat, branch)

        # AMEND (mode only): rewrite the last commit instead of adding a new
        # one. Never pushes — amending a pushed commit is a history rewrite.
        if self.mode == "amend":
            if tree_before is not None:
                try:
                    tree_after = self.git.write_tree()
                except GitError:
                    tree_after = ""
                if tree_after != tree_before:
                    raise GitError(
                        "staged changes changed while Relay was running; review the index and retry"
                    )
            return self._run_amend(message, branch)

        # Resolve the team-mode branch name BEFORE any mutation so --dry-run
        # can report the plan without creating the branch.
        team_branch = None
        if self.mode == "team":
            team_branch = self._resolve_team_branch_name(message, current_branch=branch)
            blocked = is_protected(team_branch, self.protected_branches)

        force = self.allow_protected
        if self.dry_run:
            target = team_branch if self.mode == "team" else branch
            print(f"[relay] dry-run (mode={self.mode}): commit & push to '{target}'")
            print(f"[relay]     message: {message}")
            pre = get_pre_commit_hook()
            if pre:
                print(f"[relay]     hook pre_commit: {' '.join(pre)}")
            post = get_post_push_hook()
            if post:
                print(f"[relay]     hook post_push: {' '.join(post)}")
            if self.mode == "team" and blocked and not force:
                print(
                    f"[relay]     note: '{team_branch}' is a protected branch; "
                    "this run would be refused without --allow-protected"
                )
            return 0

        # Default-branch safety: refuse to touch a protected branch in team
        # mode unless the developer explicitly opted out (--allow-protected).
        # Solo mode keeps its convention of committing to the current branch.
        # `--yes` only skips the confirmation prompt; it never opts out of this
        # guard, so a scripted/CI run cannot silently land on main/master.
        if self.mode == "team":
            assert team_branch is not None
            assert_branch_allowed(
                team_branch, self.protected_branches, force=force
            )

        # TOCTOU: ensure the index is the same one the AI approved
        if tree_before is not None:
            try:
                tree_after = self.git.write_tree()
            except GitError:
                tree_after = ""
            if tree_after != tree_before:
                raise GitError(
                    "staged changes changed while Relay was running; review the index and retry"
                )

        # Custom pre_commit hook: runs before any git commit, argv-as-list.
        pre_hook = get_pre_commit_hook()
        if pre_hook:
            run_hook(pre_hook, verbose=self.verbose)

        # BRANCH (team mode only): create & check out the feature branch.
        if self.mode == "team":
            assert team_branch is not None
            original_branch = branch
            self.git.create_branch(team_branch)
            branch = team_branch
            try:
                self.git.commit(message, no_verify=self.no_verify)
            except (GitError, KeyboardInterrupt):
                # The commit failed or was interrupted on the freshly created branch:
                # it is an orphan holding nothing but the failed attempt. Put the
                # developer back on the original branch and delete it, so the
                # run never strands them on a branch with no commit. The
                # original branch (e.g. main) is untouched — only the orphan is
                # removed. Best-effort: if the rollback itself fails, surface
                # the original error and let the user clean up by hand.
                try:
                    self.git.checkout(original_branch)
                    self.git.delete_branch(team_branch)
                    print(
                        f"[relay] commit failed or interrupted; deleted the orphan branch "
                        f"'{team_branch}' and restored '{original_branch}'."
                    )
                except GitError:
                    print(
                        f"[relay] commit failed or interrupted; could not auto-clean the "
                        f"orphan branch '{team_branch}' (reflog: `git reflog`)."
                    )
                raise
        else:
            self.git.commit(message, no_verify=self.no_verify)

        if self.no_push:
            print(f"[relay] committed (--no-push): {message}")
            return 0

        # Solo push needs a branch name; on a detached HEAD
        # `git branch --show-current` returns "", so pushing would target an
        # empty ref. The commit is already safe — tell the developer how to
        # turn the detached commit into a pushed branch.
        if self.mode == "solo" and not branch:
            print(
                "[relay] warning: HEAD is detached; committed, but there is no "
                "branch to push."
            )
            print(
                "[relay] create and push a branch with: "
                "`git switch -c <branch>` then `git push -u origin <branch>`"
            )
            return 1

        # PUSH — if this fails the commit is already safe; report the exact
        # command to finish the job instead of pretending nothing happened.
        try:
            self.git.push(branch, set_upstream=self.mode == "team")
        except GitError as exc:
            safe = sanitize_terminal(exc.stderr or str(exc))
            print(f"[relay] committed, but push failed:\n{safe}")
            upstream = "-u " if self.mode == "team" else ""
            print(f"[relay] retry with: git push {upstream}origin {sanitize_terminal(branch)}")
            return 1

        # Custom post_push hook: runs after a successful push, argv-as-list.
        post_hook = get_post_push_hook()
        if post_hook:
            try:
                run_hook(post_hook, verbose=self.verbose)
            except GitError as exc:
                # Post-push is best-effort: the commit is already pushed, so a
                # hook failure is a warning, not a rollback.
                print(f"[relay] post_push hook failed: {sanitize_terminal(str(exc))}")
                if exc.stderr:
                    print(sanitize_terminal(exc.stderr))

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
            pre = get_pre_commit_hook()
            if pre:
                print(f"[relay]     hook pre_commit: {' '.join(pre)}")
            return 0
        pre = get_pre_commit_hook()
        if pre:
            run_hook(pre, verbose=self.verbose)
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
        user-approved message string. Transient failures (429 rate limits and
        5xx server errors) are retried twice with ~2s/4s backoff before the
        manual-input fallback kicks in.

        When ``hunks`` is enabled and the diff spans multiple files, each file
        block is sent to the AI separately so the final commit carries a
        multi-part Conventional Commit body (one subject per hunk).
        """
        if self.hunks:
            blocks = split_diff_by_file(diff)
            if len(blocks) > 1:
                return self._obtain_hunks_message(blocks, branch)
        if self.ai is None:
            # No provider available (missing API key, etc.): skip straight to
            # manual input — the fallback is a first-class mode, not an error.
            print("[relay] no AI provider configured; entering manual input.")
            return self._manual_input()
        user_retries = 0
        transient_tries = 0
        while True:
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
                # Transient failures (429 / 5xx) get 2 retries with short backoff.
                if exc.kind in {"rate_limited", "api_error"} and transient_tries < 2:
                    transient_tries += 1
                    print(f"[relay] AI {sanitize_terminal(str(exc))}; retrying ({transient_tries}/2)...")
                    time.sleep(1.0 * transient_tries + random.uniform(0.1, 0.5))
                    continue
                # THE FALLBACK: catch any AI exception, ask the user for the
                # message with plain input(), and continue the workflow.
                print(f"[relay] AI unavailable ({sanitize_terminal(str(exc))}); falling back to manual input.")
                return self._manual_input()

            # Confirmation gate (skippable with --yes).
            if self.yes:
                return message
            action = interpret_choice(input(CONFIRM_PROMPT))
            if action == "accept":
                return message
            if action == "edit":
                edited = self._open_in_editor(draft=message)
                return edited if edited else self._manual_input(draft=message)
            if action == "retry" and user_retries < 3:
                user_retries += 1
                print("[relay] regenerating...")
                continue
            raise UserAbort("workflow aborted by user")

    def _obtain_hunks_message(self, blocks: list[tuple[str, str]], branch: str) -> str:
        """Hunk-level AI: one AI call per file block, combined into a body."""
        if self.ai is None:
            print("[relay] no AI provider configured; entering manual input.")
            return self._manual_input()
        print(f"[relay] hunk-level: generating {len(blocks)} messages")
        user_retries = 0
        while True:
            messages: list[str] = []
            paths: list[str] = []
            for path, block in blocks:
                tries = 0
                while True:
                    try:
                        raw = self.ai.generate(block, path, branch)
                        msg = sanitize_ai_message(raw)
                        valid, reason = validate_conventional(msg)
                        if not valid:
                            print(f"[relay] AI hunk {sanitize_terminal(path or 'unknown')} rejected ({reason}); falling back to manual input.")
                            return self._manual_input()
                        messages.append(msg)
                        paths.append(path)
                        break
                    except AIError as exc:
                        if exc.kind in {"rate_limited", "api_error"} and tries < 2:
                            tries += 1
                            print(f"[relay] AI {sanitize_terminal(str(exc))}; retrying hunk {sanitize_terminal(path or '')} ({tries}/2)...")
                            time.sleep(1.0 * tries + random.uniform(0.1, 0.5))
                            continue
                        print(f"[relay] AI unavailable for hunk {sanitize_terminal(path or '')} ({sanitize_terminal(str(exc))}); falling back to manual input.")
                        return self._manual_input()
            subject = messages[0]
            if len(messages) == 1:
                combined = subject
            else:
                bullets = []
                for msg, path in zip(messages[1:], paths[1:], strict=False):
                    hint = f" ({path})" if path else ""
                    bullets.append(f"- {msg}{hint}")
                body = "\n".join(bullets)
                combined = f"{subject}\n\n{body}"
            print(f"[relay] AI hunk message: {combined}")
            if self.yes:
                return combined
            action = interpret_choice(input(CONFIRM_PROMPT))
            if action == "accept":
                return combined
            if action == "edit":
                edited = self._open_in_editor(draft=combined)
                return edited if edited else self._manual_input(draft=combined)
            if action == "retry" and user_retries < 3:
                user_retries += 1
                print("[relay] regenerating hunks...")
                continue
            raise UserAbort("workflow aborted by user")

    @staticmethod
    def _open_in_editor(draft: str = "") -> str | None:
        """Open $GIT_EDITOR / $EDITOR with the draft commit message in a temporary file.

        Returns the edited content if saved and non-empty, or None if the editor
        is unavailable, exits with an error, or the terminal is not interactive.
        """
        if not sys.stdin.isatty():
            return None
        editor = os.environ.get("GIT_EDITOR") or os.environ.get("EDITOR")
        if not editor:
            editor = "notepad" if sys.platform == "win32" else "nano"
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".commit.txt", delete=False, encoding="utf-8"
            ) as tmp:
                if draft:
                    tmp.write(draft)
                tmp_path = tmp.name
            cmd = shlex.split(editor) + [tmp_path]
            ret = subprocess.run(cmd, check=False)
            if ret.returncode == 0 and os.path.exists(tmp_path):
                with open(tmp_path, encoding="utf-8") as f:
                    content = f.read().strip()
                return content or None
            return None
        except Exception:
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _manual_input(self, draft: str = "") -> str:
        """The fallback manual input prompt.

        Supports multi-paragraph Conventional Commits:
        - Press Enter on an empty line to finish.
        - Enter '.' on an empty line to insert a paragraph separator.
        - Ctrl-C or empty answer aborts.
        """
        print("Enter your commit message (subject, then optional body;")
        print("blank line to finish, '.' for paragraph break, Ctrl-C to abort):")
        lines: list[str] = []
        while True:
            try:
                line = input("> ")
            except (EOFError, StopIteration):
                break
            stripped = line.strip()
            if stripped == ".":
                lines.append("")
            elif not stripped:
                break
            else:
                lines.append(line.rstrip())
        message = "\n".join(lines).strip()
        if not message and draft:
            message = draft.strip()
        if not message:
            raise UserAbort("aborted - no commit message provided")
        first, _, rest = message.partition("\n")
        if rest:
            rest = rest.lstrip("\n")
            return f"{first}\n\n{rest}"
        return message

    def _resolve_team_branch_name(self, message: str, current_branch: str = "") -> str:
        """Feature-name precedence: --team <name> > current branch > prompt.

        The branch prefix is the Conventional Commit type extracted from the
        (already confirmed) message — ``feat(auth): ...`` -> ``feat/...`` —
        falling back to ``feat/...`` when the message has no valid type.

        The current branch only counts when it is not itself a protected
        (default) branch: on ``main``/``master`` there is no feature name to
        inherit, so the developer is asked instead (L-10).
        """
        feature = self.feature
        if not feature:
            current = current_branch or self.git.current_branch()
            if current and not is_protected(current, self.protected_branches):
                parts = current.split("/", 1)
                feature = parts[1] if len(parts) > 1 else parts[0]
            if not feature:
                feature = self._prompt_feature_name()
        commit_type = extract_commit_type(message) or "feat"
        return build_branch_name(self.branch_template, feature, commit_type=commit_type)

    def _prompt_feature_name(self) -> str:
        """Ask for a feature name when neither --team nor the branch provides one.

        Kept as a one-line seam so a non-interactive / CI mode can replace just
        this prompt (and its sole ``input()`` call) without touching the branch
        resolution logic.
        """
        return input("Feature name (for branch): ").strip()
