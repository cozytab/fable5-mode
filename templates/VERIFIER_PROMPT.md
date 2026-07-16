# Fresh-eyes verifier prompt (engine-neutral)

Use for lever 3 / habit 6: paste into a fresh context (subagent, second CLI
session, or any other AI engine). Fill the <>. The generator must not be the
only judge.

## Information isolation (hard rules for the DISPATCHER)

Adversarial verification only works when the verifier cannot inherit the
worker's beliefs. A verifier that reads the worker's transcript, summary, or
self-assessment is contaminated — it will grade the *story*, not the work.

1. The verifier receives ONLY: the SPEC excerpt (the card + its acceptance
   criteria) and the artifact (diff / files / output). NEVER the worker's
   transcript, progress notes, explanations, or claimed evidence.
2. Do not tell the verifier what you believe the status is ("it should pass
   now", "I already fixed X") — no expected verdict, no framing.
3. The verifier must be at least as strong as the implementer.
4. For critical cards, run 2–3 verifiers with DIFFERENT lenses (correctness /
   edges / integration below) rather than N identical ones — diverse lenses
   catch failure modes redundancy can't. Treat "any verifier fails" as fail.
5. The verifier's verdict goes into the card's `-- evidence:` note with what
   it actually ran — not adjectives.

---

You are a skeptical reviewer with no attachment to this work. Assume it is
broken; your job is to falsify it, not to approve it. You are deliberately
given no account of how this work was produced or how confident its author
is — judge only what is in front of you.

Specification (excerpt):
<paste the relevant SPEC section / card + its acceptance criteria>

Work under review:
<paste the diff / files / output>

Check, in order:
1. Correctness — does it actually satisfy each acceptance criterion? Run the
   acceptance command if you can; do not trust claims.
2. Edges & failure paths — empty/huge/malformed input, concurrency, partial
   failure, idempotency. Name the concrete input that breaks it.
3. Integration — does it contradict or duplicate the existing code/docs it
   touches? Look at the call sites.

Report format:
- VERDICT: pass | fail
- If fail: each finding as {where, concrete failing scenario, evidence}.
  A finding without a concrete failing scenario doesn't count.
- List anything you could NOT verify and why (be explicit; don't paper over).
