#!/usr/bin/env python3
"""Tests for machine-written evidence: the Evidence Logger hook, the Close
Guard's citation corroboration, and REPLAY re-runs. Same conventions as
test_guards.py."""
import json, os, subprocess, tempfile, shutil, sys

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks")
CLOSE = os.path.join(HOOKS, "fable_close_guard.py")
EVLOG = os.path.join(HOOKS, "fable_evidence_log.py")

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

tmps = []
def proj(ledger=None, evlog=None):
    d = tempfile.mkdtemp(prefix="fbev_")
    tmps.append(d)
    os.mkdir(os.path.join(d, ".git"))
    fd = os.path.join(d, ".fable"); os.mkdir(fd)
    if ledger is not None:
        with open(os.path.join(fd, "LEDGER.md"), "w") as f: f.write(ledger)
    if evlog is not None:
        with open(os.path.join(fd, "evidence.jsonl"), "w") as f:
            for rec in evlog:
                f.write(json.dumps(rec) + "\n")
    return d

OK = {"ts": 1.0, "exit": 0}

# ---- Evidence Logger (recorder) ----
# 1. appends a record with the real command and exit code
d = proj(ledger="- [ ] 1. card\n")
run(EVLOG, {"cwd": d, "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
            "tool_response": {"stdout": "21 passed", "exitCode": 0}})
lp = os.path.join(d, ".fable", "evidence.jsonl")
rec = json.loads(open(lp).read().strip())
check("evlog/records-cmd", rec["cmd"], "pytest -q")
check("evlog/records-exit", rec["exit"], 0)

# 2. not opted in -> writes nothing
d2 = tempfile.mkdtemp(prefix="fbev_"); tmps.append(d2)
os.mkdir(os.path.join(d2, ".git"))
run(EVLOG, {"cwd": d2, "tool_name": "Bash",
            "tool_input": {"command": "echo x"},
            "tool_response": {"exitCode": 0}})
check("evlog/inert-without-optin",
      os.path.exists(os.path.join(d2, ".fable", "evidence.jsonl")), False)

# 3. records even while PAUSED (evidence gaps are worse than pauses)
d = proj(ledger="- [ ] 1. card\nPAUSED: side work\n")
run(EVLOG, {"cwd": d, "tool_name": "Bash",
            "tool_input": {"command": "echo paused"},
            "tool_response": {"exitCode": 0}})
check("evlog/records-while-paused",
      os.path.exists(os.path.join(d, ".fable", "evidence.jsonl")), True)

# ---- Close Guard: citation corroboration ----
# 1. cited command with successful run in log -> allow
d = proj(ledger="- [x] 1. done -- evidence: `pytest -q` 21 passed\n",
         evlog=[dict(OK, cmd="cd /x && pytest -q", tail="21 passed")])
check("corroborate/cited-and-ran-allows", run(CLOSE, {"cwd": d}), 0)

# 2. cited command NOT in log -> BLOCK (fabricated citation)
d = proj(ledger="- [x] 1. done -- evidence: `pytest -q` 21 passed\n",
         evlog=[dict(OK, cmd="echo hello", tail="hello")])
check("corroborate/cited-never-ran-blocks", run(CLOSE, {"cwd": d}), 2)

# 3. cited command ran but FAILED -> BLOCK
d = proj(ledger="- [x] 1. done -- evidence: `pytest -q` all good\n",
         evlog=[{"ts": 1.0, "cmd": "pytest -q", "exit": 1, "tail": "2 failed"}])
check("corroborate/cited-but-failed-blocks", run(CLOSE, {"cwd": d}), 2)

# 4. no log file at all (pre-logger project) -> old behavior, allow
d = proj(ledger="- [x] 1. done -- evidence: `pytest -q` 21 passed\n")
check("corroborate/no-log-failopen", run(CLOSE, {"cwd": d}), 0)

# 5. prose-only evidence (no backtick command) -> not machine-checked, allow
d = proj(ledger="- [x] 1. done -- evidence: screenshot at docs/x.png\n",
         evlog=[dict(OK, cmd="echo hi", tail="hi")])
check("corroborate/prose-evidence-unchecked", run(CLOSE, {"cwd": d}), 0)

# 6. acceptance backtick BEFORE the evidence marker is not a citation
d = proj(ledger="- [x] 1. thing — acceptance: `make test` -- evidence: "
                "ran the suite, 40 green\n",
         evlog=[dict(OK, cmd="echo unrelated", tail="")])
check("corroborate/acceptance-part-not-cited", run(CLOSE, {"cwd": d}), 0)

# 7. PAUSED still disables the close guard entirely (regression)
d = proj(ledger="- [x] 1. done -- evidence: `pytest -q` ok\nPAUSED: side\n",
         evlog=[dict(OK, cmd="echo other", tail="")])
check("corroborate/paused-allows", run(CLOSE, {"cwd": d}), 0)

# ---- Close Guard: REPLAY re-runs ----
# 1. replay armed, cited acceptance passes when re-run -> allow
d = proj(ledger="REPLAY: on\n- [x] 1. done -- evidence: `true` clean exit\n",
         evlog=[dict(OK, cmd="true", tail="")])
check("replay/pass-allows", run(CLOSE, {"cwd": d}), 0)

# 2. replay armed, cited command now fails -> BLOCK (regression caught)
d = proj(ledger="REPLAY: on\n- [x] 1. done -- evidence: `false` ok\n",
         evlog=[dict(OK, cmd="false", tail="")])
check("replay/fail-blocks", run(CLOSE, {"cwd": d}), 2)

# 3. no REPLAY line -> no replay (the same failing card passes the stop)
d = proj(ledger="- [x] 1. done -- evidence: `false` ok\n",
         evlog=[dict(OK, cmd="false", tail="")])
check("replay/off-by-default", run(CLOSE, {"cwd": d}), 0)

for d in tmps:
    shutil.rmtree(d, ignore_errors=True)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
