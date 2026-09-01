"""relay(1) manual page source, rendered with ``relay man``.

The man page lives as a plain string so it can travel inside the wheel (no
extra data-file wiring) and is printed verbatim by the ``relay man`` subcommand,
which any user can pipe into their man directory:

    relay man | gzip -9 > /usr/local/share/man/man1/relay.1.gz

Matching the architecture in docs/ARCHITECTURE.md, this module holds only the
documentation payload; the CLI routes to it by name, just like doctor.py and
undo.py.
"""
from __future__ import annotations

from . import __version__

MAN_PAGE_TEMPLATE = fr""".TH RELAY 1 "{__version__}" "relay {__version__}"
.SH NAME
relay \- your Git workflow, on autopilot: AI Conventional Commits
.SH SYNOPSIS
.B relay
[\fIOPTIONS\fR]
.br
.B relay
[\-\-solo | \-\-team [\fIFEATURE\fR]]
.br
.B relay
.B doctor
.br
.B relay
.B pr
.BR [\-\-base \fIBRANCH\fR]
.BR [\-\-title \fITITLE\fR]
.BR [\-\-open\fR|\-\-draft\fR|\-\-yes\fR]
.br
.B relay
.B undo

.B relay
.B amend

.SH DESCRIPTION
.B Relay
reads your staged diff, hands it to an LLM (local
.B Ollama
or
.B Gemini
API), and returns a standards-compliant Conventional Commit message. If the AI
is down, rate-limited, or offline, Relay falls back to a manual message prompt
in the same terminal and continues the workflow from there.
.SH OPTIONS
.TP
.B \-\-solo
Stage all, generate a message, commit, and push to the current branch.
.TP
.B \-\-team \fIFEATURE\fR
Create and check out a new branch \fI<type>/<feature>\fR, commit, and push.
.TP
.B \-\-provider \fIname\fR
AI provider (\fIgemini\fR, \fIollama\fR, \fIopenai\fR, \fIanthropic\fR, \fImistral\fR, \fIgroq\fR, or \fIxai\fR).
\fIopenai\fR also talks to OpenAI-compatible local servers (llama.cpp, vLLM)
via \fIOPENAI_BASE_URL\fR. Default: \fIgemini\fR or \fIRELAY_AI_PROVIDER\fR.
.TP
.B \-\-timeout \fIseconds\fR
Seconds to wait for the AI response (default 30, max 120).
.TP
.B \-\-yes
Skip the confirmation prompt.
.TP
.B \-\-dry-run
Show the plan; change nothing.
.TP
.B \-\-no-push
Commit, but do not push.
.TP
.B \-\-staged
Only commit what is already staged (skip \fBgit add\fR).
.TP
.B \-\-no-verify
Skip git pre-commit and commit-msg hooks.
.TP
.B \-\-allow-protected
Allow team mode to target a protected branch (default-branch safety override).
.TP
.B \-\-hunks
Generate multi-part AI message per file/hunk (hunk-level AI messages).
.TP
.B \-\-repo \fIPATH\fR
Run on this repo path (repeatable; defaults to current dir; also \fI[repos]\fR in config / \fIRELAY_REPOS\fR).
.TP
.B \-\-verbose
Print the git commands being run.
.SH COMMANDS
.TP
.B doctor
Run a read-only self-diagnostic (PATH, git, AI credentials).
.TP
.B pr
Open a pull request / merge request for the current branch. Detects the host
from the \fIorigin\fR remote: GitHub (uses \fIGITHUB_TOKEN\fR), GitLab
(uses \fIGITLAB_TOKEN\fR), or Bitbucket Cloud (uses \fIBITBUCKET_TOKEN\fR).
Only \fIgitlab.com\fR is trusted by default on GitLab; a self-hosted GitLab
host must be added to \fIRELAY_TRUSTED_GITLAB_HOSTS\fR or the request is
refused before any token is sent.
.TP
.B undo
Undo the last commit with a soft reset (changes stay staged).
.TP
.B squash
Fold the last N commits into one (soft reset + single commit; never pushes).
.TP
.B stage
Interactively stage a subset of changed files, or hunks via \fBgit add -p\fR.
.TP
.B telemetry
View or change opt-in usage telemetry (off by default).
.TP
.B amend
Rewrite the last commit's message with a freshly generated one (never pushes).
.TP
.B completions
Print a shell completion script for bash, zsh, fish, or powershell.
.TP
.B man
Print this manual page (roff) to stdout.
.SH ENVIRONMENT
.TP
.I GEMINI_API_KEY
API key for the Gemini provider.
.TP
.I OPENAI_API_KEY
API key for the OpenAI provider (also used for OpenAI-compatible
servers such as llama.cpp via \fIOPENAI_BASE_URL\fR).
.TP
.I ANTHROPIC_API_KEY
API key for the Anthropic provider.
.TP
.I MISTRAL_API_KEY
API key for the Mistral provider.
.TP
.I GROQ_API_KEY
API key for the Groq provider.
.TP
.I XAI_API_KEY
API key for the xAI provider.
.TP
.I OLLAMA_BASE_URL
Base URL of a local Ollama server (default http://localhost:11434).
.TP
.I OLLAMA_MODEL
Ollama model name (default qwen2.5-coder:7b).
.TP
.I RELAY_AI_PROVIDER
Default provider name (gemini|ollama|openai|anthropic|mistral|groq|xai).
.TP
.I GITHUB_TOKEN
Personal access token used by \fBrelay pr\fR on GitHub.
.TP
.I GITLAB_TOKEN
Personal access token used by \fBrelay pr\fR on GitLab
(gitlab.com or a self-hosted instance you have trusted).
.TP
.I BITBUCKET_TOKEN
Username and App Password for \fBrelay pr\fR on Bitbucket Cloud, in
\fIusername:app_password\fR form (Bitbucket uses HTTP Basic auth, not a
single token).
.TP
.I RELAY_TRUSTED_GITLAB_HOSTS
Comma/space-separated allowlist of self-hosted GitLab hosts (beyond
\fIgitlab.com\fR) that \fBrelay pr\fR may send \fIGITLAB_TOKEN\fR to. The
host is derived from the \fIorigin\fR remote, so anything outside this list
is refused. Only ever trust instances you own.
.TP
.I RELAY_IGNORE_PATHS
Comma-separated globs hidden from AI prompt (e.g. \fIdist/*,*.lock\fR).
.TP
.I RELAY_REPOS
Comma-separated repository paths for multi-repo runs.
.SH EXIT STATUS
0 on success, 1 on a Relay or git error, 130 when the user aborts.
.SH SEE ALSO
.BR git (1),
.BR python (1)
"""
