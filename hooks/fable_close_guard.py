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
    closed_without_evidence, evidence_log_path, uncorroborated_citations,
    read_mode, read_replay, cited_commands,
)

MAX_LIST = 12
REPLAY_CMD_TIMEOUT = 30   # seconds per acceptance command (FABLE_REPLAY_TIMEOUT)
REPLAY_TOTAL_BUDGET = 120  # seconds across all replays in one stop


def replay_failures(ledger_p, project_root):
    """Re-run each `- [x]` card's cited acceptance command; list the failures.

    Only runs when the ledger has `REPLAY: on` (checked by the caller) — an
    explicit opt-in, because re-running acceptances at every stop costs real
    time. A command that exits non-zero or times out is a failure: 'it passed
    once' is not 'it still passes'. Budgeted so a heavy suite can't hang the
    stop indefinitely. Fail-open on unexpected errors.
    """
    import subprocess
    try:
        timeout = int(os.environ.get("FABLE_REPLAY_TIMEOUT",
                                     str(REPLAY_CMD_TIMEOUT)))
    except ValueError:
        timeout = REPLAY_CMD_TIMEOUT
    failures = []
    seen = set()
    spent = 0.0
    try:
        with open(ledger_p, encoding="utf-8", errors="replace") as fh:
            lines = [l.strip() for l in fh]
    except Exception:
        return []
    import time as _time
    for s in lines:
        if s[:5].lower() != "- [x]":
            continue
        for cmd in cited_commands(s):
            if cmd in seen:
                continue
            seen.add(cmd)
            if spent >= REPLAY_TOTAL_BUDGET:
                failures.append((cmd, "not replayed: %ds replay budget spent "
                                 "(raise FABLE_REPLAY_TIMEOUT or drop "
                                 "REPLAY: on)" % REPLAY_TOTAL_BUDGET))
                continue
            t0 = _time.time()
            try:
                p = subprocess.run(cmd, shell=True, cwd=project_root,
                                   capture_output=True, text=True,
                                   timeout=min(timeout,
                                               REPLAY_TOTAL_BUDGET - spent))
                if p.returncode != 0:
                    tail = (p.stderr or p.stdout or "").strip()[-160:]
                    failures.append((cmd, "exit %d: %s" % (p.returncode, tail)))
            except subprocess.TimeoutExpired:
                failures.append((cmd, "timed out"))
            except Exception as e:
                failures.append((cmd, "could not run: %r" % e))
            spent += _time.time() - t0
    return failures


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
    if read_mode(path) == "light":
        open_items = []  # light round: open cards don't block the stop
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
        # Machine corroboration: a card that cites a `command` as evidence
        # must have a successful run of that command in the evidence log
        # (written by the Evidence Logger hook, not by the model).
        unc = uncorroborated_citations(path, evidence_log_path(fable_dir))
        if unc:
            shown = unc[:MAX_LIST]
            lines = "\n".join("    " + it for it in shown)
            if len(unc) > len(shown):
                lines += "\n    ... and %d more" % (len(unc) - len(shown))
            sys.stderr.write(
                "[fable-mode] BLOCKED stop: %d checked card(s) cite an "
                "evidence `command` with NO successful run recorded in the "
                "evidence log (%s):\n%s\n"
                "The log is written by the Evidence Logger hook from real "
                "tool results — a cited command that never ran (or never "
                "exited 0) is not evidence. Run the acceptance command now, "
                "or fix the citation to the command that actually ran.\n"
                % (len(unc), evidence_log_path(fable_dir), lines)
            )
            return 2
        # Acceptance replay (opt-in via `REPLAY: on`): 'passed once' is not
        # 'still passes' — re-run each card's cited acceptance before the
        # round may end, so a later card can't silently break an earlier one.
        if read_replay(path):
            fails = replay_failures(path, os.path.dirname(fable_dir))
            if fails:
                shown = fails[:MAX_LIST]
                lines = "\n".join("    `%s` -> %s" % f for f in shown)
                if len(fails) > len(shown):
                    lines += "\n    ... and %d more" % (len(fails) - len(shown))
                sys.stderr.write(
                    "[fable-mode] BLOCKED stop: REPLAY is on and %d cited "
                    "acceptance command(s) do not pass when re-run now:\n%s\n"
                    "A card whose acceptance no longer passes is not done — "
                    "fix the regression (or, if the command is genuinely "
                    "stale, fix the citation), then stop.\n"
                    % (len(fails), lines)
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
        "Three legitimate exits: (1) finish each item, verify it (its "
        "acceptance command), mark `- [x] ... -- evidence: <proof>`; "
        "(2) genuinely out of scope -> `- [~] ... -- deferred: reason`; "
        "(3) the user is steering to unrelated work -> add a line "
        "`PAUSED: reason` to the ledger and continue with what they asked. "
        "Do NOT invent completion — pick the exit that matches reality.\n"
        % (len(open_items), path, lines)
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # fail-open: never trap the user in a session
        sys.stderr.write("[fable-mode] close guard error (ignored): %r\n" % e)
        sys.exit(0)
