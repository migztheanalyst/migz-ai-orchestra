param(
  [Parameter(Position=0)][string]$Command = "help",
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$Root\conductor" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
$Python = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { throw "Python 3.11+ not found" }

switch ($Command) {
  "setup" { & "$Root\scripts\setup.ps1" @Rest; exit $LASTEXITCODE }
  "doctor" { & $Python "$Root\conductor\orchestra_doctor.py" --repo $Root @Rest; exit $LASTEXITCODE }
  "status" { & $Python "$Root\conductor\orchestra.py" $Root status @Rest; exit $LASTEXITCODE }
  "create" { & $Python "$Root\conductor\task_engine.py" create @Rest; exit $LASTEXITCODE }
  "run-next" { & $Python "$Root\conductor\orchestra.py" $Root run-next @Rest; exit $LASTEXITCODE }
  "run" { & $Python "$Root\conductor\orchestra.py" $Root run-next @Rest; exit $LASTEXITCODE }
  "preflight" { & $Python "$Root\conductor\provider_preflight.py" @Rest; exit $LASTEXITCODE }
  "release-check" { & $Python "$Root\conductor\release_reviewer.py" $Root @Rest; exit $LASTEXITCODE }
  default {
    Write-Host "MIGZ AI Orchestra"
    Write-Host "Commands: setup, doctor, status, create, run-next, preflight, release-check"
  }
}
