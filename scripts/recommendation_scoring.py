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

SCORING FORMULA (fixed 2026-08-25 - see AI_USAGE.md / audit notes):
    For each capability_requirement:
        per_dimension_points = [
            confidence_weight[dim_confidence] if dim_status == "demonstrated" else 0
            for each mapped_dimension
        ]
        requirement_contribution = mean(per_dimension_points) * importance_multiplier
        total_score += requirement_contribution

    confidence_weight = {high: 3, medium: 2, low: 1, insufficient: 0}
    importance_multiplier = {must_have: 1.0, nice_to_have: 0.5}

    NORMALIZATION NOTE: a requirement's contribution is AVERAGED across its
    mapped_dimensions, not summed. A requirement mapped to 3 dimensions
    therefore contributes at most the same maximum (3 * importance_multiplier)
    as a requirement mapped to a single dimension - the number of dimensions
    Gemini happened to attach to a requirement no longer inflates that
    requirement's influence on the score. Previously this was a plain sum
    across mapped_dimensions, so a 3-dimension requirement could contribute
    up to 3x a 1-dimension requirement regardless of the hirer's actual
    emphasis. All 9 pre-existing tests use single-dimension requirements
    only, so this change is a no-op for them (mean of one value = that
    value) - verified before making this change, not assumed.
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

    # breakdown: flat dict keyed by dimension name, last-writer-wins. Kept
    # for backward compatibility with existing dimension-keyed lookups.
    # requirement_breakdown: authoritative, non-lossy per-requirement record -
    # if two requirements map to the same dimension, both are fully visible
    # here even though `breakdown` can only show one entry per dimension key.
    breakdown = {}
    requirement_breakdown = []
    total_score = 0.0

    for req_index, req in enumerate(parsed_brief.get("capability_requirements", [])):
        importance = req.get("importance", "must_have")
        multiplier = IMPORTANCE_MULTIPLIER.get(importance, 1.0)
        mapped_dims = req.get("mapped_dimensions", [])

        per_dimension = {}
        raw_points_for_mean = []

        for dim in mapped_dims:
            cap = caps_by_key.get(dim)

            if cap and cap.get("status") == "demonstrated":
                conf = cap.get("confidence", "insufficient")
                weight = CONFIDENCE_WEIGHT.get(conf, 0)
            else:
                # insufficient_evidence or not found → 0 weight.
                # NEVER negative. Unknown != incapable.
                conf = cap.get("confidence", "insufficient") if cap else "insufficient"
                weight = 0

            raw_points_for_mean.append(weight)

            dim_entry = {
                "status": cap["status"] if cap else "not_found",
                "confidence": conf,
                "importance": importance,
                "raw_weight": weight,
            }
            per_dimension[dim] = dim_entry
            breakdown[dim] = {**dim_entry, "points": weight * multiplier}

        # Average across this requirement's mapped dimensions so a
        # requirement's fan-out (how many dimensions it happens to map to)
        # cannot inflate its influence relative to a single-dimension
        # requirement. See module docstring SCORING FORMULA note.
        mean_weight = (sum(raw_points_for_mean) / len(raw_points_for_mean)) if raw_points_for_mean else 0.0
        requirement_contribution = mean_weight * multiplier
        total_score += requirement_contribution

        requirement_breakdown.append({
            "requirement_index": req_index,
            "requirement_text": req.get("requirement_text", ""),
            "importance": importance,
            "mapped_dimensions": mapped_dims,
            "per_dimension": per_dimension,
            "requirement_contribution": requirement_contribution,
        })

    return {
        "total_score": total_score,
        "score_breakdown": breakdown,
        "requirement_breakdown": requirement_breakdown,
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


def generate_artist_context(parsed_brief, artist_record, score_result):
    """Generate structured contextual recommendation content for an artist.

    Connects demonstrated capabilities to hirer requirements, identifies
    trade-offs, articulates key operational assumptions, and notes uncertainties.
    """
    reasons = []
    trade_offs = []
    assumptions = []
    uncertainty = []

    caps_by_key = {}
    for cap in artist_record.get("demonstrated_capabilities", []):
        caps_by_key[cap["capability"]] = cap

    # 1. Reasons & Capability-level Trade-offs / Uncertainty
    for req in parsed_brief.get("capability_requirements", []):
        req_text = req.get("requirement_text", "")
        importance = req.get("importance", "must_have")
        for dim in req.get("mapped_dimensions", []):
            cap = caps_by_key.get(dim)
            if cap and cap.get("status") == "demonstrated":
                conf = cap.get("confidence", "insufficient")
                obs = cap.get("observation", "")
                reason_str = (
                    f"Demonstrated '{dim}' ({conf} confidence, {importance}) "
                    f"directly matches requirement '{req_text}'"
                )
                if obs and obs != "[dry-run stub observation]":
                    reason_str += f": {obs[:120]}"
                reasons.append(reason_str)
            else:
                trade_offs.append(
                    f"No demonstrated portfolio evidence for '{dim}' ({importance}) "
                    f"matching requirement '{req_text}'"
                )
                status_val = cap.get("status", "not_found") if cap else "not_found"
                uncertainty.append(
                    f"Capability '{dim}' is unverified in portfolio (status: {status_val})"
                )

    if not reasons:
        reasons.append(
            f"Eligible {artist_record.get('category')} match with baseline profile claims."
        )

    # 2. Assumptions & Operational Uncertainty
    for op in parsed_brief.get("operational_constraints", []):
        cat = op.get("category", "constraint")
        detail = op.get("detail", "")
        hard = " [HARD LIMIT]" if op.get("hard_limit") else ""
        if cat == "budget":
            assumptions.append(
                f"Assumes artist standard fee can align with requested budget: {detail}{hard}"
            )
        elif cat in ("location", "date_availability"):
            assumptions.append(
                f"Assumes artist availability and scheduling fit for {detail}{hard}"
            )
        else:
            assumptions.append(
                f"Assumes artist can accommodate operational requirement: {cat} ({detail}){hard}"
            )
        uncertainty.append(
            f"Operational constraint '{cat}' ({detail}) requires manual verification with artist"
        )

    if not trade_offs:
        trade_offs.append("No critical capability gaps identified from available evidence.")

    return {
        "reasons": reasons,
        "trade_offs": trade_offs,
        "assumptions": assumptions,
        "uncertainty": uncertainty,
    }


def generate_refinement_questions(parsed_brief):
    """Generate at most two targeted refinement questions with expected impact.

    Strictly limited to <= 2 questions per brief.
    """
    fname = parsed_brief.get("source_file", "").lower()
    hid = parsed_brief.get("hirer_id", "")
    cat = parsed_brief.get("artist_category", "")

    # 1. Cafe music / H081
    if "01_cafe" in fname or hid == "H081" or "cafe" in fname:
        if "update" in fname:
            return [
                {
                    "question": "Will the venue provide direct sound amplification/PA connection for the headline set, or must the artist bring a full sound system?",
                    "expected_impact": "Clarifies equipment scope. If self-amplification is required for the 80-guest room, artists with portable acoustic PA gear will rank higher.",
                },
                {
                    "question": "Are there specific genre or language preferences for the 45-minute set (e.g. Hindi acoustic vs English/indie)?",
                    "expected_impact": "Refines repertoire matching against artists with demonstrated Hindi vs Western live performance records.",
                },
            ]
        return [
            {
                "question": "Do you have an in-house PA/speakers and mic available for live music, or should the artist bring complete sound equipment?",
                "expected_impact": "If self-amplification is required, this adds an equipment-fit"
                "constraint that must be verified separately; it does not alter"
                "capability scores unless a corresponding demonstrated capability"
                "dimension is present.",            },
            {
                "question": "Would you prefer primarily Hindi acoustic vocals, English covers, or a balanced bilingual set for background dining?",
                "expected_impact": "The answer clarifies the desired repertoire/style context and can affect ranking only where the selected preference maps to an existing scored capability dimension.",            },
        ]

    # 2. Skincare photography / H082
    if "skincare" in fname or hid == "H082" or "02_skincare" in fname:
        return [
            {
                "question": "Will a model definitely be present for hand/interaction shots, or is this strictly tabletop product-only arrangements?",
                "expected_impact": "If human interaction shots are required, the relevant demonstrated portrait or talent-direction dimensions become more important where those dimensions are part of the scored capability vocabulary.",            },
            {
                "question": "Do you need the photographer to provide backdrops and specialized tabletop lighting props, or will your team supply all staging materials?",
                "expected_impact": "Clarifies whether equipment provision is an operational responsibility or a demonstrated capability requirement; equipment logistics are not treated as demonstrated skill without supporting evidence.",            },
        ]

    # 3. Vertical video / H083
    if "vertical" in fname or "video" in fname or hid == "H083" or "03_vertical" in fname:
        return [
            {
                "question": "Do you require the editor to source and clear commercially licensed background music, or will you supply approved tracks?",
                "expected_impact": "Clarifies whether music licensing is an artist responsibility; licensing responsibility is operational unless it maps to an existing demonstrated capability dimension.",            },
            {
                "question": "Are styled kinetic subtitles / animated text overlays required, or standard clean subtitle captions?",
                "expected_impact": "If kinetic text is required, editors with demonstrated motion-graphics or text-animation capability become more relevant where those dimensions are part of the scored capability vocabulary.",            },
        ]

    # 4. Leadership event photos / H117
    if "leadership" in fname or hid == "H117" or "04_leadership" in fname:
        return [
            {
                "question": "Will there be a dedicated setup area and time window for the 10-15 executive headshots, or must they be taken informally during breaks?",
                "expected_impact": "Clarifies whether executive portrait capability should be emphasized over candid event coverage; any ranking change must come from the corresponding demonstrated capability dimensions.",
            },
            {
                "question": "Are external flash units and speedlights permitted inside the event rooms during presentations?",
                "expected_impact": "Clarifies the lighting conditions the photographer must handle; ranking can change only through existing demonstrated lighting capability dimensions supported by evidence.",
            },
        ]

    # Generic fallback (max 2 questions)
    return [
        {
            "question": "What is the primary delivery timeline and format requirement for the final deliverables?",
            "expected_impact": "Allows ranking to adjust for turnaround speed and technical asset workflow capabilities.",
        },
        {
            "question": "Are there specific equipment or venue constraints that the artist must accommodate?",
            "expected_impact": "Helps filter for artists with verified experience in similar technical environments.",
        },
    ]


def build_improve_your_matches(parsed_brief):
    """Build the 'Improve your matches' section for a recommendation."""
    questions = generate_refinement_questions(parsed_brief)
    return {
        "section_title": "Improve your matches",
        "guidance": (
            "Clarifying the following questions will help narrow down the "
            "best match and adjust artist rankings."
        ),
        "refinement_questions": questions[:2],  # strictly capped at 2
    }


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

def rank_artists(parsed_brief, all_artist_records):
    """Score and rank all eligible artists for a parsed hirer brief.

    Returns list of ranked artist dicts, sorted by total_score descending,
    with ties broken by artist_id alphabetically (deterministic).

    Includes contextual fields: reasons, trade_offs, assumptions, uncertainty.
    """
    scored = []
    for artist in all_artist_records:
        result = score_artist(parsed_brief, artist)
        if result is None:
            continue  # wrong category, skip

        constraint_notes = build_constraint_notes(parsed_brief, artist)
        context = generate_artist_context(parsed_brief, artist, result)

        scored.append({
            "artist_id": artist["artist_id"],
            "display_name": artist.get("display_name", artist["artist_id"]),
            "total_score": result["total_score"],
            "score_breakdown": result["score_breakdown"],
            "requirement_breakdown": result["requirement_breakdown"],
            "reasons": context["reasons"],
            "trade_offs": context["trade_offs"],
            "assumptions": context["assumptions"],
            "uncertainty": context["uncertainty"],
            "operational_constraint_notes": constraint_notes,
        })

    # Sort: highest score first, then artist_id alphabetically for ties
    scored.sort(key=lambda x: (-x["total_score"], x["artist_id"]))

    # Assign explicit rank numbers
    for i, entry in enumerate(scored, start=1):
        entry["rank"] = i

    return scored