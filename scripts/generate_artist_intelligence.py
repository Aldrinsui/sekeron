#!/usr/bin/env python3
"""
Sekeron Stage 3 - Artist Intelligence Generation
=====================================================

Combines profile claims (artist_profiles.json) and selected portfolio
evidence (evidence_manifest.json) into an evidence-backed capability
record per artist, using Gemini for the genuinely interpretive parts
(looking at images/frames, listening to audio, judging whether a
profile claim is supported/unsupported/contradicted by evidence).

Everything that does NOT require interpretation is done deterministically
in code, never left to the model:
  - profile claim text itself (segmented verbatim from already-extracted text)
  - which evidence exists and its counts (from evidence_manifest.json)
  - which evidence is attached to the model call vs. omitted for context
    efficiency (perceptual-hash near-duplicate detection for images/frames;
    a duration budget for audio) - always recorded, never silently dropped
  - evidence_id resolution (any citation to evidence not actually shown
    to the model is stripped, and the affected capability is downgraded)
  - confidence ceiling enforcement (the model can rate a capability LOWER
    than the evidence volume would allow, never higher)
  - checklist completeness (every category dimension always gets a record;
    a dimension the model skipped becomes an explicit insufficient_evidence
    entry, never silently missing)

Produces:
    generated/artist_intelligence.jsonl              (one record per artist)
    generated/artist_intelligence_run_meta.json       (model/version/thresholds)
    generated/artist_intelligence_validation_report.json

READ-ONLY GUARANTEE: never touches --dataset-root. Only reads already-
generated evidence assets under generated/evidence_assets/ and the
original photographer images (read-only open, never written to).

API KEY: read from the GEMINI_API_KEY environment variable only. Never
hardcoded, printed, logged, or written to any output file.

Usage:
    export GEMINI_API_KEY="your-key-here"
    python3 scripts/generate_artist_intelligence.py \\
        --dataset-root "/path/to/Data set" \\
        --dataset-manifest generated/dataset_manifest.json \\
        --evidence-manifest generated/evidence_manifest.json \\
        --profiles generated/artist_profiles.json \\
        --output-dir generated

    Add --dry-run to exercise the full pipeline (context selection, claim
    segmentation, validation, clamping, file writing) with a fabricated
    stub model response and NO network calls or API cost - useful for a
    quick sanity check before spending anything.

Requires: Python 3.9+, Pillow, requests (see requirements.txt).
"""

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# --------------------------------------------------------------------------
# CONFIG / THRESHOLDS - documented here, nowhere else.
# --------------------------------------------------------------------------
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
REQUEST_TIMEOUT_SECONDS = 180
MAX_MODEL_RETRIES = 2
RETRY_BACKOFF_SECONDS = 5

# Context-efficiency budgets (per artist, per Gemini call)
IMAGE_CONTEXT_BUDGET_PER_ARTIST = 20   # max images/frames attached; P03's 21 images is the dataset max
AHASH_SIZE = 8                          # 8x8 -> 64-bit perceptual hash, using Pillow only (no new dependency)
AHASH_NEAR_DUP_HAMMING_THRESHOLD = 5    # bits differing; below this, treated as visually near-duplicate
AUDIO_CONTEXT_SECONDS_BUDGET_PER_ARTIST = 480.0  # 8 min; generous safety cap, not expected to bind on this dataset

CONFIDENCE_LEVELS = ["insufficient", "low", "medium", "high"]
STATUS_LEVELS = ["demonstrated", "insufficient_evidence", "conflicting_evidence"]
CLAIM_RELATIONSHIPS = ["supported", "unsupported_no_evidence", "contradicted"]

EXPECTED_ARTIST_COUNT = 15

# --------------------------------------------------------------------------
# Category-specific dimension checklists.
# Every artist in a category is assessed against every dimension in their
# checklist - the model cannot skip one; skipped dimensions become an
# explicit insufficient_evidence record via code-side completeness checking.
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Perceptual hashing (Pillow only - no new dependency) for image/frame
# context-efficiency selection.
# --------------------------------------------------------------------------

def average_hash(image_path: Path):
    try:
        with Image.open(image_path) as img:
            gray = img.convert("L").resize((AHASH_SIZE, AHASH_SIZE))
            pixels = list(gray.getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if p >= avg else "0" for p in pixels)
            return int(bits, 2)
    except Exception:
        return None


def hamming_distance(a, b):
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------
# Mime type detection - cross-references Stage 1's ACTUAL detected format
# (not the file extension), so e.g. PO4's *.png-named-but-actually-JPEG
# files are sent with the correct mime type instead of trusting the name.
# --------------------------------------------------------------------------

def build_format_lookup(dataset_manifest):
    lookup = {}
    for artist in dataset_manifest["artists"]:
        for m in artist["media_files"]:
            if m["media_type"] == "image" and m.get("format"):
                lookup[m["relative_path"]] = m["format"]
    return lookup


FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def guess_image_mime(relative_path_or_none, extracted_path: Path, format_lookup):
    if relative_path_or_none and relative_path_or_none in format_lookup:
        fmt = format_lookup[relative_path_or_none]
        if fmt in FORMAT_TO_MIME:
            return FORMAT_TO_MIME[fmt]
    ext = extracted_path.suffix.lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")


# --------------------------------------------------------------------------
# Profile claim segmentation - deterministic, code-only. The model never
# writes claim_text; it only receives it and classifies its relationship
# to evidence. This avoids any transcription drift/hallucination risk.
# --------------------------------------------------------------------------

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def segment_profile_claims(artist_id, profile_text):
    if not profile_text:
        return []
    fragments = [f.strip() for f in SENTENCE_SPLIT_RE.split(profile_text) if f.strip()]
    claims = []
    for i, frag in enumerate(fragments, start=1):
        if len(frag) < 8:  # skip stray fragments (e.g. a lone table header word)
            continue
        claims.append({"claim_id": f"{artist_id}-PC{i:02d}", "claim_text": frag})
    return claims


# --------------------------------------------------------------------------
# Context selection: decide which evidence items are actually attached
# (binary content) to this artist's Gemini call, vs. considered-but-omitted
# for context efficiency. Never silently discarded - omissions are recorded
# with an explicit, reproducible reason.
# --------------------------------------------------------------------------

def select_context_evidence(artist_id, eligible_evidence, dataset_root, output_dir, format_lookup):
    image_items = []  # (evidence_id, resolved_path, source_relative_path, ev_dict)
    audio_items = []

    for ev in eligible_evidence:
        loc_type = ev["locator"].get("type")
        if ev["media_type"] == "image" and loc_type == "full_image":
            image_items.append((ev["evidence_id"], dataset_root / ev["source_relative_path"], ev["source_relative_path"], ev))
        elif ev["media_type"] == "video" and loc_type == "frame" and ev.get("extracted_asset_path"):
            image_items.append((ev["evidence_id"], output_dir / ev["extracted_asset_path"], ev["source_relative_path"], ev))
        elif ev["media_type"] == "audio" and loc_type in ("segment", "audio_track") and ev.get("extracted_asset_path"):
            audio_items.append((ev["evidence_id"], output_dir / ev["extracted_asset_path"], ev))

    image_items.sort(key=lambda t: t[0])  # deterministic order
    audio_items.sort(key=lambda t: t[0])

    selected_images = []
    omitted = []

    # Phase A: breadth-first coverage - always keep the first item per unique source file.
    kept_hashes = []
    kept_ids = set()
    seen_sources = set()
    for eid, path, src, ev in image_items:
        if src not in seen_sources:
            h = average_hash(path)
            selected_images.append((eid, path, src, ev, h))
            kept_ids.add(eid)
            seen_sources.add(src)
            if h is not None:
                kept_hashes.append((eid, h))

    # Phase B: fill remaining budget with non-near-duplicate items.
    budget_remaining = max(0, IMAGE_CONTEXT_BUDGET_PER_ARTIST - len(selected_images))
    for eid, path, src, ev in image_items:
        if eid in kept_ids:
            continue
        if budget_remaining <= 0:
            omitted.append({"evidence_id": eid, "reason": f"per_artist_image_budget_reached (budget={IMAGE_CONTEXT_BUDGET_PER_ARTIST})"})
            continue
        h = average_hash(path)
        if h is None:
            selected_images.append((eid, path, src, ev, h))
            kept_hashes.append((eid, h))
            budget_remaining -= 1
            continue
        nearest = min(((oid, hamming_distance(h, oh)) for oid, oh in kept_hashes if oh is not None), default=(None, 999), key=lambda t: t[1])
        if nearest[1] < AHASH_NEAR_DUP_HAMMING_THRESHOLD:
            omitted.append({"evidence_id": eid, "reason": f"near_visual_duplicate_of={nearest[0]} (hamming_distance={nearest[1]})"})
        else:
            selected_images.append((eid, path, src, ev, h))
            kept_hashes.append((eid, h))
            budget_remaining -= 1

    if len(selected_images) > IMAGE_CONTEXT_BUDGET_PER_ARTIST:
        # Coverage guarantee (Phase A) can slightly exceed the budget if an artist has more
        # unique source files than the budget itself - documented, not silently truncated.
        pass

    selected_audio = []
    running_seconds = 0.0
    for eid, path, ev in audio_items:
        loc = ev["locator"]
        dur = loc.get("end_seconds", 0) - loc.get("start_seconds", 0)
        if running_seconds + dur > AUDIO_CONTEXT_SECONDS_BUDGET_PER_ARTIST:
            omitted.append({"evidence_id": eid, "reason": f"audio_context_seconds_budget_reached (budget={AUDIO_CONTEXT_SECONDS_BUDGET_PER_ARTIST:.0f}s)"})
            continue
        selected_audio.append((eid, path, ev))
        running_seconds += dur

    summary = {
        "total_eligible_evidence": len(eligible_evidence),
        "selected_for_model_context": len(selected_images) + len(selected_audio),
        "omitted_for_context_efficiency": len(omitted),
        "omitted_details": omitted,
    }
    return selected_images, selected_audio, summary


# --------------------------------------------------------------------------
# Gemini request construction and call (isolated so it's mockable/testable
# without network access - see --dry-run).
# --------------------------------------------------------------------------

def build_response_schema(dimensions):
    capability_item_schema = {
        "type": "OBJECT",
        "properties": {
            "capability": {"type": "STRING"},
            "status": {"type": "STRING", "enum": STATUS_LEVELS},
            "confidence": {"type": "STRING", "enum": CONFIDENCE_LEVELS},
            "observation": {"type": "STRING"},
            "evidence_references": {
                "type": "ARRAY",
                "items": {"type": "OBJECT", "properties": {
                    "evidence_id": {"type": "STRING"},
                    "note": {"type": "STRING"},
                }, "required": ["evidence_id"]},
            },
            "unknowns_limitations": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["capability", "status", "confidence", "observation", "evidence_references", "unknowns_limitations"],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "demonstrated_capabilities": {"type": "ARRAY", "items": capability_item_schema},
            "additional_observed_capabilities": {"type": "ARRAY", "items": capability_item_schema, "maxItems": 2},
            "claim_evaluations": {
                "type": "ARRAY",
                "items": {"type": "OBJECT", "properties": {
                    "claim_id": {"type": "STRING"},
                    "relationship": {"type": "STRING", "enum": CLAIM_RELATIONSHIPS},
                    "related_capability": {"type": "STRING"},
                    "explanation": {"type": "STRING"},
                }, "required": ["claim_id", "relationship", "explanation"]},
            },
        },
        "required": ["demonstrated_capabilities", "additional_observed_capabilities", "claim_evaluations"],
    }


def build_prompt_parts(artist_id, category, dimensions, profile_claims, data_quality_observations,
                        selected_images, selected_audio, context_summary, format_lookup):
    dim_lines = "\n".join(f"- {d['capability']} ({d['dimension_group']}): {d['guidance']}" for d in dimensions)
    claim_lines = "\n".join(f"- [{c['claim_id']}] {c['claim_text']}" for c in profile_claims) or "(no profile claims extracted)"
    dq_lines = "\n".join(f"- {o}" for o in data_quality_observations) or "(none)"

    intro = f"""You are assessing artist {artist_id} (category: {category}) for a skills/evidence intelligence system.

RULES (follow exactly):
1. Assess EVERY dimension listed below. If evidence does not support a dimension, set status="insufficient_evidence", confidence="insufficient", evidence_references=[], and explain why in unknowns_limitations. Do NOT invent a capability.
1a. You may report up to two additional_observed_capabilities only when a useful capability is directly observable in the supplied evidence and is not adequately represented by the standard dimensions above. These are supplementary observations, not replacements for standard dimensions. Do not infer them from profile claims alone. Use concise, evidence-grounded capability names.
2. A capability may only be "demonstrated" if you can point to specific evidence_id(s) you were actually shown below, and your observation must describe what is actually visible/audible in that evidence - not what the profile claims, and not the fact that it was "selected" (selection is not proof).
3. If evidence for a dimension conflicts with itself or is genuinely ambiguous, you may still use status="demonstrated" with confidence="low" and explain the ambiguity - only use "conflicting_evidence" status for the claim_evaluations conflict case below, not for internal evidence ambiguity.
4. confidence must reflect the AMOUNT and CLARITY of evidence, not your confidence in your own reasoning.
5. Evidence marked as "cross-artist duplicate" or "flagged anomaly" in its label can still be described, but should generally not support "high" confidence alone.
6. Never infer reliability, punctuality, professionalism, popularity, character, trustworthiness, socioeconomic status, identity, or authorship/ownership from filenames. Never attempt to identify or reverse-search any person shown.
7. For each profile claim listed below, decide: "supported" (evidence confirms it), "unsupported_no_evidence" (evidence neither confirms nor denies it), or "contradicted" (evidence appears to actively contradict it). Only "contradicted" is a conflict - do not mark something "contradicted" just because it's simply unproven.
8. Output ONLY the JSON matching the provided schema. No prose outside the JSON.

DIMENSIONS TO ASSESS:
{dim_lines}

PROFILE CLAIMS (verbatim from the artist's profile document - these are CLAIMS ONLY, not verified):
{claim_lines}

KNOWN DATA-QUALITY OBSERVATIONS FOR THIS ARTIST (from automated dataset inspection - factual, not character judgments):
{dq_lines}

You are being shown {context_summary['selected_for_model_context']} of {context_summary['total_eligible_evidence']} total available evidence items for this artist. The rest were omitted only for context-size efficiency (e.g. visually near-duplicate frames from the same clip) - they are NOT unavailable, just not attached to this call. Do not assume anything about their content; do not cite their evidence_ids since you were not shown them.

EVIDENCE SHOWN BELOW (each preceded by its evidence_id label):
"""
    parts = [{"text": intro}]

    for eid, path, src, ev, _h in selected_images:
        mime = guess_image_mime(src if ev["media_type"] == "image" else None, path, format_lookup)
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as e:
            parts.append({"text": f"[evidence_id {eid}: FAILED TO READ FILE, treat as unavailable - {e}]"})
            continue
        label = f"Evidence {eid} (source: {ev.get('display_label', src)}"
        if ev["media_type"] == "video":
            ts = ev["locator"].get("timestamp_seconds")
            label += f", video frame at {ts}s"
        label += "):"
        parts.append({"text": label})
        parts.append({"inline_data": {"mime_type": mime, "data": data}})

    for eid, path, ev in selected_audio:
        try:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as e:
            parts.append({"text": f"[evidence_id {eid}: FAILED TO READ FILE, treat as unavailable - {e}]"})
            continue
        loc = ev["locator"]
        label = (f"Evidence {eid} (source: {ev.get('display_label')}, audio "
                 f"{loc.get('start_seconds', 0):.1f}s-{loc.get('end_seconds', 0):.1f}s):")
        parts.append({"text": label})
        parts.append({"inline_data": {"mime_type": "audio/wav", "data": data}})

    parts.append({"text": "Now return the JSON assessment for this artist, per the rules above."})
    return parts


def call_gemini(parts, response_schema, api_key):
    """Isolated so it can be swapped for a stub in --dry-run / tests."""
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    resp = requests.post(GEMINI_API_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return text


def dry_run_stub_response(dimensions, profile_claims, selected_images, selected_audio):
    """Fabricates a structurally valid response for pipeline testing WITHOUT
    any network call or API cost. Used only when --dry-run is passed."""
    caps = []
    shown_ids = [t[0] for t in selected_images] + [t[0] for t in selected_audio]
    for i, d in enumerate(dimensions):
        if shown_ids and i % 2 == 0:
            caps.append({
                "capability": d["capability"], "status": "demonstrated", "confidence": "low",
                "observation": "[dry-run stub observation]",
                "evidence_references": [{"evidence_id": shown_ids[0], "note": "[dry-run stub]"}],
                "unknowns_limitations": ["[dry-run stub - not a real assessment]"],
            })
        else:
            caps.append({
                "capability": d["capability"], "status": "insufficient_evidence", "confidence": "insufficient",
                "observation": "", "evidence_references": [],
                "unknowns_limitations": ["[dry-run stub: no evidence assigned]"],
            })
    claim_evals = [{"claim_id": c["claim_id"], "relationship": "unsupported_no_evidence",
                     "related_capability": "", "explanation": "[dry-run stub]"} for c in profile_claims]
    return json.dumps({"demonstrated_capabilities": caps, "additional_observed_capabilities": [], "claim_evaluations": claim_evals})


# --------------------------------------------------------------------------
# Post-processing: evidence-id resolution + confidence-ceiling enforcement.
# The model does not get the final word on either.
# --------------------------------------------------------------------------

def confidence_ceiling(independent_count, all_flagged_or_cross_artist):
    if independent_count == 0:
        return "insufficient"
    if all_flagged_or_cross_artist:
        return "low"
    if independent_count == 1:
        return "medium"
    return "high"


CONF_RANK = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}


def clamp_capability(cap, shown_evidence_by_id, warnings, artist_id):
    valid_refs = []
    for ref in cap.get("evidence_references", []):
        eid = ref.get("evidence_id")
        if eid in shown_evidence_by_id:
            valid_refs.append({**ref, **shown_evidence_by_id[eid]})
        else:
            warnings.append(f"{artist_id}/{cap.get('capability')}: dropped citation to unshown/unknown evidence_id '{eid}'")
    cap["evidence_references"] = valid_refs

    if cap["status"] in ("demonstrated", "conflicting_evidence") and not valid_refs:
        warnings.append(f"{artist_id}/{cap.get('capability')}: no valid evidence after resolution - downgraded to insufficient_evidence")
        cap["status"] = "insufficient_evidence"
        cap["confidence"] = "insufficient"
        cap.setdefault("unknowns_limitations", []).append(
            "Model-cited evidence could not be resolved to evidence actually shown; downgraded automatically."
        )

    independent_count = sum(1 for r in valid_refs if r.get("counts_as_independent_evidence", True))
    all_flagged = bool(valid_refs) and all(r.get("status") != "ok" for r in valid_refs)
    ceiling = confidence_ceiling(independent_count, all_flagged)

    cap["supporting_evidence_strength"] = {
        "independent_evidence_count": independent_count,
        "media_types_represented": sorted({r.get("media_type") for r in valid_refs if r.get("media_type")}),
        "excluded_duplicate_or_flagged_count": sum(1 for r in valid_refs if r.get("status") != "ok"),
    }

    if cap["status"] != "insufficient_evidence":
        model_conf = cap.get("confidence", "insufficient")
        if model_conf not in CONF_RANK:
            model_conf = "insufficient"
        if CONF_RANK[model_conf] > CONF_RANK[ceiling]:
            warnings.append(
                f"{artist_id}/{cap.get('capability')}: model confidence '{model_conf}' exceeds evidence-based "
                f"ceiling '{ceiling}' ({independent_count} independent item(s)); clamped down."
            )
            cap["confidence"] = ceiling
    # Clean evidence_references down to the schema-facing shape
    cap["evidence_references"] = [
        {"evidence_id": r["evidence_id"], "source_relative_path": r.get("source_relative_path"),
         "locator": r.get("locator"), "note": r.get("note", "")}
        for r in valid_refs
    ]
    return cap


def build_completeness_fill(dimension, artist_id):
    return {
        "capability": dimension["capability"],
        "dimension_group": dimension["dimension_group"],
        "status": "insufficient_evidence",
        "confidence": "insufficient",
        "observation": "",
        "evidence_references": [],
        "supporting_evidence_strength": {"independent_evidence_count": 0, "media_types_represented": [], "excluded_duplicate_or_flagged_count": 0},
        "related_profile_claim_ids": [],
        "unknowns_limitations": ["Model response did not address this dimension; auto-filled as insufficient_evidence for completeness."],
        "is_standard_checklist_dimension": True,
    }


# --------------------------------------------------------------------------
# Data-quality observation assembly (code-only, from upstream JSON).
# --------------------------------------------------------------------------

def assemble_data_quality_observations(artist_id, folder_name, dataset_manifest_artist, evidence_manifest_artist):
    obs = []
    if re.search(r"[A-Za-z]0\d|[A-Za-z]O\d", folder_name):
        if "O" in folder_name.split("_")[0]:
            obs.append(f"Folder name '{folder_name}' uses the letter 'O' rather than digit '0' in its numbering; "
                       f"artist_id preserved verbatim as '{artist_id}', not normalized.")
    seen_flags = set()
    for ev in evidence_manifest_artist["evidence"]:
        for note in ev.get("anomaly_notes", []):
            key = note.split(" - ")[0].split("(")[0].strip()
            if key not in seen_flags:
                seen_flags.add(key)
                obs.append(f"{ev['evidence_id']}: {note}")
    return obs


# --------------------------------------------------------------------------
# Main orchestration
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate evidence-backed artist intelligence via Gemini.")
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--dataset-manifest", required=True, type=Path)
    parser.add_argument("--evidence-manifest", required=True, type=Path)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="No network calls; uses a fabricated stub response to test the pipeline.")
    parser.add_argument(
    "--artist-id",
    action="append",
    dest="artist_ids",
    help="Process only the specified artist ID(s). May be provided multiple times.",
    )
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()

    if not dataset_root.exists():
        print(f"ERROR: dataset root does not exist: {dataset_root}", file=sys.stderr)
        sys.exit(1)
    try:
        output_dir.relative_to(dataset_root)
        print(f"ERROR: --output-dir ({output_dir}) is inside --dataset-root ({dataset_root}). Refusing to run.", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        pass

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: GEMINI_API_KEY environment variable is not set. Refusing to run without it (and --dry-run was not passed).",
              file=sys.stderr)
        sys.exit(1)

    with open(args.dataset_manifest, "r", encoding="utf-8") as f:
        dataset_manifest = json.load(f)
    with open(args.evidence_manifest, "r", encoding="utf-8") as f:
        evidence_manifest = json.load(f)
    with open(args.profiles, "r", encoding="utf-8") as f:
        profiles_doc = json.load(f)

    format_lookup = build_format_lookup(dataset_manifest)
    dataset_artist_by_id = {a["artist_id"]: a for a in dataset_manifest["artists"]}
    profile_text_by_artist = {}
    for rec in profiles_doc["artist_profiles"]:
        if rec["extraction_status"] == "ok" and rec.get("profile_text"):
            profile_text_by_artist.setdefault(rec["artist_id"], []).append(rec["profile_text"])

    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    global_warnings = []
    response_schema = build_response_schema(CATEGORY_DIMENSIONS["photographer"])  # placeholder, rebuilt per category below

    for ev_artist in evidence_manifest["artists"]:
        if args.artist_ids and ev_artist["artist_id"] not in args.artist_ids:
            continue
        artist_id = ev_artist["artist_id"]
        category = ev_artist["category"]
        ds_artist = dataset_artist_by_id.get(artist_id, {})
        folder_name = ds_artist.get("folder_name", artist_id)
        display_name = ds_artist.get("display_name", artist_id)
        dimensions = CATEGORY_DIMENSIONS.get(category, [])
        print(f"Processing {artist_id} ({category})...")

        eligible_evidence = [ev for ev in ev_artist["evidence"] if ev["status"] not in ("duplicate", "insufficient_evidence")]
        data_quality_observations = assemble_data_quality_observations(artist_id, folder_name, ds_artist, ev_artist)

        raw_profile_text = "\n\n".join(profile_text_by_artist.get(artist_id, []))
        profile_claims = segment_profile_claims(artist_id, raw_profile_text)

        selected_images, selected_audio, context_summary = select_context_evidence(
            artist_id, eligible_evidence, dataset_root, output_dir, format_lookup
        )

        shown_evidence_by_id = {}
        for eid, path, src, ev, _h in selected_images:
            shown_evidence_by_id[eid] = {
                "source_relative_path": ev["source_relative_path"], "locator": ev["locator"],
                "status": ev["status"], "media_type": ev["media_type"],
                "counts_as_independent_evidence": ev.get("counts_as_independent_evidence", True),
            }
        for eid, path, ev in selected_audio:
            shown_evidence_by_id[eid] = {
                "source_relative_path": ev["source_relative_path"], "locator": ev["locator"],
                "status": ev["status"], "media_type": ev["media_type"],
                "counts_as_independent_evidence": ev.get("counts_as_independent_evidence", True),
            }

        response_schema = build_response_schema(dimensions)
        prompt_parts = build_prompt_parts(
            artist_id, category, dimensions, profile_claims, data_quality_observations,
            selected_images, selected_audio, context_summary, format_lookup
        )

        model_json = None
        gen_error = None
        for attempt in range(1, MAX_MODEL_RETRIES + 2):
            try:
                if args.dry_run:
                    raw_text = dry_run_stub_response(dimensions, profile_claims, selected_images, selected_audio)
                else:
                    raw_text = call_gemini(prompt_parts, response_schema, api_key)
                model_json = json.loads(raw_text)
                break
            except Exception as e:
                gen_error = f"{type(e).__name__}: {e}"
                global_warnings.append(f"{artist_id}: generation attempt {attempt} failed - {gen_error}")
                if attempt <= MAX_MODEL_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS)

        capability_warnings = []
        if model_json is None:
            demonstrated_capabilities = [build_completeness_fill(d, artist_id) for d in dimensions]
            claim_evaluations = []
            additional_caps = []
            generation_status = "generation_failed"
        else:
            generation_status = "ok"
            model_caps_by_key = {c["capability"]: c for c in model_json.get("demonstrated_capabilities", [])}
            demonstrated_capabilities = []
            for d in dimensions:
                if d["capability"] in model_caps_by_key:
                    cap = dict(model_caps_by_key[d["capability"]])
                    cap["dimension_group"] = d["dimension_group"]
                    cap["is_standard_checklist_dimension"] = True
                    cap = clamp_capability(cap, shown_evidence_by_id, capability_warnings, artist_id)
                else:
                    cap = build_completeness_fill(d, artist_id)
                demonstrated_capabilities.append(cap)

            additional_caps = []
            for cap in model_json.get("additional_observed_capabilities", [])[:2]:
                cap = dict(cap)
                cap["dimension_group"] = "additional"
                cap["is_standard_checklist_dimension"] = False
                cap = clamp_capability(cap, shown_evidence_by_id, capability_warnings, artist_id)
                additional_caps.append(cap)

            claim_evaluations = model_json.get("claim_evaluations", [])

        global_warnings.extend(capability_warnings)

        # Link claims + build conflicts, deterministically from claim_evaluations.
        claims_by_id = {c["claim_id"]: c for c in profile_claims}
        caps_by_capability = {c["capability"]: c for c in demonstrated_capabilities}
        conflicts = []
        for ce in claim_evaluations:
            cid = ce.get("claim_id")
            if cid not in claims_by_id:
                global_warnings.append(f"{artist_id}: claim_evaluation referenced unknown claim_id '{cid}', dropped.")
                continue
            rel = ce.get("relationship")
            if rel not in CLAIM_RELATIONSHIPS:
                continue
            related_cap_key = ce.get("related_capability")
            if rel == "supported" and related_cap_key in caps_by_capability:
                caps_by_capability[related_cap_key].setdefault("related_profile_claim_ids", [])
                if cid not in caps_by_capability[related_cap_key]["related_profile_claim_ids"]:
                    caps_by_capability[related_cap_key]["related_profile_claim_ids"].append(cid)
            elif rel == "contradicted":
                conflicts.append({
                    "profile_claim_id": cid,
                    "capability_dimension": related_cap_key if related_cap_key in caps_by_capability else None,
                    "description": ce.get("explanation", ""),
                    "resolution": "unresolved_both_retained",
                })
                if related_cap_key in caps_by_capability:
                    caps_by_capability[related_cap_key]["status"] = "conflicting_evidence"

        for cap in demonstrated_capabilities + additional_caps:
            cap.setdefault("related_profile_claim_ids", [])

        evidence_coverage_summary = {
            "total_evidence_items_available": len(ev_artist["evidence"]),
            "independent_evidence_used": sum(1 for e in ev_artist["evidence"] if e.get("counts_as_independent_evidence") and e["status"] != "duplicate"),
            "duplicate_excluded": sum(1 for e in ev_artist["evidence"] if e["status"] == "duplicate"),
            "flagged_anomaly_included_with_caveat": sum(1 for e in ev_artist["evidence"] if e["status"] == "flagged_anomaly"),
            "insufficient_evidence_items_skipped": sum(1 for e in ev_artist["evidence"] if e["status"] == "insufficient_evidence"),
        }

        record = {
            "artist_id": artist_id,
            "folder_name": folder_name,
            "display_name": display_name,
            "category": category,
            "data_quality_observations": data_quality_observations,
            "profile_claims": profile_claims,
            "demonstrated_capabilities": demonstrated_capabilities + additional_caps,
            "conflicts": conflicts,
            "evidence_coverage_summary": evidence_coverage_summary,
            "context_selection_summary": context_summary,
            "generation_metadata": {
                "generated_by": "scripts/generate_artist_intelligence.py",
                "model": "dry-run-stub" if args.dry_run else GEMINI_MODEL,
                "status": generation_status,
                "error": gen_error if model_json is None else None,
                "manual_edits": False,
            },
        }
        records.append(record)

    out_path = output_dir / "artist_intelligence.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote: {out_path} ({len(records)} records)")

    run_meta = {
        "generated_by": "scripts/generate_artist_intelligence.py",
        "model": "dry-run-stub" if args.dry_run else GEMINI_MODEL,
        "dry_run": args.dry_run,
        "expected_artist_count": EXPECTED_ARTIST_COUNT,
        "actual_artist_count": len(records),
        "thresholds": {
            "image_context_budget_per_artist": IMAGE_CONTEXT_BUDGET_PER_ARTIST,
            "ahash_near_dup_hamming_threshold": AHASH_NEAR_DUP_HAMMING_THRESHOLD,
            "audio_context_seconds_budget_per_artist": AUDIO_CONTEXT_SECONDS_BUDGET_PER_ARTIST,
            "confidence_ceiling_rule": "0 independent items -> insufficient (forced); 1 -> medium max; 2+ -> high max; "
                                       "all-flagged/cross-artist-only evidence -> low max regardless of count.",
        },
        "warnings": global_warnings,
    }
    with open(output_dir / "artist_intelligence_run_meta.json", "w", encoding="utf-8") as f:
        json.dump(run_meta, f, indent=2, ensure_ascii=False)

    # Validation report
    validation = {
        "all_15_artists_present": {"passed": len(records) == EXPECTED_ARTIST_COUNT, "count": len(records)},
        "every_dimension_covered": {"passed": True, "details": []},
        "every_demonstrated_capability_has_evidence": {"passed": True, "details": []},
        "no_capability_confidence_exceeds_ceiling": {"passed": True, "details": []},
        "generation_failures": {"passed": True, "details": []},
    }
    for r in records:
        expected_dims = {d["capability"] for d in CATEGORY_DIMENSIONS.get(r["category"], [])}
        present_dims = {c["capability"] for c in r["demonstrated_capabilities"] if c.get("is_standard_checklist_dimension")}
        if expected_dims - present_dims:
            validation["every_dimension_covered"]["passed"] = False
            validation["every_dimension_covered"]["details"].append(f"{r['artist_id']}: missing {expected_dims - present_dims}")
        for c in r["demonstrated_capabilities"]:
            if c["status"] in ("demonstrated", "conflicting_evidence") and not c["evidence_references"]:
                validation["every_demonstrated_capability_has_evidence"]["passed"] = False
                validation["every_demonstrated_capability_has_evidence"]["details"].append(
                    f"{r['artist_id']}/{c['capability']}: status={c['status']} but no evidence_references"
                )
        if r["generation_metadata"]["status"] != "ok":
            validation["generation_failures"]["passed"] = False
            validation["generation_failures"]["details"].append(f"{r['artist_id']}: {r['generation_metadata']['error']}")

    validation["no_capability_confidence_exceeds_ceiling"]["details"] = [
        w for w in global_warnings if "exceeds evidence-based" in w
    ]

    with open(output_dir / "artist_intelligence_validation_report.json", "w", encoding="utf-8") as f:
        json.dump(validation, f, indent=2, ensure_ascii=False)

    all_passed = all(v["passed"] for v in validation.values())
    print(f"Validation: {'ALL PASSED' if all_passed else 'SOME CHECKS FAILED - see artist_intelligence_validation_report.json'}")
    if global_warnings:
        print(f"{len(global_warnings)} warning(s) - see artist_intelligence_run_meta.json")


if __name__ == "__main__":
    main()
