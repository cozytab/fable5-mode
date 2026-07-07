# fable-mode guard hooks

The enforcement layer: turn a few of fable-mode's prose rules into Claude Code
hooks that actually block — ledger-before-delegation and close-verification,
built around this repo's SPEC.md/PROGRESS.md conventions.

## Three hooks

| Hook | Event | What it does |
|---|---|---|
| `fable_profile_inject.py` | `SessionStart` | When the project has opted in, **auto-inject the tier by model + the six levers + ledger context recovery** (no need to type "use fable mode") |
| `fable_spawn_guard.py` | `PreToolUse` (Agent\|Task\|Workflow) | When opted in: **block a detailed spawn with no ledger** (forces the plan gate) and **block any spawn requesting a model stronger than the session's** (the model ceiling) |
| `fable_close_guard.py` | `Stop` | While the ledger still has unchecked items, **block ending the turn** (cures early stopping / spinning) |

`_fable_common.py` is the shared helper for all three (read stdin, walk up to find `.fable/`, parse the ledger).

## Opt-in signal: the `.fable/` directory (searched upward, bounded at git root)

The three hooks are registered in the global `settings.json` and fire for every
project, every session. "Does the project root have a `.fable/` directory" is
the switch:

- **Has `.fable/`** -> the three hooks take effect.
- **No `.fable/`** -> the three hooks pass through silently, as if absent — they never touch your other projects.

## Per-model tier selection (Profile Injector)

At SessionStart (only when the project has opted in), it reads the `model` field
from the hook input and auto-selects a tier, injecting it as context:

- `model` contains `fable` -> **throughput tier** (aggressive parallel delegation, async non-blocking, bulk offload).
- otherwise / `model` absent -> **conservative tier** (<=5 concurrent, inline-first).
- Override: env var `FABLE_MODE_PROFILE=auto|conservative|throughput`.

It also injects the open items from `.fable/LEDGER.md` for "context recovery"
(aligned with the context-hygiene lever).
Note: the `model` field is not guaranteed to be present; when absent it safely
defaults to the conservative tier. This is SessionStart-only info (there is no
`$CLAUDE_MODEL` environment variable).

## Ledger format `.fable/LEDGER.md` (checkbox state machine)

```
- [ ] 1. an open card (each card with a machine-checkable acceptance test)
- [x] 2. done and verified
- [~] 3. not this round -- deferred: reason
```

- `- [ ]` = open, blocks stop.
- `- [x]` / `- [~]` = closed.
- SPEC.md/PROGRESS.md remain the durable design/progress docs; LEDGER.md is only the enforcement-state snapshot of "what I committed to this round."

## Model ceiling (mechanical)

fable-mode's purpose is Fable-5-grade results **without** reaching up to Fable 5,
so the spawn guard blocks any spawn requesting a model **stronger than the
session's** (ranked `haiku < sonnet < opus < fable`):

- Checked on the `model` parameter (Agent/Task) and on `model: '...'` /
  `model = "..."` literals inside Workflow scripts. The regex is key-prefixed,
  so prose like "fable-mode" can never false-positive.
- The session model comes from a per-session cache written at SessionStart by
  the Profile Injector (`$TMPDIR/fable-mode-sessions/<session_id>.txt`, ~20
  bytes, self-cleans after 7 days) — PreToolUse hooks never receive `model`.
- Fail-open: unknown session model or unrecognized requested model -> allowed.
- Opt-out: `FABLE_ESCALATION=on` (you genuinely intend upward deferral).
- Checked before all exemptions — even a small spawn or a fork must not reach
  above the session model.

## Exemptions & safety

- **Small-spawn exemption**: payload < `FABLE_SPAWN_MIN_CHARS` (default 1500 chars) is not blocked.
- **Fork exemption**: a `subagent_type` containing `fork` is not blocked (it inherits full context, no spec tax).
- **Loop-safe**: the close guard passes through when it sees `stop_hook_active`, so you're never trapped.
- **Fail-open**: any hook exception passes through (exit 0) — it never bricks the session.

## Install / register

Easiest: run the installer at the repo root. It resolves its own location,
honors `CLAUDE_CONFIG_DIR`, and merges the hooks into `settings.json`
idempotently (re-run to re-point after a move; `--uninstall` to remove):

```bash
bash "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/fable-mode/install.sh"
```

To register by hand instead, merge these three entries into the `hooks` object
of `<config-dir>/settings.json` (don't overwrite the file). The
`${CLAUDE_CONFIG_DIR:-$HOME/.claude}` is expanded by the shell at hook-run time;
use your actual absolute clone path if it differs:

```json
"hooks": {
  "SessionStart": [{"hooks": [{"type": "command",
    "command": "python3 ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/fable-mode/hooks/fable_profile_inject.py"}]}],
  "PreToolUse": [{"matcher": "Agent|Task|Workflow",
    "hooks": [{"type": "command",
      "command": "python3 ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/fable-mode/hooks/fable_spawn_guard.py"}]}],
  "Stop": [{"hooks": [{"type": "command",
    "command": "python3 ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/fable-mode/hooks/fable_close_guard.py"}]}]
}
```

Requires `python3` (standard library only, no third-party deps). Then, in a
project, `mkdir .fable` and write `.fable/LEDGER.md` to enable enforcement there.

## Turn enforcement off

Delete the project's `.fable/` directory (or check every card to `- [x]`/`- [~]`).
To disable entirely, remove the hooks block from settings.json.

## Tests

No third-party deps, just run:

```bash
python3 tests/test_guards.py   # 13 cases: opt-in detection, ledger presence, small-spawn/fork exemptions, git-root boundary, loop-safety, fail-open
python3 tests/test_inject.py   #  9 cases: per-model tier, env override, ledger context recovery, JSON envelope, fail-open
```
