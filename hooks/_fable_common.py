"""Shared helpers for fable-mode guard hooks.

Design invariants (keep these true, they are the safety contract):
- FAIL-OPEN: any unexpected error must let the session proceed (exit 0). A bug
  in a guard must never brick the user's Claude Code session.
- OPT-IN: a guard only does anything when the project has opted into fable-mode
  enforcement by having a `.fable/` directory somewhere from cwd up to the root.
  No `.fable/` dir  ->  guards are inert.
"""
import json
import os
import re
import sys
import tempfile
import time


def read_hook_input():
    """Parse the hook JSON delivered on stdin. Returns {} on any problem."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def start_dir(data):
    """Best-effort project dir: hook 'cwd' field, else process cwd."""
    cwd = data.get("cwd")
    if cwd and os.path.isdir(cwd):
        return cwd
    try:
        return os.getcwd()
    except Exception:
        return "."


def find_fable_dir(start):
    """Walk up from `start` looking for a `.fable/` directory.

    Stops at the filesystem root or at a git repo root (whichever comes first),
    so a stray `.fable` far up the tree can't accidentally arm every project.
    Returns the absolute path to the `.fable` dir, or None.
    """
    try:
        cur = os.path.abspath(start)
    except Exception:
        return None
    while True:
        cand = os.path.join(cur, ".fable")
        if os.path.isdir(cand):
            return cand
        # git root is a natural project boundary; don't cross it.
        if os.path.isdir(os.path.join(cur, ".git")):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:  # filesystem root
            return None
        cur = parent


def ledger_path(fable_dir):
    return os.path.join(fable_dir, "LEDGER.md")


# --- model-tier ranking & per-session model cache (for the model ceiling) ---

TIER_ORDER = ("haiku", "sonnet", "opus", "fable")


def model_tier(model_str):
    """Rank a model string by capability keyword; None if unrecognized."""
    s = (model_str or "").lower()
    tiers = [i for i, k in enumerate(TIER_ORDER) if k in s]
    return max(tiers) if tiers else None


def _sessions_dir():
    d = os.path.join(tempfile.gettempdir(), "fable-mode-sessions")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_sid(session_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(session_id))[:120]


def save_session_model(session_id, model):
    """Cache the session's model at SessionStart so PreToolUse guards (which
    never receive `model`) can enforce the ceiling. Best-effort, fail-open."""
    if not session_id or not model:
        return
    try:
        d = _sessions_dir()
        now = time.time()
        for f in os.listdir(d):  # opportunistic self-cleanup, no SessionEnd hook needed
            p = os.path.join(d, f)
            try:
                if now - os.path.getmtime(p) > 7 * 86400:
                    os.remove(p)
            except OSError:
                pass
        with open(os.path.join(d, _safe_sid(session_id) + ".txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(str(model))
    except Exception:
        pass


def load_session_model(session_id):
    if not session_id:
        return None
    try:
        with open(os.path.join(_sessions_dir(), _safe_sid(session_id) + ".txt"),
                  encoding="utf-8") as fh:
            return fh.read().strip() or None
    except Exception:
        return None


# --- evidence-on-close convention (lever 4: report evidence, not adjectives) ---

EVIDENCE_RE = re.compile(r"(evidence|verified|证据|凭证|验证)\s*[:：]", re.IGNORECASE)


# --- machine-written evidence log (.fable/evidence.jsonl) ---
#
# The Evidence Logger hook appends one JSON line per Bash command:
#   {"ts": <epoch>, "cmd": <command>, "exit": <int>, "tail": <output tail>}
# The Close Guard checks cited `commands` on `- [x]` cards against this log,
# so "the acceptance actually ran" is machine truth, not a self-reported note.

EVIDENCE_LOG = "evidence.jsonl"
EVIDENCE_LOG_MAX_BYTES = 512 * 1024  # rotate: keep the newest half beyond this
EVIDENCE_TAIL_CHARS = 200

_BACKTICK_RE = re.compile(r"`([^`]+)`")


def evidence_log_path(fable_dir):
    return os.path.join(fable_dir, EVIDENCE_LOG)


def response_exit_code(tool_response):
    """Best-effort exit code from a Bash tool_response; None when unknown."""
    r = tool_response
    if isinstance(r, str):
        m = re.search(r"[Ee]xit code[: ]+([0-9]+)", r)
        return int(m.group(1)) if m else None
    if not isinstance(r, dict):
        return None
    for key in ("exitCode", "exit_code", "code", "returncode"):
        v = r.get(key)
        if isinstance(v, int):
            return v
    for key in ("is_error", "isError"):
        if r.get(key) is True:
            return 1
    text = " ".join(str(r.get(k, "")) for k in ("stdout", "stderr", "output"))
    m = re.search(r"[Ee]xit code[: ]+([0-9]+)", text)
    return int(m.group(1)) if m else None


def append_evidence(fable_dir, cmd, exit_code, tail):
    """Append one run record; rotate the log when it grows too large.
    Best-effort, fail-open — recording must never disturb the session."""
    try:
        path = evidence_log_path(fable_dir)
        try:
            if os.path.getsize(path) > EVIDENCE_LOG_MAX_BYTES:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines[len(lines) // 2:])
        except OSError:
            pass
        rec = {"ts": time.time(), "cmd": str(cmd)[:2000],
               "exit": exit_code,
               "tail": str(tail or "")[-EVIDENCE_TAIL_CHARS:]}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _norm_cmd(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def cited_commands(card_line):
    """Backtick-quoted commands in the *evidence part* of a `- [x]` line.
    Returns [] when the evidence note cites no command (prose-only note)."""
    m = EVIDENCE_RE.search(card_line)
    if not m:
        return []
    return [_norm_cmd(c) for c in _BACKTICK_RE.findall(card_line[m.end():])
            if _norm_cmd(c)]


def evidence_log_has_run(log_path, cited, want_success=True):
    """True if the log records a run whose command matches `cited`
    (normalized substring, either direction) — successful when want_success."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                cmd = _norm_cmd(rec.get("cmd", ""))
                if not cmd:
                    continue
                if cited in cmd or cmd in cited:
                    if not want_success or rec.get("exit") == 0:
                        return True
    except Exception:
        return False
    return False


def uncorroborated_citations(ledger_p, log_path):
    """`- [x]` cards whose cited evidence command never ran successfully.

    Machine check for "the acceptance actually ran": a card that cites a
    `command` as evidence must have a successful run of that command in the
    evidence log. Cards with prose-only evidence are not checked here (the
    substantive-string rule still applies to them). Returns [] when the log
    doesn't exist yet (projects predating the logger) — fail-open.
    """
    if not os.path.isfile(log_path):
        return []
    bad = []
    try:
        with open(ledger_p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s[:5].lower() != "- [x]":
                    continue
                cites = cited_commands(s)
                if cites and not any(
                        evidence_log_has_run(log_path, c) for c in cites):
                    bad.append(s)
    except Exception:
        return []
    return bad


# --- model-routing profiles (quality / balanced / frugal) ---

ROUTING_PROFILES = ("quality", "balanced", "frugal")
_ROUTING_RE = re.compile(r"^ROUTING\s*[:：]\s*(quality|balanced|frugal)\b",
                         re.IGNORECASE)
_TIER_RE = re.compile(r"^TIER\s*[:：]\s*(throughput|conservative)\b",
                      re.IGNORECASE)


def read_tier(path):
    """Per-round concurrency tier from a `TIER: <tier>` ledger line, or None.

    Same pattern as ROUTING — the user says a word, the model writes the line,
    the choice persists for the round and stays auditable. Fail-open.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _TIER_RE.match(line.strip())
                if m:
                    return m.group(1).lower()
    except Exception:
        return None
    return None


_REPLAY_RE = re.compile(r"^REPLAY\s*[:：]\s*(on|off)\b", re.IGNORECASE)
_MODE_RE = re.compile(r"^MODE\s*[:：]\s*(light|full)\b", re.IGNORECASE)


def read_mode(path):
    """Per-round ceremony weight from a `MODE: light|full` ledger line.

    'light' = triage for small rounds: the design gate and open-cards-block-
    stop are off, but evidence honesty (and the model ceiling) stay armed.
    Default 'full'. Fail-open to 'full' on any read problem.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _MODE_RE.match(line.strip())
                if m:
                    return m.group(1).lower()
    except Exception:
        return "full"
    return "full"


def read_replay(path):
    """True when the ledger opts into acceptance replay (`REPLAY: on`)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _REPLAY_RE.match(line.strip())
                if m:
                    return m.group(1).lower() == "on"
    except Exception:
        return False
    return False


def read_routing(path):
    """Per-round routing profile from a `ROUTING: <profile>` ledger line.

    Returns 'quality'|'balanced'|'frugal', or None when absent/unrecognized
    (callers fall back to the default). Fail-open on any read problem.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _ROUTING_RE.match(line.strip())
                if m:
                    return m.group(1).lower()
    except Exception:
        return None
    return None


MIN_EVIDENCE_CHARS = 6


def closed_without_evidence(path):
    """List `- [x]` ledger lines whose evidence marker is missing OR hollow.

    Convention: a card may only be checked `- [x]` together with a substantive
    evidence note (`-- evidence: <command output / screenshot / test count>`).
    A marker followed by fewer than MIN_EVIDENCE_CHARS characters ("evidence:
    ok") is treated as missing — adjectives are not evidence.
    Returns [] on any read problem (fail-open).
    """
    bad = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s[:5].lower() != "- [x]":
                    continue
                m = EVIDENCE_RE.search(s)
                if not m or len(s[m.end():].strip()) < MIN_EVIDENCE_CHARS:
                    bad.append(s)
    except Exception:
        return []
    return bad


# --- consecutive-failure streak (attribution-ladder reminder) ---

def _streak_file(session_id):
    return os.path.join(_sessions_dir(), _safe_sid(session_id) + ".fails")


def load_fail_streak(session_id):
    if not session_id:
        return 0
    try:
        with open(_streak_file(session_id), encoding="utf-8") as fh:
            return max(0, int(fh.read().strip() or 0))
    except Exception:
        return 0


def save_fail_streak(session_id, n):
    if not session_id:
        return
    try:
        with open(_streak_file(session_id), "w", encoding="utf-8") as fh:
            fh.write(str(int(n)))
    except Exception:
        pass


def parse_ledger(path):
    """Return (open_items, has_any, paused) for a ledger file.

    A ledger line is a markdown checkbox: `- [ ] ...`, `- [x] ...`, `- [~] ...`
    (case-insensitive on x). `open_items` is the list of `- [ ]` line texts.
    `has_any` is True if the file has at least one checkbox line at all.
    `paused` is True if any line starts with `PAUSED` (case-insensitive) AND
    carries a reason (>=3 chars after the marker) — the user-facing switch to
    suspend enforcement mid-round for unrelated work. A bare `PAUSED` with no
    reason is ignored: pausing must be attributable, not a one-word escape
    hatch a model can reach for silently.
    """
    open_items = []
    has_any = False
    paused = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s.upper().startswith("PAUSED"):
                    reason = s[len("PAUSED"):].strip(" \t:：-–—")
                    if len(reason.strip()) >= 3:
                        paused = True
                    continue
                if len(s) < 4 or not s.startswith("- ["):
                    continue
                mark = s[3:4].lower()
                if s[2:5] == "[ ]":
                    has_any = True
                    open_items.append(s)
                elif mark in ("x", "~"):
                    has_any = True
    except FileNotFoundError:
        return [], False, False
    except Exception:
        # Unreadable ledger: treat as "no ledger" -> fail open.
        return [], False, False
    return open_items, has_any, paused
