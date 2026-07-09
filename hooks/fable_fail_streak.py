#!/usr/bin/env python3
"""fable-mode Fail-Streak Reminder  (PostToolUse hook on Bash).

Grinding is the failure mode this catches: N consecutive failing commands
usually means the model is patching the wrong layer. At every 3rd consecutive
Bash failure it injects the attribution ladder as context:

    harness -> deployment -> product

(1) suspect the test/driver itself, (2) prove the new code is actually
running (cache/build/restart), (3) only then debug the product — and fix the
class via an invariant, not the instance.

Advisory only — never blocks (exit 0 always). Armed per project by `.fable/`;
off while the ledger is PAUSED. Streak state lives beside the model cache in
$TMPDIR/fable-mode-sessions/<sid>.fails and self-resets on the next success.
Fail-open on any error.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fable_common import (  # noqa: E402
    read_hook_input, start_dir, find_fable_dir, ledger_path, parse_ledger,
    load_fail_streak, save_fail_streak,
)

REMIND_EVERY = 3

_EXIT_CODE_RE = re.compile(r"[Ee]xit code[: ]+([0-9]+)")

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


def command_failed(tool_response):
    """Best-effort failure detection; uncertain -> treated as success."""
    r = tool_response
    if isinstance(r, str):
        return bool(_EXIT_CODE_RE.search(r) and
                    _EXIT_CODE_RE.search(r).group(1) != "0")
    if not isinstance(r, dict):
        return False
    for key in ("exitCode", "exit_code", "code", "returncode"):
        v = r.get(key)
        if isinstance(v, int):
            return v != 0
    for key in ("is_error", "isError"):
        if r.get(key) is True:
            return True
    text = " ".join(str(r.get(k, "")) for k in ("stdout", "stderr", "output"))
    m = _EXIT_CODE_RE.search(text)
    return bool(m and m.group(1) != "0")


def main():
    data = read_hook_input()
    sid = data.get("session_id")
    if not sid:
        return 0

    fable_dir = find_fable_dir(start_dir(data))
    if not fable_dir:
        return 0  # not opted in -> inert
    _open, _has, paused = parse_ledger(ledger_path(fable_dir))
    if paused:
        return 0

    if not command_failed(data.get("tool_response")):
        if load_fail_streak(sid):
            save_fail_streak(sid, 0)
        return 0

    streak = load_fail_streak(sid) + 1
    save_fail_streak(sid, streak)
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
    except Exception as e:  # advisory hook: never disturb the session
        sys.stderr.write("[fable-mode] fail-streak error (ignored): %r\n" % e)
        sys.exit(0)
