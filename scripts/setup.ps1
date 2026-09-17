param(
  [switch]$SkipModels,
  [switch]$FullModels,
  [switch]$WithDeepSeek
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { throw "Python 3.11+ not found" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git not found" }

& $Python -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'; print(sys.version.split()[0])"
$dirs = @("tasks\pending","tasks\running","tasks\review","tasks\passed","tasks\blocked","state","evidence","logs")
foreach ($dir in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null }

$Base = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL.TrimEnd('/') } else { "http://127.0.0.1:11434" }
try { Invoke-RestMethod -Uri "$Base/api/tags" -TimeoutSec 5 | Out-Null }
catch { throw "Ollama is not reachable at $Base. Install/start Ollama: https://ollama.com/download" }

function Pull-Model([string]$Model) {
  Write-Host "Ensuring model: $Model"
  if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $env:OLLAMA_HOST = $Base
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull failed: $Model" }
  } else {
    $body = @{ name=$Model; stream=$false } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$Base/api/pull" -ContentType "application/json" -Body $body -TimeoutSec 3600 | Out-Null
  }
}

if (-not $SkipModels) {
  Pull-Model "qwen2.5-coder:3b"
  if ($FullModels) {
    Pull-Model "qwen2.5-coder:7b"
    Pull-Model "qwen3.5:4b"
  }
  if ($WithDeepSeek) { Pull-Model "deepseek-r1:1.5b" }
}

$env:PYTHONPATH = "$Root\conductor" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })
& $Python "$Root\conductor\health_check.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Setup complete."
Write-Host "Next: .\orchestra.ps1 doctor"
Write-Host "Optional live verification: .\orchestra.ps1 doctor --probe"
