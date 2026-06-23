# Decisions & discoveries

The engineering log kept while building this project. Two kinds of entries:

- **Decision** — a design choice and *why*. The reasoning is the point; the code only
  shows the *what*.
- **Discovery** — an external fact (an API shape, a flag spelling, a platform gotcha)
  that isn't obvious from the code or from general knowledge, and that I'd otherwise
  have to re-derive.

It reads roughly in the order things were figured out, grouped by area.

---

## LLM provider & protocol

### Decision: default LLM = the `claude -p` CLI, not the Anthropic SDK
A Claude **subscription** authenticates the Claude Code CLI out of the box but does
*not* include an Anthropic API key — the API is a separate, separately-billed product.
`claude -p` rides the existing CLI login, so the project runs with zero keys, which is
what "runnable offline with no accounts" demands. The Anthropic SDK provider is still
implemented behind the same `complete(messages, tools)` interface as a swappable,
documented alternative — so the provider-agnostic design is real, not theoretical.

### Decision: in-prompt JSON tool protocol, not native tool use
`claude -p` is a text-completion engine — there's no clean way to surface native
tool-use blocks back through the CLI's `--output-format json`. Asking the model to reply
with a single JSON object (`{"action": "call_tool", ...}` or `{"action": "final", ...}`)
keeps the LLM interface to one function, works identically across providers, and makes
the loop's parser trivially testable with a scripted fake LLM. The cost — occasional
malformed-JSON retries — is handled by the loop's corrective nudge, which counts against
the turn budget.

### Decision: `complete()` is synchronous even though the loop is async
`claude -p` is a blocking `subprocess.run`. The loop is async *only* so the MCP
`ClientSession` can stay open across turns. During an LLM call nothing else needs the
event loop (the MCP session is idle), so blocking it briefly is fine — no thread executor,
no needless complexity.

---

## Driving `claude -p` from a subprocess

### Discovery: the `claude -p` CLI contract (verified against CLI v2.1.47)
- `claude -p "<prompt>" --output-format json` returns one JSON object; the assistant
  text is in the **`result`** field. Check `is_error` and the exit code for failure.
- `--model haiku|sonnet|opus` (aliases work; full IDs too).
- `--append-system-prompt "<text>"` layers onto the system prompt.
- **`--tools ""`** cleanly disables all built-in tools — turning it into a pure text
  engine that only follows our in-prompt protocol.

### Discovery (load-bearing): `claude -p` hangs when launched from a project directory
The first real call from inside this project **timed out after 120s**. Root cause:
`claude -p` spins up a full session that loads the working directory's MCP servers and
session hooks before answering. The lean flag set that makes it a fast, deterministic
text engine (verified: ~4s, clean result):
- `--tools ""` — no built-in tools.
- `--strict-mcp-config` — load only explicitly-passed MCP servers; with none passed,
  that's **zero**. *This is the flag that kills the hang.*
- `--setting-sources ""` — skip user/project/local settings → no hooks, deterministic.
- `--no-session-persistence` — don't write a session file per call.
- `stdin=subprocess.DEVNULL` in `subprocess.run` — don't block on inherited stdin.

### Discovery: the nested-session guard
`claude -p` refuses to launch from inside an existing CLI session (it sets `CLAUDECODE=1`
and `CLAUDE_CODE_SSE_PORT`). The wrapper scrubs those two vars from the child process
environment so the demo/eval run even when invoked from within a session. Normal user
runs are unaffected.

---

## The agent loop

### Decision: async loop, no `pytest-asyncio` dependency
The MCP `ClientSession` must stay open across all turns of a triage run, so the loop is
async. But pulling in `pytest-asyncio` just to test it isn't worth it — tests call
`asyncio.run(triage(...))` directly. One fewer dev dependency.

### Decision: `parse_action` decodes from the first `{` with `raw_decode`
`json.JSONDecoder().raw_decode` parses one JSON value and ignores trailing data, so it
transparently tolerates ` ```json ` fences and trailing prose; starting at the first `{`
skips leading prose. The known ceiling (noted in-code): it assumes the first `{` opens
the real action object — true for our JSON-only protocol; revisit if the model ever
emits decoy braces first.

### Decision: dynamic tool dispatch via `getattr`; `mcp` typed as `Any`
The loop dispatches with `getattr(mcp, tool)(**args)` after gating `tool` against the
known tool names. This decouples the loop from any concrete client and makes a fake MCP
trivial in tests. `mcp: Any` is honest (dispatch *is* dynamic) and passes `mypy --strict`.
Bad/extra kwargs raise `TypeError`, which is caught and fed back to the model as an
observation so it can recover.

### Decision: tools return JSON-serializable objects, not pydantic models
The agent feeds tool output back to the LLM as **text** (`json.dumps`). So the tool
contract is "return JSON-serializable Python (dict / list of dicts)," and the MCP client
can return the raw `structuredContent` payload directly — **no pydantic re-parse on the
wire path**. The `LogEntry`/`Trace`/`Incident` models stay as shape documentation and the
judge/tests' typed view. (This is simpler than the original plan, which called for parsing
into models everywhere.)

---

## MCP server & client

### Discovery: FastMCP `CallToolResult` shape depends on the tool's return type
Verified against `mcp 1.28.0` — the client parser must handle both:
- **dict return** (e.g. `get_incident`): `result.structuredContent` *is* the dict.
- **list return** (e.g. `search_logs`): `result.structuredContent` is **wrapped** as
  `{"result": [...]}`, and `result.content` has **one `TextContent` block per item**, not
  one block holding the whole array.
- **errors**: a tool that raises sets `result.isError`, with the message in
  `content[0].text`. So raising `ValueError` in a tool is a clean way to signal a
  recoverable error to the loop.

### Decision: the mock pools all fixtures and filters by service/query
The agent never asks for "INC-1001's logs" — it calls `get_incident(id)` to learn the
services + error signature, then `search_logs(query, service)` / `get_traces(service)`.
So the mock loads **all** files under `logs/` (and `traces/`) into one pool and filters,
mirroring how a real query API behaves. `get_traces`'s service filter matches a trace if
the service is the root *or* appears in any span, so "traces involving payment-gateway"
works even when checkout-service is the root.

### Decision: clients are `AsyncExitStack`-based context managers
Each client is two stacked async context managers (`stdio_client`/`streamablehttp_client`
→ `ClientSession`) that must both stay open for the whole run. Wrapping them in our own
async context manager with `AsyncExitStack` keeps the call site a single
`async with get_mcp_client(...) as mcp:` and matches how the loop wants one long-lived
object.

### Decision: factories take explicit args; `Settings.from_env()` is the only env read
`get_llm(provider, model)` and `get_mcp_client(backend)` take plain arguments rather than
each re-reading the environment. `Settings.from_env()` is the **single** place env is
read — one obvious spot to see every knob, default, and int-parse, and no env
monkeypatching in tests.

### Discovery: `streamablehttp_client` returns a 3-tuple and takes `headers=` directly
Its signature is `streamablehttp_client(url, headers=None, ...)` and it yields a **3-tuple**
`(read, write, get_session_id)` — not stdio's 2-tuple. So the Datadog client unpacks three
and passes the first two to `ClientSession`; auth headers go straight in via `headers=`,
no custom HTTP client needed.

### Decision: `get_mcp_client` returns a union, not a Protocol
Two structurally-identical async-context-manager clients with the same three-method
surface. A `Protocol` would be a one-implementation-per-method abstraction for something
the loop already dispatches against as `Any`. A `TriageMCPClient | DatadogMCPClient` union
is the minimal honest annotation — `mypy --strict` is happy and the call site is unchanged.

---

## Eval integrity & harness

### Decision: strip `ground_truth` server-side, not client-side
If the agent could ever see the ground-truth field, the evaluation would be meaningless.
Stripping happens in the mock server's `get_incident` — as close to the data as possible —
and is pinned by a unit test. The judge reads `ground_truth` directly from the fixture
files, never through the MCP surface.

### Decision: split the harness into `run_cases()` (injectable) + `main()` (env wiring)
`run_cases(incident_ids, mcp, agent_llm, judge_llm, max_turns)` is the testable core — the
eval tests drive it offline with scripted fakes over the *real* fixture files and assert
the scoreboard math. `main()` only wires `Settings` + factories, runs the loop, prints, and
saves. Each case is wrapped so one failure records a zero-score row instead of sinking the
whole run.

### Decision: distinct service names per incident
Because the mock pools all fixtures and filters by service, two incidents sharing a service
would bleed across a service-scoped search. Each incident uses its own service names so
per-incident triage stays clean.

### Discovery: the eval is discriminating, not a rubber stamp
A baseline run (haiku agent, sonnet judge) scored a mean of 4.5/6 across the six incidents.
One incident lost a root-cause point because the agent embellished a retrieved detail into
a claim the fixtures didn't support — and the judge caught it. That's the signal you want:
the harness penalizes confident-but-unsupported answers rather than rewarding fluency.

---

## The Anthropic SDK provider

### Decision: the SDK provider maps bare model aliases to full IDs
`claude -p` accepts bare aliases (`haiku`/`sonnet`/`opus`); the Anthropic SDK 404s on
those — it needs full IDs. `Settings` carries the bare alias, and the same string flows
through `get_llm(provider, model)` for both providers, so the SDK module owns a small
alias→ID map. The factory contract stays identical across providers — the mapping is the
provider's concern, not the caller's.

### Decision: `import anthropic` is lazy, inside `complete()`
`anthropic` is an optional extra, not installed in the default/test/typecheck environment.
A top-level import would make the module un-importable offline and kill its unit test.
Putting the import inside `complete()` (with a clean error on `ImportError`) keeps the
request-builder and the alias map importable and testable with no extra installed. The tool
catalog is rendered into the prompt by the *same* function the CLI provider uses — that
rendering must stay byte-identical across providers, so it's one function, not two copies.

---

## Cross-platform (Windows) gotchas

### Discovery: Windows cp1252 stdout crashes on the model's unicode
The agent loop ran fine, then crashed at `print()` with `UnicodeEncodeError` on a `→` —
Windows' default stdout encoding is cp1252, not UTF-8, and LLM output routinely contains
arrows and smart quotes. Fix: `force_utf8_stdout()` reconfigures stdout to UTF-8 (guarded
so it's a no-op on redirected streams). Anything that prints LLM-derived text needs it.

### Discovery: trace mode has to reconfigure **stderr** too
The trace output prints that same LLM text to **stderr**, which is *also* cp1252 on
Windows. So `setup_trace()` reconfigures stderr to UTF-8 as well — same root cause as
stdout, different stream.

### Discovery (load-bearing): the PowerShell runner was silently mangling pass-through flags
The verbosity flag worked via `python -m … -v` directly but not via `.\run.ps1 demo … -v`.
Two compounding PowerShell gotchas in the old `param()`-based runner:
1. **`-v` was eaten as `-Verbose`.** A `param()` block with attributes makes the script an
   *advanced function*, which gets PowerShell's common parameters — and `-v` is a unique
   prefix of `-Verbose`, so it bound there and never reached Python.
2. **A one-element remaining-args splat exploded character-by-character.** `$args[1..N]`
   returns a *scalar string* when there's exactly one trailing arg; splatting a scalar
   string into a native exe iterates its **characters**, so Python received `-` and `v` as
   two args.

   Fix: drop the `param()` block entirely (no advanced function → no common-parameter
   binding) and read `$args` directly, forcing an array with `@(...)` so a lone trailing
   arg stays an array. Rule of thumb for PowerShell pass-through: never use an attributed
   `param()` for remaining args, and always `@()`-wrap the splat.

---

## Trace / verbosity mode

### Decision: graduated trace = stdlib `logging` levels, not a custom global
"See what's happening under the hood" wanted to be *levels*, not a binary flag. Mapping
0–3 onto stdlib logging means zero custom gating/emit infrastructure: L1→`INFO`,
L2→`DEBUG`, L3→a custom `TRACE=5` below DEBUG. `setup_trace()` turns up **only** the
`triage` logger tree, so the module loggers propagate to the stderr handler while
third-party libraries (httpx/anthropic) stay quiet at every level. Crucially, **no
`verbose` parameter is threaded** through `triage()`/`complete()`/`judge()` — the level is
a logger setting, so level 0 is byte-identical to the pre-feature behavior, and each level
is automatically a strict superset of the one below.

---

## Tooling & packaging

### Decision: PEP 735 `[dependency-groups]`, not tool-specific dev-deps
`uv sync` installs the `dev` group by default, and PEP 735 is the standard spelling, which
keeps `pyproject.toml` tool-agnostic. `mypy` is `strict`; `ruff` is `line-length=100`,
`target=py310`.

### Decision: Windows-first task runner (`run.ps1` + `python -m`)
`make` isn't standard on Windows. The `python -m` entry points are cross-platform;
`run.ps1` is a thin shortcut over them. A Makefile would be extra surface to keep in sync
for no benefit on the target platform.

### Note: the Datadog backend is written, typed, and **unverified**
There's no Datadog account in this environment, so every spot needing a live server to
confirm — the auth scheme (OAuth vs API-key/app-key headers), the remote tools' exact
argument names, and normalizing Datadog's response shape back into our schema — is marked
`TODO(datadog-creds)`. It's a documented integration point, not a tested feature, and the
README's limitations section says so plainly.
