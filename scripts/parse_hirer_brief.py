#!/usr/bin/env python3
"""
Sekeron Stage 4 - Hirer Brief Parser
========================================

Parses raw hirer conversation/brief text into structured requirement objects
using Gemini for the interpretive parsing, with deterministic post-validation.

Gemini maps free-text requirements to the shared capability vocabulary
(imported from capability_vocabulary.py). Code validates that every
mapped_dimension and operational constraint category exists in the
vocabulary - hallucinated or misspelled keys are rejected with a warning.

Has --dry-run mode that returns deterministic stub parsed output without
any API calls.

NO scoring. NO ranking. NO artist matching. This module only parses.

Requires: Python 3.9+, requests (see requirements.txt).
"""

import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests is not installed. Run: pip install -r requirements.txt",
          file=sys.stderr)
    sys.exit(1)

# Import shared vocabulary - single source of truth for dimension keys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_vocabulary import (
    CAPABILITY_KEYS_BY_CATEGORY,
    CATEGORY_DIMENSIONS,
    OPERATIONAL_CATEGORIES,
)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
REQUEST_TIMEOUT_SECONDS = 120


# --------------------------------------------------------------------------
# Gemini structured-output schema for brief parsing
# --------------------------------------------------------------------------

def build_parse_schema():
    """JSON schema for Gemini's structured response."""
    return {
        "type": "OBJECT",
        "properties": {
            "hirer_id": {"type": "STRING"},
            "artist_category": {
                "type": "STRING",
                "enum": list(CATEGORY_DIMENSIONS.keys()),
            },
            "capability_requirements": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "requirement_text": {"type": "STRING"},
                        "mapped_dimensions": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                        },
                        "importance": {
                            "type": "STRING",
                            "enum": ["must_have", "nice_to_have"],
                        },
                    },
                    "required": [
                        "requirement_text",
                        "mapped_dimensions",
                        "importance",
                    ],
                },
            },
            "operational_constraints": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "category": {
                            "type": "STRING",
                            "enum": OPERATIONAL_CATEGORIES,
                        },
                        "detail": {"type": "STRING"},
                        "hard_limit": {"type": "BOOLEAN"},
                    },
                    "required": ["category", "detail", "hard_limit"],
                },
            },
        },
        "required": [
            "hirer_id",
            "artist_category",
            "capability_requirements",
            "operational_constraints",
        ],
    }


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------

def build_parse_prompt(brief_text, source_file):
    """Build the prompt for Gemini to parse a hirer brief."""
    dim_lines = []
    for cat, dims in CATEGORY_DIMENSIONS.items():
        keys = [d["capability"] for d in dims]
        dim_lines.append(f"  {cat}: {', '.join(keys)}")
    dim_text = "\n".join(dim_lines)
    op_text = ", ".join(OPERATIONAL_CATEGORIES)

    return f"""You are parsing a hirer's inquiry/brief into structured requirements \
for an artist matching system.

SOURCE FILE: {source_file}

RULES:
1. Identify the hirer_id from the text. Look for reference numbers like \
"enquiry 081" → "H081", "Ref H-117" → "H117". If no reference is found, \
derive one from the source filename by adding 80 to the file prefix number (e.g. "02_skincare..." → "H082", "03_vertical..." → "H083").
2. Determine the artist_category the hirer needs (one of: \
{', '.join(CATEGORY_DIMENSIONS.keys())}).
3. Extract capability_requirements — things the hirer wants the artist to \
be able to DO or demonstrate. Each requirement must map to one or more \
dimensions from the EXACT lists below. ONLY use dimension keys from the \
correct category's list — do not invent new ones.
4. Extract operational_constraints — logistical/practical conditions (budget, \
dates, location, etc.). Use ONLY these constraint categories: {op_text}
5. Capability requirements and operational constraints are STRUCTURALLY \
SEPARATE. A budget is always an operational constraint, never a \
capability_requirement. A skill like "acoustic guitar" is always a \
capability_requirement, never an operational constraint.
6. importance: "must_have" if the hirer clearly needs this, "nice_to_have" \
if it's optional/preferred/bonus.
7. hard_limit: true if violating this constraint would be a dealbreaker.

VALID DIMENSION KEYS PER CATEGORY:
{dim_text}

VALID OPERATIONAL CONSTRAINT CATEGORIES:
{op_text}

BRIEF TEXT:
{brief_text}

Return ONLY the JSON matching the provided schema."""


# --------------------------------------------------------------------------
# Gemini API call
# --------------------------------------------------------------------------

def call_gemini_parse(brief_text, source_file, api_key):
    """Call Gemini to parse a brief. Returns parsed dict."""
    prompt = build_parse_prompt(brief_text, source_file)
    schema = build_parse_schema()
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    resp = requests.post(
        GEMINI_API_URL, headers=headers, json=body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# --------------------------------------------------------------------------
# Dry-run stub parser — deterministic, no API calls
# --------------------------------------------------------------------------

def dry_run_stub_parse(brief_text, source_file):
    """Deterministic stub parse for --dry-run mode. No API calls.

    Maps each of the 5 known briefs to a hand-crafted parsed structure
    that exercises the full vocabulary. Falls back to a generic stub for
    unknown briefs.
    """
    fname = source_file.lower()
    text_lower = brief_text.lower()

    # ---- Cafe follow-up (must check before original cafe) ----
    if "update" in fname and ("cafe" in fname or "081" in fname):
        return {
            "hirer_id": "H081",
            "artist_category": "musician",
            "capability_requirements": [
                {
                    "requirement_text": (
                        "proper 45 min headline set, needs to feel like a "
                        "performance/moment"
                    ),
                    "mapped_dimensions": [
                        "performance_format",
                        "live_vs_studio_context",
                    ],
                    "importance": "must_have",
                },
                {
                    "requirement_text": "acoustic is still fine",
                    "mapped_dimensions": ["genre_style_signal"],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "engaging performance for ~80 guests, dynamic feel"
                    ),
                    "mapped_dimensions": ["audio_arrangement_characteristics"],
                    "importance": "nice_to_have",
                },
            ],
            "operational_constraints": [
                {
                    "category": "budget",
                    "detail": "up to 15k",
                    "hard_limit": True,
                },
                {
                    "category": "guest_count",
                    "detail": "around 80 guests",
                    "hard_limit": False,
                },
                {
                    "category": "equipment",
                    "detail": (
                        "can clear a small area for performance, "
                        "speaker situation still pending"
                    ),
                    "hard_limit": False,
                },
            ],
        }

    # ---- Original cafe music ----
    if "cafe" in fname or "enquiry 081" in text_lower:
        return {
            "hirer_id": "H081",
            "artist_category": "musician",
            "capability_requirements": [
                {
                    "requirement_text": (
                        "acoustic, not too loud, people should still be "
                        "able to talk — background music"
                    ),
                    "mapped_dimensions": [
                        "genre_style_signal",
                        "performance_format",
                    ],
                    "importance": "must_have",
                },
                {
                    "requirement_text": "Hindi/English vocals",
                    "mapped_dimensions": ["vocal_or_instrumental_role"],
                    "importance": "nice_to_have",
                },
                {
                    "requirement_text": (
                        "slightly lively bit later if possible"
                    ),
                    "mapped_dimensions": ["audio_arrangement_characteristics"],
                    "importance": "nice_to_have",
                },
            ],
            "operational_constraints": [
                {
                    "category": "budget",
                    "detail": "around 7k, absolute max 9k",
                    "hard_limit": True,
                },
                {
                    "category": "date_availability",
                    "detail": "next Friday, 7 PM to 10 PM",
                    "hard_limit": True,
                },
                {
                    "category": "equipment",
                    "detail": (
                        "no massive setup, no stage, PA/speakers uncertain"
                    ),
                    "hard_limit": False,
                },
            ],
        }

    # ---- Skincare product photography ----
    if "skincare" in fname or "product photographer" in text_lower:
        return {
            "hirer_id": "H082",
            "artist_category": "photographer",
            "capability_requirements": [
                {
                    "requirement_text": (
                        "product photography, clean/premium look, "
                        "not hospital/super white"
                    ),
                    "mapped_dimensions": [
                        "subject_domain",
                        "lighting_treatment",
                    ],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "clean premium color treatment, warm but not sterile"
                    ),
                    "mapped_dimensions": ["color_tone_treatment"],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "can handle a simple setup themselves, no studio"
                    ),
                    "mapped_dimensions": ["technical_control_indicators"],
                    "importance": "nice_to_have",
                },
                {
                    "requirement_text": (
                        "square and vertical crops for website + Instagram"
                    ),
                    "mapped_dimensions": ["composition_technique"],
                    "importance": "nice_to_have",
                },
            ],
            "operational_constraints": [
                {
                    "category": "budget",
                    "detail": "about 18k with basic retouching",
                    "hard_limit": True,
                },
                {
                    "category": "turnaround_time",
                    "detail": "selects needed in 2 days",
                    "hard_limit": True,
                },
                {
                    "category": "location",
                    "detail": "Gurgaon ideal, Delhi can work",
                    "hard_limit": False,
                },
                {
                    "category": "usage_rights",
                    "detail": (
                        "own website and social channels, "
                        "pending marketing confirmation"
                    ),
                    "hard_limit": False,
                },
            ],
        }

    # ---- Vertical video reel ----
    if "vertical" in fname or "video" in fname or "reel editor" in text_lower:
        return {
            "hirer_id": "H083",
            "artist_category": "video_editor",
            "capability_requirements": [
                {
                    "requirement_text": (
                        "vertical reel ~30 sec, energetic but clean, "
                        "not crazy transitions"
                    ),
                    "mapped_dimensions": [
                        "pacing_rhythm",
                        "content_format_context",
                    ],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "find the story from ~70 clips, "
                        "not just put every clip in order"
                    ),
                    "mapped_dimensions": ["visual_sequencing_signals"],
                    "importance": "must_have",
                },
                {
                    "requirement_text": "captions where anyone is speaking",
                    "mapped_dimensions": ["audio_dialogue_handling"],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "clean composition and framing, "
                        "no over-the-top transitions"
                    ),
                    "mapped_dimensions": ["shot_composition_and_framing"],
                    "importance": "nice_to_have",
                },
            ],
            "operational_constraints": [
                {
                    "category": "budget",
                    "detail": "8-10k",
                    "hard_limit": True,
                },
                {
                    "category": "turnaround_time",
                    "detail": "first cut by Friday evening",
                    "hard_limit": True,
                },
                {
                    "category": "other",
                    "detail": (
                        "may need to suggest alternative song "
                        "due to licensing concerns"
                    ),
                    "hard_limit": False,
                },
            ],
        }

    # ---- Leadership event photography ----
    if "leadership" in fname or "h-117" in text_lower:
        return {
            "hirer_id": "H117",
            "artist_category": "photographer",
            "capability_requirements": [
                {
                    "requirement_text": (
                        "candid event coverage — not stiff conference "
                        "photos, people talking, exercises, reactions"
                    ),
                    "mapped_dimensions": [
                        "shooting_context_style",
                        "subject_domain",
                    ],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "dynamic compositions capturing interactions "
                        "and group activities"
                    ),
                    "mapped_dimensions": ["composition_technique"],
                    "importance": "must_have",
                },
                {
                    "requirement_text": (
                        "quick headshots for 10–15 leadership team members"
                    ),
                    "mapped_dimensions": ["lighting_treatment"],
                    "importance": "nice_to_have",
                },
                {
                    "requirement_text": (
                        "8–10 pictures same evening for LinkedIn, "
                        "quick turnaround on selects"
                    ),
                    "mapped_dimensions": ["technical_control_indicators"],
                    "importance": "nice_to_have",
                },
            ],
            "operational_constraints": [
                {
                    "category": "date_availability",
                    "detail": "4 Sept, likely 10am–3pm",
                    "hard_limit": True,
                },
                {
                    "category": "location",
                    "detail": "South Delhi, venue TBD",
                    "hard_limit": False,
                },
                {
                    "category": "guest_count",
                    "detail": "around 120 people (110–130)",
                    "hard_limit": False,
                },
                {
                    "category": "equipment",
                    "detail": "room and flash policy unknown",
                    "hard_limit": False,
                },
            ],
        }

    # ---- Generic fallback (should not be reached for known briefs) ----
    return {
        "hirer_id": f"H{abs(hash(source_file)) % 1000:03d}",
        "artist_category": "photographer",
        "capability_requirements": [
            {
                "requirement_text": "general requirement (dry-run fallback)",
                "mapped_dimensions": ["subject_domain"],
                "importance": "must_have",
            },
        ],
        "operational_constraints": [],
    }


# --------------------------------------------------------------------------
# Post-parse validation — deterministic, enforces vocabulary alignment
# --------------------------------------------------------------------------

def validate_parsed_brief(parsed, source_file):
    """Validate that a parsed brief uses only valid vocabulary keys.

    - Raises ValueError if any mapped_dimension is not in CAPABILITY_KEYS_BY_CATEGORY
      for the parsed artist_category.
    - Raises ValueError if any operational constraint is not in OPERATIONAL_CATEGORIES.
    - Returns (parsed, []).
    """
    category = parsed.get("artist_category")
    valid_dims = CAPABILITY_KEYS_BY_CATEGORY.get(category, set())

    # Validate capability requirements
    for req in parsed.get("capability_requirements", []):
        for dim in req.get("mapped_dimensions", []):
            if dim not in valid_dims:
                raise ValueError(
                    f"Invalid mapped_dimension '{dim}' for category '{category}' "
                    f"in {source_file}."
                )

    # Validate operational constraints
    for op in parsed.get("operational_constraints", []):
        if op["category"] not in OPERATIONAL_CATEGORIES:
            raise ValueError(
                f"Invalid operational constraint category '{op['category']}' "
                f"in {source_file}."
            )

    return parsed, []


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def parse_brief(brief_text, source_file, api_key=None, dry_run=False):
    """Parse a hirer brief into structured requirements.

    Args:
        brief_text: Raw text of the hirer's conversation/brief.
        source_file: Filename of the brief (for traceability).
        api_key: Gemini API key (required unless dry_run=True).
        dry_run: If True, use deterministic stub output, no API calls.

    Returns:
        (parsed_brief_dict, warnings_list)
    """
    if dry_run:
        parsed = dry_run_stub_parse(brief_text, source_file)
    else:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY required when not in dry-run mode"
            )
        parsed = call_gemini_parse(brief_text, source_file, api_key)

    parsed["source_file"] = source_file
    parsed, warnings = validate_parsed_brief(parsed, source_file)

    parsed["parsing_metadata"] = {
        "model": "dry-run-stub" if dry_run else GEMINI_MODEL,
        "manual_edits": False,
    }

    return parsed, warnings
