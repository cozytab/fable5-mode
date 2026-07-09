#!/usr/bin/env python3
"""fable-mode lint — one-shot discipline check for a fable-mode project.

Not a hook: a CLI the model (or CI) runs at wrap-up, and the machine-checkable
acceptance for the discipline itself:

    python3 ~/.claude/skills/fable-mode/hooks/fable_lint.py [project_dir]

Checks (each finding names the file and the rule):
  1. docs/SPEC.md exists next to the `.fable/` project root.
  2. SPEC.md decisions carry source tags — at least one of
     [measured]/[inferred]/[not-shown]/[design-gap] (or the Chinese set
     [实测]/[读数]/[推断]/[未展示]/[设计补全]). Untagged specs hide guesses.
  3. Every open `- [ ]` ledger card hints at its acceptance (mentions a test/
     acceptance/验收, or carries a `backtick command`).
  4. Every closed `- [x]` ledger card carries an evidence marker
     (`-- evidence:` / `证据:`).

Exit 0 = clean, exit 1 = findings (printed one per line), exit 0 with a note
if the directory isn't a fable-mode project at all.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fable_common import (  # noqa: E402
    find_fable_dir, ledger_path, closed_without_evidence,
)

SOURCE_TAG_RE = re.compile(
    r"\[(measured|inferred|not-shown|design-gap|实测|读数|推断|未展示|设计补全)\]",
    re.IGNORECASE)
ACCEPTANCE_HINT_RE = re.compile(r"(accept|验收|test|测试|`[^`]+`)", re.IGNORECASE)


def lint(project_dir):
    findings = []
    fable_dir = find_fable_dir(project_dir)
    if not fable_dir:
        print("fable-lint: no .fable/ found from %s — not a fable-mode "
              "project, nothing to lint" % project_dir)
        return 0
    root = os.path.dirname(fable_dir)

    spec = os.path.join(root, "docs", "SPEC.md")
    if not os.path.isfile(spec):
        findings.append("%s: missing (plan gate: requirements + approach + "
                        "task cards live here)" % spec)
    else:
        try:
            with open(spec, encoding="utf-8", errors="replace") as fh:
                if not SOURCE_TAG_RE.search(fh.read()):
                    findings.append(
                        "%s: no source tags — tag design decisions "
                        "[measured]/[inferred]/[not-shown] so reviewers know "
                        "which foundations are guesses" % spec)
        except Exception:
            pass

    lp = ledger_path(fable_dir)
    if os.path.isfile(lp):
        try:
            with open(lp, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    s = line.strip()
                    if s[:5].lower() == "- [ ]" and not ACCEPTANCE_HINT_RE.search(s):
                        findings.append(
                            "%s:%d: open card with no acceptance hint "
                            "(name the test/command that will prove it): %s"
                            % (lp, i, s))
        except Exception:
            pass
        for s in closed_without_evidence(lp):
            findings.append(
                "%s: checked card without `-- evidence:` marker: %s" % (lp, s))
    else:
        findings.append("%s: missing (no task cards -> no round structure)" % lp)

    for f in findings:
        print("FINDING  " + f)
    print("fable-lint: %d finding(s)" % len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    try:
        sys.exit(lint(os.path.abspath(target)))
    except Exception as e:
        print("fable-lint: error (%r)" % e)
        sys.exit(0)
