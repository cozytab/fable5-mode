#!/usr/bin/env python3
"""fable-mode Evidence Logger  (PostToolUse hook on Bash).

Machine-written evidence: appends every Bash command's real outcome
(command, exit code, output tail) to `.fable/evidence.jsonl`. The Close
Guard then verifies that any `command` a `- [x]` card cites as evidence
actually ran — and succeeded — in this recorded history.

This closes the honor-system gap: a model can type `-- evidence: pytest
21/21` without ever running pytest, but it cannot forge an entry in a log
only this hook writes. (It could still edit the file by hand — the log is
tamper-evident-by-convention, not cryptographic — but a fabrication now
requires a visible, auditable act instead of a plausible sentence.)

Passive recorder: always exit 0, never blocks, never prints. Armed per
project by `.fable/`; records even while PAUSED (pausing enforcement must
not create evidence gaps). Fail-open on any error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fable_common import (  # noqa: E402
    read_hook_input, start_dir, find_fable_dir, append_evidence,
    response_exit_code,
)


def main():
    data = read_hook_input()
    fable_dir = find_fable_dir(start_dir(data))
    if not fable_dir:
        return 0  # not opted in -> inert

    tool_input = data.get("tool_input") or {}
    cmd = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not cmd:
        return 0

    r = data.get("tool_response")
    exit_code = response_exit_code(r)
    tail = ""
    if isinstance(r, dict):
        tail = str(r.get("stdout") or r.get("output") or r.get("stderr") or "")
    elif isinstance(r, str):
        tail = r
    append_evidence(fable_dir, cmd, exit_code, tail)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # passive recorder: never disturb the session
        sys.stderr.write("[fable-mode] evidence log error (ignored): %r\n" % e)
        sys.exit(0)
