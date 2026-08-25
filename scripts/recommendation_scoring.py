#!/usr/bin/env python3
"""
Sekeron Stage 4 - Deterministic Recommendation Scoring
=========================================================

Pure Python scoring and ranking. No LLM calls. No network access.

Scores each artist against a parsed hirer brief's capability requirements
using only demonstrated evidence from artist_intelligence.jsonl.

Key principles:
  - insufficient_evidence gets 0 points (unknown != incapable, NO penalty)
  - Operational constraints are attached verbatim but NEVER scored
  - Ties broken by artist_id alphabetically (deterministic)
  - All eligible artists included in the ranked list (no cut-off)

Imports capability vocabulary from capability_vocabulary.py to ensure
dimension keys stay in sync with artist_intelligence.jsonl.

SCORING FORMULA:
    For each capability_requirement:
        for each mapped_dimension:
            if artist has demonstrated status:
                points += confidence_weight[confidence] * importance_multiplier
            else:
                points += 0  (no penalty)

    confidence_weight = {high: 3, medium: 2, low: 1, insufficient: 0}
    importance_multiplier = {must_have: 1.0, nice_to_have: 0.5}
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_vocabulary import (
    CAPABILITY_KEYS_BY_CATEGORY,
    OPERATIONAL_CATEGORIES,
)


# --------------------------------------------------------------------------
# Scoring constants — documented here, used nowhere else.
# --------------------------------------------------------------------------

CONFIDENCE_WEIGHT = {
    "high": 3,
    "medium": 2,
    "low": 1,
    "insufficient": 0,
}

IMPORTANCE_MULTIPLIER = {
    "must_have": 1.0,
    "nice_to_have": 0.5,
}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def score_artist(parsed_brief, artist_record):
    """Score a single artist against a parsed hirer brief.

    Returns dict with total_score and per-dimension breakdown,
    or None if the artist's category does not match the brief.

    Only capability_requirements affect the score.
    Operational constraints are NEVER scored.
    """
    if artist_record["category"] != parsed_brief["artist_category"]:
        return None  # wrong category, not eligible

    # Build lookup: capability_key → capability dict from intelligence
    caps_by_key = {}
    for cap in artist_record.get("demonstrated_capabilities", []):
        caps_by_key[cap["capability"]] = cap

    breakdown = {}
    total_score = 0.0

    for req in parsed_brief.get("capability_requirements", []):
        importance = req.get("importance", "must_have")
        multiplier = IMPORTANCE_MULTIPLIER.get(importance, 1.0)

        for dim in req.get("mapped_dimensions", []):
            cap = caps_by_key.get(dim)

            if cap and cap.get("status") == "demonstrated":
                conf = cap.get("confidence", "insufficient")
                weight = CONFIDENCE_WEIGHT.get(conf, 0)
                points = weight * multiplier
            else:
                # insufficient_evidence, conflicting_evidence, or not found
                # → 0 points. NEVER negative. Unknown != incapable.
                points = 0.0

            breakdown[dim] = {
                "status": cap["status"] if cap else "not_found",
                "confidence": (
                    cap.get("confidence", "insufficient") if cap
                    else "insufficient"
                ),
                "importance": importance,
                "points": points,
            }
            total_score += points

    return {
        "total_score": total_score,
        "score_breakdown": breakdown,
    }


def build_constraint_notes(parsed_brief, artist_record):
    """Build human-readable notes about operational constraints.

    These are for manual review by the Sekeron team — they are NEVER
    used in scoring. Constraints like budget, date availability, and
    location require verification with the artist and cannot be
    algorithmically resolved.
    """
    notes = []
    for op in parsed_brief.get("operational_constraints", []):
        limit_str = " [HARD LIMIT]" if op.get("hard_limit") else ""
        notes.append(
            f"{op['category']}: {op['detail']}{limit_str} — verify with artist"
        )
    return notes


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def rank_artists(parsed_brief, all_artist_records):
    """Score and rank all eligible artists for a parsed hirer brief.

    Returns list of ranked artist dicts, sorted by total_score descending,
    with ties broken by artist_id alphabetically (deterministic).

    All eligible artists are included — no cut-off threshold.
    """
    scored = []
    for artist in all_artist_records:
        result = score_artist(parsed_brief, artist)
        if result is None:
            continue  # wrong category, skip

        constraint_notes = build_constraint_notes(parsed_brief, artist)

        scored.append({
            "artist_id": artist["artist_id"],
            "display_name": artist.get("display_name", artist["artist_id"]),
            "total_score": result["total_score"],
            "score_breakdown": result["score_breakdown"],
            "operational_constraint_notes": constraint_notes,
        })

    # Sort: highest score first, then artist_id alphabetically for ties
    scored.sort(key=lambda x: (-x["total_score"], x["artist_id"]))

    # Assign explicit rank numbers
    for i, entry in enumerate(scored, start=1):
        entry["rank"] = i

    return scored
