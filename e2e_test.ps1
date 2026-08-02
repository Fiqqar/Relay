<#
e2e_test.ps1 - Safe end-to-end test for Relay (Windows / PowerShell)

WHAT IT DOES
  Creates a throwaway git repo under $env:TEMP, makes one dummy file change, and
  runs the real `relay --solo` binary against it. It never touches your real
  projects, never needs an API key, and never hits the network:

    * OLLAMA_BASE_URL is pointed at a dead port so the AI call fails
      deterministically -> the shipped CLI's manual-input fallback kicks in.
    * The expected commit message is piped into stdin so input() is answered.
    * --no-push means no remote is required.
  Finally it asserts the commit actually landed with the expected subject.

USAGE
    powershell -ExecutionPolicy Bypass -File e2e_test.ps1
#>
$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host "[e2e] $msg" -ForegroundColor Cyan }

# --- Locate the relay command (console script, else python -m relay) -------
$relayCmd = (Get-Command relay -ErrorAction SilentlyContinue).Source
if ($relayCmd) {
    $cmd = $relayCmd
    $relayArgs = @("--solo", "--no-push", "--provider", "ollama")
} else {
    Write-Step "relay not on PATH; falling back to 'python -m relay'"
    $cmd = "python"
    $relayArgs = @("-m", "relay", "--solo", "--no-push", "--provider", "ollama")
}

$expect = "fix: e2e test commit"
$repo = Join-Path ([System.IO.Path]::GetTempPath()) ("relay-e2e-" + [guid]::NewGuid().ToString("N").Substring(0, 8))

# Point Ollama at a dead port so the fallback path is deterministic even if a
# real Ollama server happens to be running on this machine.
$previousOllamaUrl = $env:OLLAMA_BASE_URL
$env:OLLAMA_BASE_URL = "http://127.0.0.1:9"

try {
    New-Item -ItemType Directory -Path $repo | Out-Null
    Write-Step "temp repo: $repo"

    git init -q $repo
    git -C $repo config user.email "e2e@relay.test"
    git -C $repo config user.name "Relay E2E"
    Set-Content -LiteralPath (Join-Path $repo "dummy.txt") -Value "hello from e2e`n"
    git -C $repo add .

    Push-Location $repo
    try {
        Write-Step "running: $cmd $($relayArgs -join ' ')  < stdin: $expect"
        # The correct way to pipe into a native command in PowerShell with args splatting
        $output = $expect | & $cmd @relayArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    Write-Host $output
    if ($code -ne 0) { throw "relay exited with code $code" }

    $subject = (git -C $repo log -1 --format=%s).Trim()
    if ($subject -ne $expect) { throw "commit subject mismatch: '$subject' != '$expect'" }

    Write-Step "PASS: solo flow committed '$subject'"
    Write-Step "PASS: temp repo cleaned up"
}
finally {
    if ($null -eq $previousOllamaUrl) { Remove-Item Env:OLLAMA_BASE_URL -ErrorAction SilentlyContinue }
    else { $env:OLLAMA_BASE_URL = $previousOllamaUrl }
    if (Test-Path -LiteralPath $repo) {
        Remove-Item -LiteralPath $repo -Recurse -Force -ErrorAction SilentlyContinue
    }
}