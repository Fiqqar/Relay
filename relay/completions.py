"""Shell completion scripts for relay — generated from one data table.

Shipping completions as a ``relay completions <shell>`` command (instead of
static files that drift from the CLI) guarantees the tab-completion words always
match the installed binary's actual subcommands and flags.

Supported shells:
    bash, zsh, fish, powershell

Usage:
    relay completions bash           # print to stdout
    relay completions bash > ~/.bash_completion.d/relay
    relay completions zsh > "${fpath[1]}/_relay"
    relay completions fish > ~/.config/fish/completions/relay.fish
    relay completions powershell > relay-completion.ps1
"""
from __future__ import annotations

# The single source of truth for what the completion scripts advertise. Kept in
# sync with the argparse definitions in relay/cli.py; order does not matter for
# any shell, but grouping keeps the generators readable.
SUBCOMMANDS = [
    "amend", "completions", "doctor", "man", "pr", "squash", "stage",
    "telemetry", "undo",
]

GLOBAL_FLAGS = [
    "--version", "--solo", "--team", "-m", "--message", "--provider",
    "--timeout", "--yes", "--dry-run", "--no-push", "--staged", "--no-verify",
    "-s", "--signoff", "--allow-protected", "--hunks", "--repo", "--verbose",
    "--validate-manual", "--allow-sensitive",
]

# Per-subcommand flags, one table for every shell. Values are the flag
# descriptions shown by zsh/fish; keys are the exact option strings argparse
# registers in relay/cli.py (test_completions asserts that parity both ways).
SUBCOMMAND_FLAGS: dict[str, dict[str, str]] = {
    "doctor": {
        "--provider": "AI provider to check",
        "--probe": "probe AI and forge endpoints",
        "--json": "print the report as JSON",
        "--verbose": "print the git commands being run",
    },
    "pr": {
        "--base": "branch to merge into",
        "--title": "pull request title",
        "-o": "open the PR in the browser",
        "--open": "open the PR in the browser",
        "-d": "open as a draft",
        "--draft": "open as a draft",
        "--body": "pull request body text",
        "--body-file": "read the body from a file",
        "-e": "edit the body in $EDITOR",
        "--edit": "edit the body in $EDITOR",
        "--yes": "skip the confirmation prompt",
        "--verbose": "print the git commands being run",
    },
    "squash": {
        "--count": "number of commits to squash",
        "--message": "message for the squashed commit",
        "--provider": "AI provider to use",
        "--timeout": "seconds to wait for the AI",
        "--yes": "skip the confirmation prompt",
        "--dry-run": "show the plan; change nothing",
        "-s": "add a Signed-off-by trailer",
        "--signoff": "add a Signed-off-by trailer",
        "--no-verify": "skip git hooks",
        "--verbose": "print the git commands being run",
    },
    "amend": {
        "--provider": "AI provider to use",
        "--timeout": "seconds to wait for the AI",
        "--yes": "skip the confirmation prompt",
        "--staged": "fold staged changes into the amended commit",
        "--dry-run": "show the plan; change nothing",
        "-s": "add a Signed-off-by trailer",
        "--signoff": "add a Signed-off-by trailer",
        "--verbose": "print the git commands being run",
    },
    "stage": {
        "-p": "pick hunks interactively",
        "--patch": "pick hunks interactively",
        "--allow-sensitive": "stage sensitive files without prompting",
        "--verbose": "print the git commands being run",
    },
    "undo": {
        "--verbose": "print the git commands being run",
    },
}

# One-line descriptions used by the fish generator. Fish takes a -a <name>
# token plus a -d <description>; keeping the map here (keyed by SUBCOMMANDS)
# preserves the helpful one-liners while the loop guarantees every subcommand
# is advertised.
_FISH_DESCRIPTIONS = {
    "amend": "rewrite the last commit message",
    "completions": "print a shell completion script",
    "doctor": "diagnose this install",
    "man": "print the relay(1) manual page",
    "pr": "open a pull request / merge request",
    "squash": "squash the last N commits",
    "stage": "interactively stage a subset of changed files",
    "telemetry": "view or change opt-in usage telemetry",
    "undo": "undo the last commit",
}

SHELLS = ("bash", "zsh", "fish", "powershell")


def _bash_list() -> str:
    return " ".join(GLOBAL_FLAGS + list(SUBCOMMANDS))


def _bash_subcommand_cases() -> str:
    """One branch per subcommand offering exactly that command's flags."""
    blocks = []
    for sub, flags in SUBCOMMAND_FLAGS.items():
        words = " ".join(flags)
        blocks.append(
            f'    if [[ "${{COMP_WORDS[1]}}" == {sub} ]]; then\n'
            f'        COMPREPLY=( $(compgen -W "{words}" -- "$cur") )\n'
            "        return 0\n"
            "    fi"
        )
    return "\n".join(blocks)


def bash_script() -> str:
    opts = _bash_list()
    sub_cases = _bash_subcommand_cases()
    return f"""# bash completion for relay
# Generated by `relay completions bash`. Source this in your ~/.bashrc.
_relay_complete()
{{
    local cur prev
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "{opts}" -- "$cur") )
        return 0
    fi
    if [[ "${{COMP_WORDS[1]}}" == completions ]]; then
        COMPREPLY=( $(compgen -W "bash zsh fish powershell" -- "$cur") )
        return 0
    fi
{sub_cases}
    COMPREPLY=( $(compgen -W "{opts}" -- "$cur") )
}}
complete -F _relay_complete relay
"""


def _zsh_flag_spec(flag: str, desc: str) -> str:
    return f"'{flag}[{desc}]'"


def _zsh_subcommand_cases() -> str:
    """A `case $words[1]` branch per subcommand, offering its own flags."""
    blocks = []
    for sub, flags in SUBCOMMAND_FLAGS.items():
        specs = " \\\n          ".join(_zsh_flag_spec(f, d) for f, d in flags.items())
        blocks.append(f"    {sub})\n      _arguments \\\n          {specs}\n      ;;")
    return "\n".join(blocks)


def zsh_script() -> str:
    subs = " ".join(SUBCOMMANDS)
    sub_cases = _zsh_subcommand_cases()
    return f"""#compdef relay
# Generated by relay completions zsh. Drop into $fpath as _relay.
_arguments -C \\
  '--solo[stage, commit and push to the current branch]' \\
  '-m[use this commit message instead of generating one]:message' \\
  '--message=[use this commit message instead of generating one]:message' \\
  '-s[add a Signed-off-by trailer]' \\
  '--signoff[add a Signed-off-by trailer]' \\
  '--team=[create & checkout a feature branch]:feature' \\
  '--provider[AI provider]:provider:(anthropic gemini groq mistral ollama openai xai)' \\
  '--timeout[seconds to wait for the AI response]:seconds' \\
  '--yes[skip the confirmation prompt]' \\
  '--dry-run[show the plan; change nothing]' \\
  '--no-push[commit but do not push]' \\
  '--staged[only commit what is already staged]' \\
  '--no-verify[skip git pre-commit and commit-msg hooks]' \\
  '--allow-protected[allow team mode to target a protected branch]' \\
  '--hunks[generate multi-part AI message per file/hunk]' \\
  '--repo=[run on this repo path]:repo:_files -/' \\
  '--verbose[print the git commands being run]' \\
  '--validate-manual[warn when a manually typed message is not a Conventional Commit]' \\
  '--allow-sensitive[stage potentially sensitive files without prompting]' \\
  '--version[print the relay version]' \\
  '1:subcommand:({subs})' \\
  '*::arg:->args'

case "$state" in
  args)
    case "$words[1]" in
{sub_cases}
    esac
    ;;
esac
"""


def fish_script() -> str:
    lines = [
        "# fish completion for relay",
        "# Generated by relay completions fish.",
        "complete -c relay -s h -l help -d 'Show help'",
    ]
    # Subcommand lines are generated from SUBCOMMANDS (single source of truth)
    # so a new subcommand can never be forgotten here, like bash/zsh/powershell.
    for subcommand in SUBCOMMANDS:
        lines.append(
            "complete -c relay -n '__fish_use_subcommand' "
            f"-a '{subcommand}' -d '{_FISH_DESCRIPTIONS[subcommand]}'"
        )
    # Per-subcommand flags come from SUBCOMMAND_FLAGS too, so bash/zsh/fish
    # advertise the same set for the same subcommand.
    for sub, flags in SUBCOMMAND_FLAGS.items():
        for flag, desc in flags.items():
            short = flag[1:] if not flag.startswith("--") else ""
            long = "" if short else flag[2:]
            spec = f"-s {short}" if short else f"-l {long}"
            lines.append(
                "complete -c relay -n "
                f"'__fish_seen_subcommand_from {sub}' {spec} -d '{desc}'"
            )
    lines += [
        "complete -c relay -n '__fish_use_subcommand' -l solo -d 'commit on the current branch'",
        "complete -c relay -n '__fish_use_subcommand' -l team -d 'create & checkout a feature branch'",
        "complete -c relay -n '__fish_use_subcommand' -l message -s m -r -d 'use this commit message instead of generating one'",
        "complete -c relay -n '__fish_use_subcommand' -l signoff -s s -d 'add a Signed-off-by trailer'",
        "complete -c relay -n '__fish_use_subcommand' -l provider -x -a 'anthropic gemini groq mistral ollama openai xai' -d 'AI provider'",
        "complete -c relay -n '__fish_use_subcommand' -l timeout -x -d 'seconds to wait for the AI'",
        "complete -c relay -n '__fish_use_subcommand' -l yes -d 'skip the confirmation prompt'",
        "complete -c relay -n '__fish_use_subcommand' -l dry-run -d 'show the plan; change nothing'",
        "complete -c relay -n '__fish_use_subcommand' -l no-push -d 'commit but do not push'",
        "complete -c relay -n '__fish_use_subcommand' -l staged -d 'only commit what is staged'",
        "complete -c relay -n '__fish_use_subcommand' -l no-verify -d 'skip git hooks'",
        "complete -c relay -n '__fish_use_subcommand' -l allow-protected -d 'allow team mode to target a protected branch'",
        "complete -c relay -n '__fish_use_subcommand' -l hunks -d 'generate multi-part AI message per file/hunk'",
        "complete -c relay -n '__fish_use_subcommand' -l repo -r -d 'run on this repo path'",
        "complete -c relay -n '__fish_use_subcommand' -l verbose -d 'print the git commands'",
        "complete -c relay -n '__fish_use_subcommand' -l validate-manual -d 'warn on non-conventional manual message'",
        "complete -c relay -n '__fish_use_subcommand' -l allow-sensitive -d 'stage sensitive files without prompting'",
        "complete -c relay -n '__fish_use_subcommand' -l version -d 'print the relay version'",
    ]
    return "\n".join(lines) + "\n"


def powershell_script() -> str:
    opts = " ".join(GLOBAL_FLAGS + list(SUBCOMMANDS))
    return f"""# PowerShell argument completer for relay
# Generated by relay completions powershell. Add to your $PROFILE:
#     . ``$PSScriptRoot/relay-completion.ps1``
Register-ArgumentCompleter -Native -CommandName relay -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $terms = @("{opts}" -split ' ')
    $terms | Where-Object {{ $_ -like "$wordToComplete*" }} | Sort-Object -Unique |
        ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }}
}}
"""


def generate(shell: str) -> str:
    """Return the completion script for ``shell``; raises ValueError otherwise."""
    normalized = shell.lower()
    if normalized not in SHELLS:
        raise ValueError(
            f"unsupported shell '{shell}'; choose from: {', '.join(SHELLS)}"
        )
    return {
        "bash": bash_script,
        "zsh": zsh_script,
        "fish": fish_script,
        "powershell": powershell_script,
    }[normalized]()


__all__ = [
    "SUBCOMMANDS",
    "GLOBAL_FLAGS",
    "SUBCOMMAND_FLAGS",
    "SHELLS",
    "generate",
]
