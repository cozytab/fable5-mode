# Ledger — <round name>

State machine: `- [ ]` open (blocks turn-end) · `- [x]` done AND verified ·
`- [~] ... -- deferred: reason` consciously out of this round.
A line `PAUSED: reason` anywhere suspends enforcement (for user-steered work
unrelated to this round) — the reason is required (bare `PAUSED` is ignored),
the model ceiling stays active; remove the line to resume. Evidence notes on
`- [x]` must be concrete (`evidence: ok` counts as missing).

Only mark `- [x]` after the acceptance command actually ran — the Close Guard
blocks turn-end for any `- [x]` without an evidence note (`-- evidence:` /
`verified:` / `证据:`):

Cite the acceptance `command` inside the evidence note — the Close Guard
corroborates cited commands against `.fable/evidence.jsonl` (machine-written
by the Evidence Logger): a citation that never ran, or never exited 0, blocks
the stop. Optional: a `REPLAY: on` line re-runs cited acceptances before the
round may end ('passed once' is not 'still passes').

- [ ] 1. <card> — acceptance: `<command>`
- [ ] 2. <card> — acceptance: `<command>`
- [x] 0. (example) scaffold -- evidence: `pytest -q` -> 12 passed
- [~] 9. (example) dark mode -- deferred: not this round
