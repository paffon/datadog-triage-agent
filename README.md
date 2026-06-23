# datadog-triage-agent

A small, hand-rolled Python agent that takes a production incident signal, pulls
correlated observability context (incident details, logs, traces) through **MCP
tools**, reasons to a root-cause hypothesis, and emits a structured
"one-click reproduce" recipe plus a candidate fix. It ships with an
**LLM-as-judge evaluation harness** that scores triage quality against
synthetic ground-truth incidents.

It runs **offline by default** — a local mock MCP server serves synthetic
fixtures, so there are no accounts or API keys to set up. The real Datadog
remote MCP server is wired in behind a flag (opt-in, documented below).

No agent frameworks. The agent loop is a plain capped turn loop over a one-function
LLM interface and a three-tool MCP surface — written out in
[`agent.py`](src/datadog_triage_agent/agent.py) so the reasoning is visible, not
buried in a library.

## How it works

```
   incident_id  ->  +------------------------------+  -> TriageResult
                    |        agent loop            |     { root_cause, confidence,
                    |  (hand-rolled, capped turns) |       evidence[], repro_steps[],
                    |  plan -> call tool -> observe |       candidate_fix }
                    +---------+----------+---------+
                              |          |
               complete(msgs, |          | call_tool(name, args)
                      tools)  v          v
            +---------------------+   +---------------------------+
            | LLM provider (1 fn) |   | MCP client (1 interface)  |
            |  complete(messages, |   |  get_incident /           |
            |           tools)    |   |  search_logs / get_traces |
            |  - claude_cli (def.) |   +----+-----------------+----+
            |  - anthropic_sdk    |        | TRIAGE_BACKEND= |
            +---------------------+        v mock            v datadog
                                    +------------+    +----------------+
                                    | mock MCP   |    | Datadog remote |
                                    | server     |    | MCP (HTTP,     |
                                    | (FastMCP,  |    | opt-in, creds) |
                                    | stdio,     |    +----------------+
                                    | fixtures)  |
                                    +------------+
```

- The LLM is driven as a **pure text engine** behind a single function,
  `complete(messages, tools) -> str`. Tool calls travel as an **in-prompt JSON
  protocol** (the model replies with one `{"action": ...}` object), not native
  tool use — so the same loop works identically across providers and is trivial
  to test with a fake LLM.
- Both backends expose the **same three tools** (`get_incident`, `search_logs`,
  `get_traces`), so the agent code is backend-agnostic — only the client differs.
- The eval harness runs the agent over every ground-truth incident and has a
  separate judge model score three dimensions (root-cause correctness, repro
  actionability, evidence grounding). Ground truth lives only in the fixture
  files and is **stripped server-side** before the agent ever sees an incident —
  the agent can't cheat.

## Quickstart (offline, no accounts)

Prerequisites: Python ≥ 3.10, [`uv`](https://docs.astral.sh/uv/), and the
`claude` CLI (the default LLM provider — uses your existing Claude Code login,
no API key).

```powershell
uv sync                 # create the venv, install deps
.\run.ps1 demo          # full triage on INC-1001, pretty-printed
.\run.ps1 eval          # run all 6 incidents, print a scoreboard, save eval_results/latest.json
.\run.ps1 test          # offline test suite (no `claude` needed)
.\run.ps1 lint          # ruff
.\run.ps1 typecheck     # mypy --strict
```

`run.ps1` is a thin Windows-first task runner; each task is just
`uv run python -m datadog_triage_agent.<module>`, which works on any platform.

`.\run.ps1 demo INC-1003` triages a different fixture. The six synthetic
incidents (`fixtures/incidents/INC-100{1..6}.json`) cover a payment-gateway
timeout cascade, DB connection-pool exhaustion, a bad-deploy NoneType, an
OOMKilled memory leak, an expired upstream credential, and a 429 retry-storm —
each with correlated logs and traces that actually point to the root cause.

## Seeing what the agent did (trace mode)

Both `demo` and `eval` take a verbosity flag — `-v`, `-vv`, `-vvv` (or
`--verbose`, or `TRIAGE_TRACE=1..3`) — that streams the loop's inner workings to
**stderr**. The final result / scoreboard stays on stdout, so `… -vv 1>out.txt`
still captures a clean result.

| Level | Adds                                                                                  |
| ----- | ------------------------------------------------------------------------------------- |
| `-v`  | each tool call + arguments + the observation it returned; turn headers; eval scores   |
| `-vv` | + every turn's raw LLM reply (the model's reasoning + chosen action); judge payload    |
| `-vvv`| + raw LLM transport (`claude -p` argv & stdout / Anthropic request & response)         |

```powershell
.\run.ps1 demo INC-1003 -v      # watch the agent investigate
.\run.ps1 eval -v               # per-incident trace + judge scores, then the scoreboard
```

It's plain stdlib `logging` on a `triage.*` logger tree, so third-party libraries
stay quiet at every level.

## Configuration

All knobs are environment variables (see [`.env.example`](.env.example); a `.env`
file is loaded if present). Defaults run the offline mock path.

| Variable             | Default    | Meaning                                  |
| -------------------- | ---------- | ---------------------------------------- |
| `TRIAGE_BACKEND`     | `mock`     | `mock` \| `datadog`                      |
| `TRIAGE_LLM`         | `cli`      | `cli` (`claude -p`) \| `anthropic` (SDK) |
| `TRIAGE_MODEL`       | `haiku`    | agent model (`haiku`/`sonnet`/`opus` or a full id) |
| `TRIAGE_JUDGE_MODEL` | `sonnet`   | eval judge model                         |
| `TRIAGE_MAX_TURNS`   | `6`        | agent tool-budget per incident           |

## Swappable LLM provider: the Anthropic SDK

The default provider is the `claude -p` CLI, because a Claude **subscription**
authenticates Claude Code out of the box but does *not* include an Anthropic API
key. The Anthropic SDK provider is implemented behind the same one-function
interface as a documented alternative (it needs API credits):

```powershell
uv sync --extra anthropic       # install the `anthropic` package
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:TRIAGE_LLM = "anthropic"
.\run.ps1 demo
```

It renders the tool catalog into the system prompt and uses the same in-prompt
JSON protocol, so the agent loop is byte-for-byte identical to the CLI path.

## Real Datadog backend (opt-in, not exercised here)

Setting `TRIAGE_BACKEND=datadog` points the same three-tool surface at Datadog's
remote MCP server over streamable HTTP, mapping our tool names onto Datadog's
(`search_datadog_logs`, `search_datadog_spans`/`get_datadog_trace`,
`get_datadog_incident`):

```powershell
$env:TRIAGE_BACKEND = "datadog"
$env:DATADOG_MCP_URL = "https://mcp.datadoghq.com/..."   # per your Datadog site
$env:DD_API_KEY = "..."
$env:DD_APPLICATION_KEY = "..."
.\run.ps1 demo
```

This path is **written and typed but not validated** — it was developed without
a Datadog account, so the exact auth scheme (OAuth vs API-key headers), the
remote tools' argument names, and the response normalization back into our
schema are marked `TODO(datadog-creds)` in
[`datadog.py`](src/datadog_triage_agent/mcp_backends/datadog.py). Treat it as a
documented integration point, not a tested feature.

## Limitations / next steps

- **The Datadog backend is unverified** (no account) — see the TODOs above.
- **The CLI provider is not deterministic.** `claude -p` exposes no temperature
  control, so eval scores vary run-to-run. The judge is discriminating (it
  catches, e.g., the agent embellishing "processor connection pool" into
  "database connection pool"), but treat the scoreboard as directional.
- **No prompt tuning.** The agent prompt is deliberately plain; raising eval
  scores by tightening "don't embellish beyond retrieved evidence" is left as a
  separate effort.
- The final `TriageResult` is not streamed token-by-token; for step-by-step
  visibility into the loop, use the `-v`/`-vv`/`-vvv` trace flag (above).

## Project layout

```
src/datadog_triage_agent/
  agent.py            # the hand-rolled async triage loop
  prompts.py          # system prompt + in-prompt JSON tool protocol
  models.py           # pydantic types (TriageResult, Incident, LogEntry, ...)
  config.py           # Settings.from_env() — single env-read point
  demo.py             # end-to-end triage on one incident
  llm/                # complete(messages, tools): claude_cli (default) | anthropic_sdk
  mcp_backends/       # TriageMCPClient (mock) | DatadogMCPClient (remote)
  mock_server/        # FastMCP stdio server; serves fixtures; strips ground_truth
  evals/              # harness + judge + rubric
fixtures/             # 6 synthetic incidents with correlated logs/traces + ground truth
tests/                # offline; run without the `claude` CLI
```
