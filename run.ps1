#!/usr/bin/env pwsh
# Task runner (Windows-first). Usage: ./run.ps1 <task> [args...]
#   demo | eval | mock-server | test | lint | typecheck
# demo/eval/mock-server target modules that land in later phases.

param(
    [Parameter(Position = 0)][string]$Task = "help",
    [Parameter(ValueFromRemainingArguments = $true)]$Rest
)

$ErrorActionPreference = "Stop"

switch ($Task) {
    "demo"        { uv run python -m datadog_triage_agent.demo @Rest }
    "eval"        { uv run python -m datadog_triage_agent.evals @Rest }
    "mock-server" { uv run python -m datadog_triage_agent.mock_server @Rest }
    "test"        { uv run pytest @Rest }
    "lint"        { uv run ruff check . @Rest }
    "typecheck"   { uv run mypy src @Rest }
    default       { Write-Host "Usage: ./run.ps1 demo|eval|mock-server|test|lint|typecheck" }
}
