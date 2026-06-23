#!/usr/bin/env pwsh
# Task runner (Windows-first). Usage: ./run.ps1 <task> [args...]
#   demo | eval | mock-server | test | lint | typecheck
# Args after the task pass through verbatim, e.g. `demo INC-1003 -v` (trace level).
#
# Read args from $args rather than a param() block: a [Parameter()] block makes
# this an advanced function, which binds -v as the common -Verbose flag and
# swallows it before it reaches Python. $args keeps every token literal.

$Task = if ($args.Count -ge 1) { $args[0] } else { "help" }
$Rest = @($args | Select-Object -Skip 1)  # @() so a lone arg stays an array, not a string that @Rest splats char-by-char

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
