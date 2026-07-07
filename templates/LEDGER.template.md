# Ledger — <round name>

State machine: `- [ ]` open (blocks turn-end) · `- [x]` done AND verified ·
`- [~] ... -- deferred: reason` consciously out of this round.

Only mark `- [x]` after the acceptance command actually ran — cite evidence:

- [ ] 1. <card> — acceptance: `<command>`
- [ ] 2. <card> — acceptance: `<command>`
- [x] 0. (example) scaffold — verified: `pytest -q` -> 12 passed
- [~] 9. (example) dark mode -- deferred: not this round
