🎨 Design Reference

# Sekeron Stage 3 — Schemas & Formulas

---

## 1. Capability Dimensions
Category-specific, fixed vocabulary — imported from `capability_vocabulary.py`, never redefined elsewhere.

| Category | Dimensions |
|---|---|
| Photographer (7) | `subject_domain`, `composition_technique`, `lighting_treatment`, `color_tone_treatment`, `environment_context`, `technical_control_indicators`, `shooting_context_style` |
| Musician (6) | `vocal_or_instrumental_role`, `genre_style_signal`, `performance_format`, `live_vs_studio_context`, `instrumental_technical_signals`, `audio_arrangement_characteristics` |
| Video editor (7) | `pacing_rhythm`, `shot_composition_and_framing`, `visual_sequencing_signals`, `color_treatment`, `content_format_context`, `motion_graphics_or_overlay_evidence`, `audio_dialogue_handling`* |

*`audio_dialogue_handling` currently has zero evidence for all 5 editors — see TASKS.md.

## 2. Confidence Levels

| Level | Meaning |
|---|---|
| `insufficient` | 0 independent evidence items — forced, not a judgment call |
| `low` | 1 item, or all contributing items flagged/cross-artist |
| `medium` | 1 clean item, ceiling |
| `high` | 2+ clean items, ceiling |

## 3. `artist_intelligence.jsonl` Record Shape
One line per artist, 15 total.

| Field | Notes |
|---|---|
| `artist_id`, `folder_name`, `display_name`, `category` | Identity |
| `data_quality_observations` | Code-assembled from upstream anomaly flags |
| `profile_claims` | Verbatim segments, never model-authored |
| `demonstrated_capabilities[]` | `capability`, `status`, `confidence`, `profile_conflict`, `observation`, `evidence_references[]`, `supporting_evidence_strength`, `unknowns_limitations` |
| `conflicts[]` | `profile_claim_id`, `capability_dimension`, `resolution: "unresolved_both_retained"` |
| `context_selection_summary` | What was shown to the model vs. omitted, and why |
| `generation_metadata` | `model`, `status`, `error` |

## 4. Scoring Formula

```
confidence_weight = { high: 3, medium: 2, low: 1, insufficient: 0 }
importance_multiplier = { must_have: 1.0, nice_to_have: 0.5 }

requirement_contribution = mean(confidence_weight per mapped_dimension) × importance_multiplier
total_score = Σ requirement_contribution
```

| Rule | Why |
|---|---|
| Averaged, not summed, across dimensions | A requirement mapped to 3 dimensions can't be worth 3x one mapped to 1 |
| Tiebreak: `(-total_score, artist_id)` | Deterministic, alphabetical on exact ties |
| Operational constraints never scored | Surfaced separately, zero weight in the formula |

## 5. Context-Efficiency Budgets

| Parameter | Value |
|---|---|
| `IMAGE_CONTEXT_BUDGET_PER_ARTIST` | 20 |
| Perceptual dedup | 8×8 average hash, Hamming distance threshold 5 |
| Coverage guarantee | ≥1 item per unique source file before filling remaining budget |
| `AUDIO_CONTEXT_SECONDS_BUDGET_PER_ARTIST` | 480.0 |
