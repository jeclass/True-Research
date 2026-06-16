# Gate A/B — Opus 4.8 vs Qwen 3.7 Max on the terminal gate

**The one measurement left.** After the architect review (2026-06-16) the engine
is one efficient build (Groq volume + DeepSeek V4 Pro on init/verify/synth). The
*only* unresolved cell is the once-firing terminal gate — the ungrounded "is this
research conclusive, or should the run continue?" decision. `--cheap` puts Qwen
3.7 Max there (~$0.06, high abstention bias); `--accurate` puts Opus 4.8 there
(~$0.11, lowest measured hallucination). This experiment decides which is right.

If Qwen ties or beats Opus on the metric below, **Qwen wins outright** — ~2×
cheaper at the gate and no Anthropic dependency in the cheap tier, so the Opus
tier may not be needed at all. If Opus is materially safer, `--accurate`'s gate
earns its premium. Either way it's a number, not a prior.

## The metric

For each run we have a human **ground truth**:
- `fail` — the finished run still had a real gap; it *should have stayed open*.
- `pass` — the run was genuinely conclusive.

Then per gate model:

| metric | definition | why it matters |
|---|---|---|
| **false-conclusive** | P(gate PASSED \| ground_truth = `fail`) | **the fatal error** — rubber-stamping an unfinished run ends it with a flawed answer |
| false-open | P(gate FAILED \| ground_truth = `pass`) | abstention bias — the *cost* of safety (wasted cycles re-opening a done run) |

Lower **false-conclusive** is load-bearing; false-open is the price you pay for it.
Qwen's known high-abstention bias should show as low false-conclusive **and**
higher false-open — the question is whether the trade is worth 2× the gate cost.

## Why replay, not re-run

We do **not** run each question twice end-to-end. Two full runs diverge on search
paths, so the two gates would judge *different* findings — confounding the model
comparison with run-to-run noise. Instead we freeze **one** terminal state per
question and replay only the gate on it under each model. Same findings, same open
questions, same prompts; the gate model is the lone variable. The replay is
strictly read-only (it never writes a verdict or mutates questions), so both arms
can judge the same run without contaminating it.

## Run it

```powershell
# 1. Generate one terminal state per question (needs GROQ + DASHSCOPE + DEEPSEEK
#    keys + the LiteLLM proxy up). Use --cheap so states are cheap to produce;
#    the gate model doesn't matter here — we replace it in the replay.
foreach ($q in (python -c "import yaml,sys; [print(x['id']+'\t'+' '.join(x['question'].split())) for x in yaml.safe_load(open('experiments/gate_ab/questions.yaml'))['questions']]")) {
  $id, $text = $q -split "`t", 2
  python driver.py "$text" --cheap --profile general    # note the run-id it prints
}

# 2. Replay the A/B over the run-ids from step 1 (validate first with --dry-run):
python experiments/gate_ab/run_gate_ab.py replay --runs <id1> <id2> ... --dry-run
python experiments/gate_ab/run_gate_ab.py replay --runs <id1> <id2> ...

# 3. Open experiments/gate_ab/results.csv and fill `ground_truth` (fail|pass) for
#    each run — use questions.yaml's `should_stay_open_if` as the rubric.

# 4. Score:
python experiments/gate_ab/run_gate_ab.py score experiments/gate_ab/results.csv
```

`--dry-run` validates the whole path (resume each run, build the gate prompts,
resolve both gate models) **without any LLM spend or keys** — use it to confirm
wiring before spending.

## Files

- `questions.yaml` — the 10 hard questions + per-item `should_stay_open_if` rubric
  (the gap that makes a PASS a false-conclusive). Edit/extend freely.
- `run_gate_ab.py` — `replay` (read-only gate replay -> results.csv) and `score`
  (false-conclusive / false-open from filled-in ground truth).
- `results.csv` — produced by `replay`; you fill `ground_truth`; `score` reads it.
