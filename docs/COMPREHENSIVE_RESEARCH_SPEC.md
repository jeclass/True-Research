# Comprehensive research spec — deeper trees, verification waves, wave orchestration

Operator-approved 2026-06-11. Goal: make the engine do **8-hour+, above-and-
beyond research** that exceeds Gemini/Claude/ChatGPT deep research on **depth,
verification, and trust** (not raw speed — the cloud giants win on index
quality and minutes-long turnaround; we win on exhaustive, stress-tested,
private, cheap depth).

Build in the order below — each is independently shippable and validated by
the same `runs/certify.ps1` bar plus a dedicated deep-run. None is a rewrite;
all layer on the existing deterministic loop. Keep every change guarded so a
normal run is unchanged, the same discipline used for the lens/scraper/reranker.

---

## 0. Why this is possible here and not there

"Multi-hour" is a property of the deterministic driver loop, not a model. The
frontier services synthesize once and stop (minutes). Our loop can run
arbitrarily long against state on disk, resume across reboots, and spend $0 on
the volume work. The job of this spec is to make long runs buy *depth and
verification* rather than idle looping.

---

## 1. Stronger compose model (do first — cheapest 8→9 jump)

**Problem:** the synthesis-calibration ceiling is the local 9B doing the
one-shot compose. Certification's source_quality/factual ceiling on hard
questions traces to compose nuance, not faithfulness (which is structural).

**Change:** add a `compose` role (or `worker_compose`) routed independently of
the worker. Readers + query-gen stay local ($0); only the compose call — one
short, low-volume call per resolved question — routes to a stronger model
(Haiku first-party, or a 27B on a second GPU). This is a small, bounded cost
increase for a synthesis-quality jump.

**Acceptance:** gen-evbattery and sci-aspirin re-run; compose→Haiku lifts
mean_overall by ≥0.5 at ≤ +$0.30/question. Compare to the certified 7.2.

---

## 2. Deeper question trees (breadth)

**Today:** initializer seeds ~6 questions; evaluator opens gaps; workers
fragment. `max_cycles: 40`. Trees stay shallow because runs hit caps first.

**Change:**
- Richer initializer prompt: explicit multi-level decomposition (top facets →
  sub-facets), targeting 8–15 seed questions for a comprehensive run, each
  scoped to be a self-contained investigation.
- A `depth_budget` / `max_question_depth` knob so fragmentation can recurse
  (worker fragments a child into grandchildren when a sub-facet is itself
  broad). Guard against unbounded growth with a hard node cap logged to
  DECISIONS.
- A `comprehensive` config profile or flag that raises `max_cycles`,
  `max_wall_hours`, and the budget caps together (one switch for "go deep").

**Acceptance:** a comprehensive run produces a question tree ≥2 levels deep
with ≥20 resolved questions, REPORT.md covers every top facet, no unbounded
loop (node cap respected + logged).

---

## 3. Verification wave (the trust differentiator)

**This is what makes the engine exceed the frontier services.** They cite;
they do not adversarially verify. We can.

**Change:** a new session type `verifier` (Opus or strong cloud — judgment
work, §1) and a driver phase. After the breadth/depth phases resolve the tree,
for each load-bearing claim (high-confidence findings, or claims the
synthesizer would lead with):
- Spawn an independent `verifier` whose ONLY job is to REFUTE the claim: search
  for contradicting evidence, re-check the original numbers against the primary
  source, flag overreach or misread effect sizes.
- A claim that survives → marked `verified` (carries a verification note into
  synthesis). A claim that's refuted → re-opened as a question, or demoted to a
  flagged uncertainty in the report.
- New state: `finding.verification: {status: unverified|verified|refuted,
  note, verifier_run}`.

**Acceptance:** seed a deliberately wrong claim (e.g. a finding citing a
misread effect size); the verifier catches and refutes it; the report demotes
it rather than leading with it. On a real run, ≥80% of lead claims carry a
verification status and the report distinguishes verified from unverified.

---

## 4. Wave orchestration (enables 8-hour depth)

**Change:** the driver gains a phase machine over the existing loop — each wave
is just a different question-selection + session policy, not new cognition:

```
BREADTH   — map the space: resolve the seed tree, fragment freely
   ↓
DEPTH     — pick the highest-value findings; re-investigate each hard
            (more reads, primary-source insistence, cross-validation ≥2 indep)
   ↓
VERIFY    — §3 verification wave over lead claims
   ↓
SYNTHESIZE — final report, now annotating verified vs unverified
```

- Phase transitions are deterministic (driver-controlled), logged to PROGRESS.
- Resumable across phases (a wave boundary is a natural checkpoint) — an
  8-hour run survives a reboot mid-wave.
- Each phase has its own breaker budget so DEPTH can't starve VERIFY.

**Acceptance:** an 8-hour `comprehensive` run on one hard question completes all
four waves, the report shows verified lead claims + a depth far beyond the
certified single-pass run, total Opus spend stays bounded (per-cycle eval
local; Opus only at verify + final gate + synthesis), and a mid-run reboot
resumes into the correct wave.

---

## 5. Hardware note (conditional, operator-gated)

Items 1–4 are software on the current single 16GB card; an 8-hour run there is
serial-read-bound (~80–120 cycles). The **second GPU** turns serial reads into
4–8-way fan-out (readers + concurrent worker investigations) — the single
biggest scale unlock, and the thing that lets comprehensive mode actually
*surpass* the frontier services on coverage. Operator will source it if the
pipeline proves useful (it now has: certified 7.2, scientific 7.8). Pin
instances per card (`CUDA_VISIBLE_DEVICES`), don't split one model across both
(see operator's model research, `docs/LOCAL_SETUP_REPORT.md` addendum).

---

## Guardrails (unchanged contract)

Every wave honors the §3 invariants: amnesiac sessions, default-FAIL evaluator,
every-claim-traceable, breakers always armed, atomic writes, resumable. The
verification wave strengthens invariant 3 from "traceable" to "traceable AND
stress-tested." Nothing here weakens a guard.
