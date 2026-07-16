#!/usr/bin/env python3
"""fable-mode Fail-Streak Guard  (PostToolUse hook on Bash).

Grinding is the failure mode this catches: N consecutive failing commands
usually means the model is patching the wrong layer — and every further
attempt happens in a context polluted by the failures before it.

Two rungs:

  streak 3 (advisory, every 3rd): inject the attribution ladder —
      harness -> deployment -> product
  (1) suspect the test/driver itself, (2) prove the new code is actually
  running (cache/build/restart), (3) only then debug the product — and fix
  the class via an invariant, not the instance.

  streak >= 6 (structural, exit 2): insight alone hasn't worked — now the
  reset is mechanical. Every further failing command is answered with a
  blocking demand: STOP retrying; distill what was ruled out into the
  ledger card as `-- tried: <hypotheses eliminated, dead ends>`; then
  restart the card from a FRESH context (subagent or new session) that
  reads only SPEC + LEDGER — not the failure pile. Writing the `-- tried:`
  note (or a success) is what resets the streak: the distillation is the
  exit, so the lesson survives the context that learned it.

Armed per project by `.fable/`; off while the ledger is PAUSED. Streak
state lives beside the model cache in $TMPDIR/fable-mode-sessions/
<sid>.fails and self-resets on the next success. Fail-open on any error.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fable_common import (  # noqa: E402
    read_hook_input, start_dir, find_fable_dir, ledger_path, parse_ledger,
    load_fail_streak, save_fail_streak, response_exit_code,
)

REMIND_EVERY = 3
HARD_AT = 6

LADDER = (
    "[fable-mode] %d consecutive failing commands — before the next fix, walk "
    "the attribution ladder (cheapest layer first): (1) HARNESS: the test/"
    "driver/acceptance script is code too — falsify the test before the "
    "tested; (2) DEPLOYMENT: prove the code you just changed is actually "
    "running (behavior signature, cache-bust, rebuild/restart) — 'fix had no "
    "effect' is often 'fix never ran'; (3) PRODUCT: only now debug, and fix "
    "the class via an invariant, not the one observed symptom. If the same "
    "command keeps failing verbatim, stop retrying it."
)

RESET_DEMAND = (
    "[fable-mode] %d consecutive failing commands — this is a grind, and "
    "further attempts inside this failure pile get WORSE, not better. Do not "
    "run another fix attempt. Instead: (1) append to the current ledger card "
    "a distillation `-- tried: <hypotheses ruled out, dead ends, the one "
    "thing still unknown>`; (2) restart the card from a FRESH context — a "
    "subagent or new session that reads only SPEC + LEDGER, not this "
    "transcript. Writing the `-- tried:` note (or a passing command) resets "
    "this guard; more grinding does not."
)

# a `tried:` distillation line in the ledger is the structured exit
_TRIED_RE = re.compile(r"(tried|已试|排除)\s*[:：]", re.IGNORECASE)


def count_tried(lp):
    try:
        with open(lp, encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if _TRIED_RE.search(line))
    except Exception:
        return 0


def _tried_file(sid):
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "fable-mode-sessions")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(sid))[:120]
    return os.path.join(d, safe + ".tried")


def load_tried(sid):
    try:
        with open(_tried_file(sid), encoding="utf-8") as fh:
            return max(0, int(fh.read().strip() or 0))
    except Exception:
        return 0


def save_tried(sid, n):
    try:
        os.makedirs(os.path.dirname(_tried_file(sid)), exist_ok=True)
        with open(_tried_file(sid), "w", encoding="utf-8") as fh:
            fh.write(str(int(n)))
    except Exception:
        pass


def main():
    data = read_hook_input()
    sid = data.get("session_id")
    if not sid:
        return 0

    fable_dir = find_fable_dir(start_dir(data))
    if not fable_dir:
        return 0  # not opted in -> inert
    lp = ledger_path(fable_dir)
    _open, _has, paused = parse_ledger(lp)
    if paused:
        return 0

    if response_exit_code(data.get("tool_response")) in (None, 0):
        if load_fail_streak(sid):
            save_fail_streak(sid, 0)
        save_tried(sid, count_tried(lp))
        return 0

    # A new `-- tried:` distillation since the last failure is the structured
    # exit from a grind: accept it and start fresh.
    tried_now = count_tried(lp)
    streak = load_fail_streak(sid)
    if tried_now > load_tried(sid):
        streak = 0
    streak += 1
    save_fail_streak(sid, streak)
    save_tried(sid, tried_now)

    if streak >= HARD_AT:
        sys.stderr.write(RESET_DEMAND % streak + "\n")
        return 2  # strongest PostToolUse signal: stderr fed back to Claude
    if streak >= REMIND_EVERY and streak % REMIND_EVERY == 0:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": LADDER % streak,
            }
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail-open: never disturb the session
        sys.stderr.write("[fable-mode] fail-streak error (ignored): %r\n" % e)
        sys.exit(0)
