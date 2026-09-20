🔧 Pipeline Architecture

# Sekeron Stage 3 — Artist Intelligence & Recommendation

This document describes the actual data pipeline, script responsibilities, and data flow. No frontend, no deployment layer — this is a local, script-driven pipeline, not a web app.

---

## 1. Technology Stack
Technologies used and their purpose.

| Layer | Technology | Purpose |
|---|---|---|
| Language | Python 3 | Entire pipeline |
| Media inspection | ffmpeg / ffprobe | Video/audio duration, codec, scene-change detection, frame/audio extraction |
| Image processing | Pillow | Dimension/format inspection, corrupt-image detection, perceptual hashing |
| Document parsing | python-docx | Profile document text extraction |
| LLM | Gemini 3.6 Flash (raw `requests`) | Multimodal capability assessment, hirer-brief interpretation |
| Testing | pytest | 12 regression tests |
| Version control | Git + GitHub | `github.com/Aldrinsui/sekeron` |

## 2. Pipeline Stages & Data Flow

```
Data set/ (read-only, never modified)
   │
   ├─► inspect_dataset.py ─────────────► dataset_manifest.json
   ├─► select_evidence.py ─────────────► evidence_manifest.json + evidence_assets/
   ├─► select_editor_audio_addendum.py ─► audio evidence for video-editor clips
   │      (not currently committed — see TASKS.md)
   ├─► extract_profiles.py ────────────► artist_profiles.json
   │
   ├─► generate_artist_intelligence.py ─► artist_intelligence.jsonl
   │      (calls Gemini per artist; imports capability_vocabulary.py)
   │
   ├─► parse_hirer_brief.py ───────────► parsed requirements
   │      (calls Gemini per brief; embedded into recommendations.json)
   │
   ├─► generate_recommendations.py ────► recommendations.json
   │      (uses recommendation_scoring.py — deterministic, no LLM call)
   │
   └─► update_recommendation.py ───────► updated_recommendation.json
          (re-parses follow-up text, re-scores via recommendation_scoring.py)
```

## 3. Module Responsibilities

| Module | Responsibility |
|---|---|
| `capability_vocabulary.py` | Single source of truth: capability dimensions per category, status/confidence enums. Every other script imports from here. |
| `recommendation_scoring.py` | The only place scoring math lives. Category hard-filter, confidence-ceiling enforcement, tiebreak logic. |
| `generate_artist_intelligence.py` | Orchestrates evidence selection, prompt construction, Gemini call, validation, clamping. |
| `demo.py` | Read-only presentation layer over the 3 committed `generated/*.json` files. No dataset or API access needed to run it. |

## 4. Determinism Boundary
| Layer | Deterministic? |
|---|---|
| Scoring arithmetic | ✅ Yes — pure function of parsed brief + artist data |
| Confidence-ceiling clamping | ✅ Yes — code-enforced, overrides model self-report |
| Evidence-ID resolution | ✅ Yes — unresolvable citations stripped automatically |
| Artist-intelligence generation | ❌ No — live Gemini call, not guaranteed byte-identical across runs |
| Hirer-brief parsing | ❌ No — same reason |
