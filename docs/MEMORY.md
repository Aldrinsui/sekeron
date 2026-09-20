🧠 Project Memory

# Sekeron Stage 3 — Context, Progress & Important Notes

This document keeps track of the current state of the project and important things to remember. It helps maintain continuity across sessions or new contributors (human or AI).

| Last Updated | Current Phase | Progress |
|---|---|---|
| Sep 19, 2026 | Phase 5 — VO5 Investigation | 18/22 (82%) |

---

## 🎯 Current Status
- ✅ Full pipeline (6 stages) implemented, 12/12 tests passing
- ✅ Two real bugs found via self-audit, fixed, regression-tested (capability_vocabulary import drift, scoring double-count)
- ✅ Three documentation/reproducibility issues found and fixed: `demo.py` crash, incomplete README, `AI_USAGE.md` overclaim
- 🔄 VO5 (video editor) still returns 0/7 demonstrated capabilities — root cause narrowed but not resolved
- ⬜ Follow-up logic (`update_recommendation.py`) works for the submitted case but isn't a real diff mechanism — known, disclosed limitation

## ✅ Completed Tasks

| # | Task | Completed |
|---|---|---|
| 1.1 | Dataset inspection script | Aug 25 |
| 1.2 | Evidence selection + budgeting | Aug 25 |
| 2.1–2.3 | Profile extraction, vocabulary, intelligence generator | Aug 25 |
| 3.1–3.3 | Brief parser, scoring engine, follow-up logic | Aug 26–27 |
| 2.4 / 3.4 | Fixed import-drift and scoring double-count bugs | Aug 30 |
| 4.2 | `demo.py` helper added | Aug 30 |
| 4.3 | README pipeline gaps fixed | Sep 18 |
| 4.4 / 4.5 | `demo.py` crash + `AI_USAGE.md` honesty fixes | Sep 19 |

## 🔄 In Progress

| # | Task | Notes |
|---|---|---|
| 5.3 | VO5 root-cause resolution | See full investigation trail below |

## ⬜ Not Started
- Explicit `requirement_diff` for follow-up updates (added/removed/modified, not implicit re-parse)
- `contradictions` / `unknowns` fields in hirer-brief parser schema
- `select_editor_audio_addendum.py` — never committed; all 5 video editors have zero `audio_dialogue_handling` evidence as a result

---

## 🔍 VO5 Investigation — full trail
Read this before repeating any diagnostic step.

1. **Symptom:** all 7 capability dimensions return `insufficient_evidence`, citing a model-generated "evidence failed to load" message, in ~2 of every 3 real generation attempts.
2. **Ruled out:** corrupted/malformed local files — verified all 20 selected evidence files exist, valid JPEGs, correct sizes (5K–512K), correct `image/jpeg` mime type, ~2.5MB total payload.
3. **Confirmed two distinct failure modes, not one:**
   - Clean HTTP 200 + valid JSON, but model self-reports inability to read the media (most common).
   - Genuine HTTP 503 from Gemini's servers (correctly handled by retry logic → honest `generation_failed`, not faked success).
4. **Cross-model comparison attempted, inconclusive:** `gemini-2.5-flash` returned HTTP 404 — not available to this API key/project, not a real negative data point.
5. **Bisection test (`bisect_vo5.py`) — key result:** asked the model directly, outside the full assessment prompt, which images it could read. **All 20 confirmed readable, zero unreadable.** This rules out the images as the cause entirely.
6. **Current leading hypothesis:** the full capability-assessment prompt (8 rules + 7 dimension write-ups + strict `responseSchema` + 20 images together) is too heavy for reliable completion — a prompt-load problem, not a data problem.
7. **Not yet tried:** reducing `IMAGE_CONTEXT_BUDGET_PER_ARTIST` for a single isolated test run.

## ⚠️ Don't repeat these mistakes
- Don't trust "I fixed it" without re-cloning and checking — this has produced false positives multiple times in this project's history.
- Don't present `demo.py`'s output as proof of correctness on its own — it's a display layer; always trace back to the real generator and data.
- Don't invent tooling that wasn't actually used if asked what's in the stack (no PySpark, no vector DB, no SDK — raw REST only).
