✅ Project Tasks

# Sekeron Stage 3 — Task Breakdown & Progress

| Total Tasks | Completed | In Progress | Not Started |
|---|---|---|---|
| 22 | 18 (82%) | 1 | 3 |

---

## Phase 1: Data Pipeline — Dataset Inspection & Evidence Selection
Read-only inspection, evidence extraction, budgeting. All under `scripts/`.

| # | Task | Priority | Status | Completed |
|---|---|---|---|---|
| 1.1 | Dataset inspection script | High | ✅ Completed | Aug 25 |
| 1.2 | Evidence selection + budgeting/dedup | High | ✅ Completed | Aug 25 |
| 1.3 | Editor audio addendum script | Medium | ⬜ Not Started | — |

## Phase 2: Artist Intelligence
Evidence-backed capability generation via Gemini, category-specific dimensions.

| # | Task | Priority | Status | Completed |
|---|---|---|---|---|
| 2.1 | Profile text extraction | High | ✅ Completed | Aug 25 |
| 2.2 | Capability vocabulary (single source of truth) | High | ✅ Completed | Aug 25 |
| 2.3 | Artist intelligence generator | High | ✅ Completed | Aug 25 |
| 2.4 | Fix: `capability_vocabulary` import drift bug | High | ✅ Completed | Aug 30 |
| 2.5 | Fix: `profile_conflict` overwriting evidence status | High | ✅ Completed | Aug 30 |

## Phase 3: Recommendation Engine
Hirer-intent parsing, deterministic scoring, follow-up re-ranking.

| # | Task | Priority | Status | Completed |
|---|---|---|---|---|
| 3.1 | Hirer brief parser | High | ✅ Completed | Aug 26 |
| 3.2 | Deterministic scoring engine | High | ✅ Completed | Aug 26 |
| 3.3 | Follow-up re-ranking logic | High | ✅ Completed | Aug 27 |
| 3.4 | Fix: multi-dimension scoring double-count | High | ✅ Completed | Aug 30 |
| 3.5 | Add explicit `requirement_diff` (replace, not implicit) | Medium | ⬜ Not Started | — |
| 3.6 | Add `contradictions`/`unknowns` fields to brief schema | Medium | ⬜ Not Started | — |

## Phase 4: Documentation & Reproducibility

| # | Task | Priority | Status | Completed |
|---|---|---|---|---|
| 4.1 | README, decision_note, AI_USAGE (initial) | High | ✅ Completed | Aug 27 |
| 4.2 | `demo.py` helper | Medium | ✅ Completed | Aug 30 |
| 4.3 | Fix: README missing 3 of 6 pipeline steps | High | ✅ Completed | Sep 18 |
| 4.4 | Fix: `demo.py` crash on fresh clone | High | ✅ Completed | Sep 19 |
| 4.5 | Fix: `AI_USAGE.md` VO5 overclaim | High | ✅ Completed | Sep 19 |

## Phase 5: VO5 Investigation
`in_progress` — all 7 capability dimensions return `insufficient_evidence`, model self-reports "evidence failed to load."

| # | Task | Priority | Status |
|---|---|---|---|
| 5.1 | Verify local payload integrity (files, sizes, mime types) | High | ✅ Completed |
| 5.2 | Bisect payload via direct API test (`bisect_vo5.py`) | High | ✅ Completed — model confirmed all 20 images individually readable |
| 5.3 | Resolve root cause / regenerate a working VO5 record | High | 🔄 In Progress |

---

## Notes
- Every "Fix" row above has a corresponding regression test in `tests/test_recommendation.py`.
- Dates confirmed against actual `git log`, not estimated.
- See `MEMORY.md` for the full narrative context behind Phase 5.
