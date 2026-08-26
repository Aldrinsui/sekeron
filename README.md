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

```bash
python3 -m pip install -r requirements.txt
```

### Generate artist intelligence

Set the Gemini API key in the environment before running the intelligence stage:

```bash
export GEMINI_API_KEY="<YOUR_GEMINI_API_KEY>"
```

Generate the evidence-backed artist intelligence:

```bash
python3 scripts/generate_artist_intelligence.py \
  --dataset-root "<DATASET_ROOT>" \
  --dataset-manifest generated/dataset_manifest.json \
  --evidence-manifest generated/evidence_manifest.json \
  --profiles generated/artist_profiles.json \
  --output-dir generated
```

The final assessment run used Gemini 3.6 Flash. The generated intelligence records store model metadata and whether generation succeeded.

### Generate recommendations

```bash
python3 scripts/generate_recommendations.py \
  --briefs-dir briefs \
  --intelligence generated/artist_intelligence.jsonl \
  --profiles generated/artist_profiles.json \
  --output-dir generated
```

### Process the supplied follow-up

```bash
python3 scripts/update_recommendation.py \
  --original generated/recommendations.json \
  --update-brief briefs/01_cafe_music_update.txt \
  --hirer-id H081 \
  --intelligence generated/artist_intelligence.jsonl \
  --output-dir generated
```

### Run tests

```bash
python3 -m pytest tests/test_recommendation.py -v
```

## Approach

Artist intelligence uses category-specific capability dimensions rather than treating all creative work identically. Media is selected through the evidence-selection stage rather than blindly processing every frame or second.

For video, the evidence-selection stage uses temporal anchor frames and, for sufficiently long video-editor clips, scene-change candidate frames. For musicians, full audio tracks are extracted from short video clips where appropriate. Near-duplicate evidence is omitted for context efficiency.

Capability records distinguish demonstrated evidence from insufficient evidence and record confidence. Evidence references identify supplied source material. Profile claims are stored separately and are not treated as demonstrated capability unless the supplied evidence supports them.

The intelligence stage also allows a small number of additional observed capabilities when they are directly observable in supplied evidence and are not adequately represented by the standard category dimensions. These are supplementary observations and do not replace the standard checklist dimensions.

Gemini 3.6 Flash is used for structured multimodal artist assessment and sparse hirer-brief interpretation. Deterministic Python handles validation, scoring and ranking.

Confidence weights:

- high = 3
- medium = 2
- low = 1
- insufficient = 0

Importance weights:

- must-have = 1.0
- nice-to-have = 0.5

Insufficient evidence receives zero points and no negative penalty. Unknown does not mean incapable.

Operational constraints such as budget, date and equipment are preserved for human verification and never affect the capability score.

Artists are sorted by score descending, with `artist_id` as the deterministic tie-breaker. The generated output contains the top two artists per brief, reasons, trade-offs, assumptions, uncertainty and up to two refinement questions with expected impact.

The follow-up recommendation is freshly recomputed from the updated requirements. A ranking change is not forced when deterministic scoring produces the same ordering. The update output separately records score changes and score-gap changes so that an unchanged ordinal ranking is not incorrectly described as unchanged scoring.

## Evaluation

The test suite contains nine tests covering validation, confidence weighting, importance weighting, insufficient evidence, deterministic tie-breaking, exclusion of operational constraints, follow-up requirement replacement, end-to-end generation/update behaviour and contextual recommendation fields.

Final local result:

```text
9 passed
```

The generated initial recommendations contain two artists for each of H081, H082, H083 and H117. The follow-up output contains two artists for H081.

The final artist-intelligence validation covered all 15 artists, verified that every demonstrated capability had evidence, and reported no generation failures in the final combined output.

### Time spent

Approximately **[ENTER YOUR ACTUAL TIME]** hours of focused implementation and verification time were spent on the assessment, within the six-hour timebox.

## Limitations

Availability, budget acceptance, equipment compatibility and similar operational facts cannot be verified from portfolio evidence and remain human verification tasks.

The supplied dataset contains incomplete or anomalous evidence, so some capabilities remain insufficiently supported and some rankings can remain close. Missing or weak evidence is reported as uncertainty rather than treated as incapability.

Model-generated observations remain subject to the quality of the supplied media. The pipeline therefore applies deterministic evidence validation and confidence ceilings rather than accepting model confidence without constraint.

The implementation deliberately stays within the assessment scope: no frontend, scraping, model training, deployment or production integration.
