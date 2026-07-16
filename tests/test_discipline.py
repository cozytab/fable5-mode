#!/usr/bin/env python3
"""Tests for MODE: light triage and the structural fail-streak. Same
conventions as test_guards.py."""
import json, os, subprocess, tempfile, shutil, sys, time

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks")
SPAWN = os.path.join(HOOKS, "fable_spawn_guard.py")
CLOSE = os.path.join(HOOKS, "fable_close_guard.py")
STREAK = os.path.join(HOOKS, "fable_fail_streak.py")
INJ = os.path.join(HOOKS, "fable_profile_inject.py")

passed = failed = 0
def check(name, got, want):
    global passed, failed
    ok = got == want
    print(("PASS" if ok else "FAIL"), name, "got=%s want=%s" % (got, want))
    if ok: passed += 1
    else: failed += 1

def run(script, payload):
    p = subprocess.run([sys.executable, script], input=json.dumps(payload),
                       capture_output=True, text=True)
    return p.returncode

def run_out(script, payload):
    p = subprocess.run([sys.executable, script], input=json.dumps(payload),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr

tmps = []
def proj(ledger=None):
    d = tempfile.mkdtemp(prefix="fbdisc_")
    tmps.append(d)
    os.mkdir(os.path.join(d, ".git"))
    fd = os.path.join(d, ".fable"); os.mkdir(fd)
    if ledger is not None:
        with open(os.path.join(fd, "LEDGER.md"), "w") as f: f.write(ledger)
    return d

BIG = "x" * 2000
SMALL = "y" * 100
RUN_TAG = "%d" % (time.time() * 1000)

# ---- MODE: light (triage) ----
# 1. light mode: open cards do not block the stop
d = proj(ledger="MODE: light\n- [ ] 1. open card\n")
check("light/open-cards-dont-block", run(CLOSE, {"cwd": d}), 0)

# 2. light mode: evidence-on-close still enforced
d = proj(ledger="MODE: light\n- [x] 1. done\n")
check("light/evidence-still-enforced", run(CLOSE, {"cwd": d}), 2)

# 3. light mode: design gate off (big spawn without open cards allowed)
d = proj(ledger="MODE: light\n")
check("light/design-gate-off", run(SPAWN, {"cwd": d, "tool_name": "Agent",
      "tool_input": {"prompt": BIG}}), 0)

# 4. light mode: model ceiling STAYS armed
SID = "fbdisc-sonnet-" + RUN_TAG
subprocess.run([sys.executable, INJ], input=json.dumps(
    {"cwd": tempfile.mkdtemp(prefix="fbseed_"), "session_id": SID,
     "model": "claude-sonnet-5"}), capture_output=True, text=True)
d = proj(ledger="MODE: light\n- [ ] 1. card\n")
check("light/ceiling-stays", run(SPAWN, {"cwd": d, "session_id": SID,
      "tool_name": "Agent", "tool_input": {"prompt": SMALL, "model": "opus"}}), 2)

# 5. full mode unaffected (regression)
d = proj(ledger="MODE: full\n- [ ] 1. open card\n")
check("light/full-still-blocks", run(CLOSE, {"cwd": d}), 2)

# ---- structural fail-streak ----
FAIL_RESP = {"stdout": "", "stderr": "boom", "exitCode": 1}
OK_RESP = {"stdout": "ok", "stderr": "", "exitCode": 0}

def hit(d, sid, resp):
    return run_out(STREAK, {"cwd": d, "session_id": sid, "tool_name": "Bash",
                            "tool_input": {"command": "make test"},
                            "tool_response": resp})

# 1. failures 1-5: exit 0 (advisory at 3); failure 6+: exit 2 (structural)
d = proj(ledger="- [ ] 1. card\n")
sid = "fbdisc-streak-1-" + RUN_TAG
results = [hit(d, sid, FAIL_RESP) for _ in range(7)]
check("streak6/advisory-under-6", all(rc == 0 for rc, _, _ in results[:5]), True)
check("streak6/advisory-at-3", "attribution ladder" in results[2][1], True)
check("streak6/hard-at-6", results[5][0], 2)
check("streak6/stays-hard-past-6", results[6][0], 2)
check("streak6/demands-tried-note", "-- tried:" in results[5][2], True)

# 2. writing a `-- tried:` distillation into the ledger resets the streak
with open(os.path.join(d, ".fable", "LEDGER.md"), "a") as f:
    f.write("- [ ] 1b. card -- tried: ruled out cache; test asserts wrong port\n")
rc, _, _ = hit(d, sid, FAIL_RESP)
check("streak6/tried-note-resets", rc, 0)

# 3. success still resets (regression)
sid2 = "fbdisc-streak-2-" + RUN_TAG
d2 = proj(ledger="- [ ] 1. card\n")
for _ in range(6):
    hit(d2, sid2, FAIL_RESP)
hit(d2, sid2, OK_RESP)
rc, _, _ = hit(d2, sid2, FAIL_RESP)
check("streak6/success-resets", rc, 0)

# 4. PAUSED still disables the streak guard (regression)
d3 = proj(ledger="- [ ] 1. c\nPAUSED: side work\n")
sid3 = "fbdisc-streak-3-" + RUN_TAG
outs = [hit(d3, sid3, FAIL_RESP) for _ in range(7)]
check("streak6/paused-off", all(rc == 0 for rc, _, _ in outs), True)

for d in tmps:
    shutil.rmtree(d, ignore_errors=True)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
