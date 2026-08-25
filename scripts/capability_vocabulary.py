#!/usr/bin/env python3
"""
Sekeron Stage 3 - Shared Capability Vocabulary
===================================================

Single source of truth for the exact capability dimension keys, status
values, and confidence levels used throughout the pipeline.

CATEGORY_DIMENSIONS here is byte-for-byte the same object that
generate_artist_intelligence.py uses to build artist_intelligence.jsonl.
parse_hirer_brief.py and recommendation_scoring.py import THIS module
rather than redefining the list, so hirer-requirement dimension mapping
can never drift out of sync with what artist_intelligence.jsonl actually
contains - a typo or renamed dimension in one place breaks imports
everywhere else instead of silently producing unmatched requirements.

Do not duplicate these lists elsewhere. Import from here.
"""

CONFIDENCE_LEVELS = ["insufficient", "low", "medium", "high"]
STATUS_LEVELS = ["demonstrated", "insufficient_evidence"]
CLAIM_RELATIONSHIPS = ["supported", "unsupported_no_evidence", "contradicted"]

EXPECTED_ARTIST_COUNT = 15

CATEGORY_DIMENSIONS = {
    "photographer": [
        {"capability": "subject_domain", "dimension_group": "subject",
         "guidance": "What kind of subject matter is depicted (portrait, candid, event, landscape, product, etc.)?"},
        {"capability": "composition_technique", "dimension_group": "composition",
         "guidance": "Framing, balance, use of space, rule-of-thirds/symmetry or deliberate departures from it."},
        {"capability": "lighting_treatment", "dimension_group": "lighting",
         "guidance": "Natural vs. studio light, low-light handling, directionality, hard vs. soft light."},
        {"capability": "color_tone_treatment", "dimension_group": "color",
         "guidance": "Color grading style, black-and-white vs. color, saturation/contrast choices."},
        {"capability": "environment_context", "dimension_group": "environment",
         "guidance": "Indoor/outdoor/studio/urban/natural setting as depicted."},
        {"capability": "technical_control_indicators", "dimension_group": "technical",
         "guidance": "Visible outcomes only - focus/depth-of-field control, sharpness, motion blur. Do NOT infer camera settings not visible in the image."},
        {"capability": "shooting_context_style", "dimension_group": "style",
         "guidance": "Candid vs. posed, single-subject vs. group, documentary vs. directed."},
    ],
    "musician": [
        {"capability": "vocal_or_instrumental_role", "dimension_group": "role",
         "guidance": "Is a voice present? An instrument? Which, if identifiable from audio/visual evidence?"},
        {"capability": "genre_style_signal", "dimension_group": "style",
         "guidance": "Audible style signals only - frame as observed signals, not an authoritative genre label."},
        {"capability": "performance_format", "dimension_group": "format",
         "guidance": "Solo vs. ensemble, based on audible voices/instruments or visible performers."},
        {"capability": "live_vs_studio_context", "dimension_group": "context",
         "guidance": "Crowd noise, stage lighting, room acoustics vs. a clean studio-style recording."},
        {"capability": "instrumental_technical_signals", "dimension_group": "technical",
         "guidance": "Only if visually evidenced - e.g. hand position on an instrument, visible technique."},
        {"capability": "audio_arrangement_characteristics", "dimension_group": "arrangement",
         "guidance": "Layering, dynamics, tempo changes actually audible in the supplied segment(s)."},
    ],
    "video_editor": [
        {"capability": "pacing_rhythm", "dimension_group": "pacing",
         "guidance": "Judge from the actual visual content and variety across sampled frames of a clip - not from scene-cut counts alone, which are structural metadata, not proof by themselves."},
        {"capability": "shot_composition_and_framing", "dimension_group": "composition",
         "guidance": "Framing quality/style across sampled frames."},
        {"capability": "visual_sequencing_signals", "dimension_group": "sequencing",
         "guidance": "Do frames from the same clip suggest coherent narrative flow vs. abrupt jump cuts?"},
        {"capability": "color_treatment", "dimension_group": "color",
         "guidance": "Grading/tone consistency or style visible across frames."},
        {"capability": "content_format_context", "dimension_group": "format",
         "guidance": "What kind of content is this (event coverage, vlog, performance capture, interview, etc.)?"},
        {"capability": "motion_graphics_or_overlay_evidence", "dimension_group": "graphics",
         "guidance": "Only if text overlays/graphics/titles are actually visible in a sampled frame."},
        {"capability": "audio_dialogue_handling", "dimension_group": "audio",
         "guidance": "Based on the one representative audio sample per clip. Comment on clarity, mix, presence of dialogue/music/ambient sound - do not speculate about full-clip editing choices beyond what this sample supports."},
    ],
}

CAPABILITY_KEYS_BY_CATEGORY = {
    cat: {d["capability"] for d in dims} for cat, dims in CATEGORY_DIMENSIONS.items()
}

# Operational constraint categories are structurally separate from capability
# dimensions - a fixed, closed taxonomy. These NEVER appear as mapped_dimensions
# on a capability_requirement, and are NEVER used in scoring. See
# recommendation_scoring.py for enforcement.
OPERATIONAL_CATEGORIES = [
    "budget", "location", "date_availability", "turnaround_time",
    "guest_count", "equipment", "usage_rights", "other",
]
