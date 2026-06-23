# Screenshots

The top-level `README.md` embeds three terminal screenshots from this folder. To
(re)generate them, run each command in a terminal and save a screenshot of the output
under the exact filename below.

| File         | Command to capture                | What it should show                                                |
| ------------ | --------------------------------- | ------------------------------------------------------------------ |
| `demo.png`   | `.\run.ps1 demo`                  | The pretty-printed `TriageResult` for INC-1001 (root cause, evidence, reproduction steps, candidate fix). |
| `trace.png`  | `.\run.ps1 demo INC-1003 -v`      | The agent investigating live — tool calls, arguments, and observations streaming to stderr, then the final result. |
| `eval.png`   | `.\run.ps1 eval`                  | The per-incident + aggregate LLM-as-judge scoreboard across all six incidents. |

Tips: use a dark terminal theme, ~100-column width, and capture from the command line
down to the end of the output so the command being run is visible in the shot.
