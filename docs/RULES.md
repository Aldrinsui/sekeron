📋 Development Rules

# Sekeron Stage 3 — Project Guidelines for AI & Human Collaboration

This document defines the development rules, coding standards, and hard constraints for the Sekeron Stage 3 pipeline. These rules ensure every output stays auditable, reproducible, and defensible under live questioning. Both AI assistants and human contributors must follow these guidelines.

---

## 1. General Principles
These rules apply to the entire project.

- ✅ Follow the project documentation (PRD, ARCHITECTURE, DESIGN) before making changes.
- ✅ Keep every generated claim traceable to a real evidence ID that resolves.
- ✅ Prioritize auditability over impressiveness — a claim that can't be checked is worse than no claim.
- ✅ Make small, focused changes with a regression test, instead of large risky edits.
- ✅ Do not touch the original dataset. Ever. Read-only, no exceptions.
- ✅ Verify by re-cloning and re-running — never trust a commit message or "I fixed it" without checking.
- ❌ Do not let a profile claim overwrite an evidence-derived status.
- ❌ Do not manually edit any file under `generated/`. Fix the script, regenerate.

## 2. Scoring & Confidence Standards
Rules specific to the deterministic scoring layer.

| Rule | Requirement |
|---|---|
| Status values | `demonstrated` / `insufficient_evidence` only — no third state |
| Profile conflicts | Separate `profile_conflict: bool` flag, never overwrites status |
| Confidence ceiling | 0 items → `insufficient` (forced) · 1 item → `medium` max · 2+ items → `high` max · all-flagged-only → `low` max |
| Multi-dimension requirements | Averaged across mapped dimensions, never summed |
| Missing evidence | Scores exactly 0, never negative. Unknown ≠ incapable. |
| Operational constraints | Never enter scoring (budget, location, date, turnaround, guest count, equipment, usage rights) |
| Category | Hard filter — never cross-category recommendations |

## 3. Technology & Processing Standards
Rules related to the tech stack and coding style.

| Layer | Standard |
|---|---|
| Language | Python 3, stdlib-first, minimal dependencies |
| Media processing | ffmpeg/ffprobe (video/audio), Pillow (images, perceptual hashing) |
| LLM | Gemini 3.6 Flash via raw `requests` — no SDK, full wire-format visibility |
| Testing | pytest, regression test added for every bug found |
| Dependencies | Pinned exact versions in `requirements.txt` |
| API keys | `GEMINI_API_KEY` from environment only — never hardcoded, printed, or logged |

## 4. Project Structure
- ✅ One script per pipeline stage, each independently runnable with `--output-dir`.
- ✅ Shared constants (capability dimensions, status/confidence enums) live in `capability_vocabulary.py` only — never redefined locally.
- ✅ Scoring logic lives in `recommendation_scoring.py` only — one formula, one place.
- ❌ Do not create a new script without updating `ARCHITECTURE.md`'s data-flow diagram.
- ❌ Do not commit anything under `generated/` except the 3 explicitly required final outputs.
