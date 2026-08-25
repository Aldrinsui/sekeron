# Sekeron Stage 3 — Artist Intelligence & Recommendation

## Overview

This implementation builds an evidence-led pipeline for incomplete hirer briefs and 15 artist profiles across musicians, photographers and video editors.

The pipeline has two stages:

1. **Artist intelligence** — profile claims and selected portfolio evidence are converted into category-specific capability records with evidence references, confidence and unknowns.
2. **Recommendation** — hirer briefs are parsed into structured capability requirements and operational constraints, then matching artists are ranked using deterministic scoring.

A supplied follow-up brief is parsed separately and the ranking is recomputed from the updated requirements.

## Setup

Python 3.14 was used during development.

Install dependencies:

    python3 -m pip install -r requirements.txt

Generate recommendations:

    python3 scripts/generate_recommendations.py --briefs-dir briefs --intelligence generated/artist_intelligence.jsonl --profiles generated/artist_profiles.json --output-dir generated

Process the supplied follow-up:

    python3 scripts/update_recommendation.py --original generated/recommendations.json --update-brief briefs/01_cafe_music_update.txt --hirer-id H081 --intelligence generated/artist_intelligence.jsonl --output-dir generated

Run tests:

    python3 -m pytest tests/test_recommendation.py -v

## Approach

Artist intelligence uses category-specific capability dimensions rather than treating all creative work identically. Media is selected through the evidence-selection stage rather than blindly processing every frame or second.

Capability records distinguish demonstrated evidence from insufficient evidence and record confidence. Evidence references identify supplied source material. Unsupported profile claims are not treated as demonstrated capability.

Gemini is used for structured interpretation of sparse hirer language. Ranking is deterministic Python.

Confidence weights: high=3, medium=2, low=1, insufficient=0.

Importance weights: must-have=1.0, nice-to-have=0.5.

Insufficient evidence receives zero points and no negative penalty.

Operational constraints such as budget, date and equipment are preserved for human verification and never affect the capability score.

Artists are sorted by score descending, with artist_id as the deterministic tie-breaker. The generated output contains the top two artists per brief, reasons, trade-offs, assumptions, uncertainty and up to two refinement questions with expected impact.

The follow-up recommendation is freshly recomputed from the updated requirements. A ranking change is not forced when deterministic scoring produces the same ordering.

## Evaluation

The test suite contains nine tests covering validation, confidence weighting, importance weighting, insufficient evidence, deterministic tie-breaking, exclusion of operational constraints, follow-up requirement replacement, end-to-end generation/update behaviour and contextual recommendation fields.

Final local result: 9 passed.

The generated initial recommendations contain two artists for each of H081, H082, H083 and H117. The follow-up output contains two artists for H081.

## Limitations

Availability, budget acceptance, equipment compatibility and similar operational facts cannot be verified from portfolio evidence and remain human verification tasks.

The supplied dataset contains incomplete evidence, so some rankings can remain flat. Missing evidence is reported as uncertainty rather than treated as incapability.

The implementation deliberately stays within the assessment scope: no frontend, scraping, model training, deployment or production integration.
