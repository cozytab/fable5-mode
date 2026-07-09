#!/usr/bin/env python3
"""fable-mode Close Guard  (Stop hook).

Two duties while a `.fable/LEDGER.md` exists (both loop-safe, both off when
the ledger is PAUSED):

1. Blocks ending the turn while the ledger still has open `- [ ]` items,
   so fable-mode can't quietly stop mid-plan (the "early-stopping" failure).
   Mark items `- [x]` (done+verified) or `- [~] ... -- deferred: reason`.
2. Evidence-on-close: blocks ending the turn while any `- [x]` item lacks an
   evidence marker (`-- evidence: ...` / `证据: ...`) — "report evidence, not
   adjectives" as a hard rule, not prose.

Inert unless a `.fable/LEDGER.md` is found. Loop-safe via stop_hook_active.
Fail-open on any error.

Exit codes: 0 = allow stop; 2 = block stop (stderr shown to Claude).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fable_common import (  # noqa: E402
    read_hook_input, start_dir, find_fable_dir, ledger_path, parse_ledger,
    closed_without_evidence,
)

MAX_LIST = 12


def main():
    data = read_hook_input()

    # Prevent an infinite stop/continue loop: if we already blocked once and
    # Claude is stopping again, let it through.
    if data.get("stop_hook_active"):
        return 0

    fable_dir = find_fable_dir(start_dir(data))
    if not fable_dir:
        return 0

    path = ledger_path(fable_dir)
    if not os.path.isfile(path):
        return 0  # no ledger -> nothing to enforce

    open_items, _has_any, paused = parse_ledger(path)
    if paused:
        return 0  # round paused -> enforcement off
    if not open_items:
        # All cards closed -> enforce evidence-on-close before allowing stop.
        bad = closed_without_evidence(path)
        if bad:
            shown = bad[:MAX_LIST]
            lines = "\n".join("    " + it for it in shown)
            if len(bad) > len(shown):
                lines += "\n    ... and %d more" % (len(bad) - len(shown))
            sys.stderr.write(
                "[fable-mode] BLOCKED stop: %d checked card(s) in %s carry no "
                "evidence marker:\n%s\n"
                "A card is only done when its acceptance actually ran. Append "
                "`-- evidence: <what proved it>` (a command + its result, a "
                "test count, a screenshot path) to each `- [x]` line — or "
                "uncheck the card and verify it now. Adjectives are not "
                "evidence.\n" % (len(bad), path, lines)
            )
            return 2
        return 0  # all closed, all evidenced -> allow stop

    shown = open_items[:MAX_LIST]
    more = len(open_items) - len(shown)
    lines = "\n".join("    " + it for it in shown)
    if more > 0:
        lines += "\n    ... and %d more" % more
    sys.stderr.write(
        "[fable-mode] BLOCKED stop: %d open ledger item(s) in %s\n%s\n"
        "Finish each item and verify it (its acceptance command), then mark "
        "`- [x]`; or if genuinely out of scope, mark `- [~] ... -- deferred: "
        "reason`. Do the work now rather than ending the turn.\n"
        % (len(open_items), path, lines)
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail-open: never trap the user in a session
        sys.stderr.write("[fable-mode] close guard error (ignored): %r\n" % e)
        sys.exit(0)
