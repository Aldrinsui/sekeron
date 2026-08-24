#!/usr/bin/env python3
"""
Sekeron Stage 3 - Stage 2: Media Evidence Selection Pipeline
===============================================================

Reads the Stage 1 dataset_manifest.json + the original dataset (read-only)
and produces a selective, precisely-referenced evidence pack:

  generated/evidence_manifest.json     (machine-readable evidence index)
  generated/evidence_selection_log.md  (human-readable rationale + findings)
  generated/evidence_assets/<artist_id>/frames/*.jpg
  generated/evidence_assets/<artist_id>/audio_segments/*.wav

READ-ONLY GUARANTEE (same as Stage 1):
This script never writes, renames, moves, or modifies anything under
--dataset-root. All ffmpeg invocations that touch a source file are
extraction-only (read the source, write a NEW file elsewhere). The
--output-dir is checked at startup and refused if it resolves inside
--dataset-root.

NO artist intelligence, scoring, embeddings, RAG, or model calls happen
in this stage. This stage only decides WHICH evidence to extract and
WHERE it points, with a machine-written rationale for every item.

Usage:
    python3 scripts/select_evidence.py \\
        --dataset-root "/path/to/Data set" \\
        --manifest generated/dataset_manifest.json \\
        --output-dir generated

Requires: Python 3.9+, Pillow, ffmpeg/ffprobe on PATH (see requirements.txt).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageStat
except ImportError:
    print("ERROR: Pillow is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

# --------------------------------------------------------------------------
# SELECTION THRESHOLDS - all documented here, nowhere else. Change only here.
# --------------------------------------------------------------------------
AUDIO_FULL_INCLUDE_MAX_SECONDS = 45.0      # audio files at/under this length: include in full
AUDIO_WINDOW_SECONDS = 15.0                # length of each sampled window for longer audio
AUDIO_WINDOW_FRACTIONS = [0.10, 0.45, 0.80]  # window start points, as fraction of duration
AUDIO_EXTRACT_SAMPLE_RATE = 16000          # downsampled for evidence pack size; sufficient for
                                            # content/feature inspection, not meant for playback fidelity
AUDIO_EXTRACT_CHANNELS = 1

VIDEO_ANCHOR_FRACTIONS = [0.10, 0.50, 0.90]  # always-taken temporal anchor frames
SCENE_MIN_VIDEO_DURATION = 15.0            # below this duration, skip scene detection (anchors only)
SCENE_SCORE_THRESHOLD = 0.4                # ffmpeg scene score above which a cut is a "candidate"
SCENE_MAX_CANDIDATE_FRAMES = 8             # hard cap on scene-change frames PER VIDEO (not per artist)
SCENE_DEDUPE_SECONDS = 1.0                 # skip a scene candidate within this many seconds of an anchor
PER_ARTIST_FRAME_SOFT_BUDGET = 60          # informational soft cap only - never padded to reach

MUSICIAN_VIDEO_FULL_AUDIO_MAX_SECONDS = 120.0  # musician video clips at/under this: extract full audio
                                                 # track as primary evidence (none in this dataset exceed it,
                                                 # rule kept explicit for reproducibility on future data)

BLACKDETECT_MIN_DURATION = 0.5
BLACKDETECT_PIC_TH = 0.98
BLACK_ANOMALY_RATIO = 0.20                 # >20% of video duration black -> anomaly flag

SILENCEDETECT_NOISE_DB = "-30dB"
SILENCEDETECT_MIN_DURATION = 0.5
SILENCE_ANOMALY_RATIO = 0.50               # >50% of an audio segment silent -> anomaly flag

FRAME_STDDEV_BLANK_THRESHOLD = 5.0         # grayscale pixel stddev below this -> possible blank/solid frame

FFMPEG_TIMEOUT_SECONDS = 180

# Heuristic only - flags filenames that plausibly reference a named public
# figure, so we can generate a sanitized display_label per requirement 4.
# This is a coarse keyword heuristic, not a verified identification, and is
# documented as a limitation in the selection log.
NAMED_INDIVIDUAL_KEYWORDS = ["MODI", "PM_", "MINISTER", "PRESIDENT", "CELEBRITY"]

STOCK_MUSIC_FILENAME_PATTERN = re.compile(
    r"^[a-z0-9]+-[a-z0-9-]+-\d{5,7}\.(mp3|wav)$", re.IGNORECASE
)


# --------------------------------------------------------------------------
# Utility
# --------------------------------------------------------------------------

def sha256_of_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def run_subprocess(cmd, timeout=FFMPEG_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "", "TIMEOUT"
    except FileNotFoundError as e:
        return None, "", f"NOT_FOUND: {e}"


def extract_frame(source_path: Path, timestamp_seconds: float, out_path: Path) -> tuple:
    """Extract a single JPEG still at timestamp_seconds. Returns (ok, error_msg)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", f"{timestamp_seconds:.3f}", "-i", str(source_path),
        "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(out_path),
    ]
    rc, _, err = run_subprocess(cmd)
    if rc != 0 or not out_path.exists():
        return False, err or "unknown ffmpeg error"
    return True, None


def extract_audio_segment(source_path: Path, start_seconds: float, duration_seconds: float,
                           out_path: Path) -> tuple:
    """Extract an audio segment (or full track if start=0 and duration covers it) as
    downsampled mono WAV. Returns (ok, error_msg)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-ss", f"{start_seconds:.3f}", "-i", str(source_path),
        "-t", f"{duration_seconds:.3f}",
        "-vn", "-ac", str(AUDIO_EXTRACT_CHANNELS), "-ar", str(AUDIO_EXTRACT_SAMPLE_RATE),
        "-acodec", "pcm_s16le", "-loglevel", "error", str(out_path),
    ]
    rc, _, err = run_subprocess(cmd)
    if rc != 0 or not out_path.exists():
        return False, err or "unknown ffmpeg error"
    return True, None


def detect_scene_candidates(source_path: Path, duration: float):
    """Runs ffmpeg's built-in scene-change scorer (single decode pass, no frames
    saved) and returns a list of (timestamp_seconds, score) sorted by score desc.
    On any failure, returns an empty list (falls back to anchors-only) rather
    than raising - scene detection is an enhancement, not a hard requirement."""
    cmd = [
        "ffmpeg", "-i", str(source_path),
        "-filter:v", f"select='gt(scene,{SCENE_SCORE_THRESHOLD})',metadata=print,showinfo",
        "-an", "-f", "null", "-loglevel", "info", "-",
    ]
    rc, out, err = run_subprocess(cmd)
    combined = (out or "") + (err or "")
    if rc is None:
        return []

    candidates = []
    last_score = None
    for line in combined.splitlines():
        score_match = re.search(r"lavfi\.scene_score\s*=\s*([\d.]+)", line)
        if score_match:
            try:
                last_score = float(score_match.group(1))
            except ValueError:
                last_score = None
            continue
        time_match = re.search(r"pts_time:([\d.]+)", line)
        if time_match and last_score is not None:
            try:
                ts = float(time_match.group(1))
                if 0.0 <= ts <= duration:
                    candidates.append((ts, last_score))
            except ValueError:
                pass
            last_score = None

    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates


def detect_black_ratio(source_path: Path, duration: float) -> float:
    """Returns fraction of video duration flagged as black by ffmpeg blackdetect.
    Returns 0.0 on failure (does not block the pipeline)."""
    if duration <= 0:
        return 0.0
    cmd = [
        "ffmpeg", "-i", str(source_path),
        "-vf", f"blackdetect=d={BLACKDETECT_MIN_DURATION}:pic_th={BLACKDETECT_PIC_TH}",
        "-an", "-f", "null", "-loglevel", "info", "-",
    ]
    rc, out, err = run_subprocess(cmd)
    combined = (out or "") + (err or "")
    if rc is None:
        return 0.0
    total_black = 0.0
    for match in re.finditer(r"black_duration:([\d.]+)", combined):
        try:
            total_black += float(match.group(1))
        except ValueError:
            pass
    return min(total_black / duration, 1.0)


def detect_silence_ratio(audio_path: Path, duration: float) -> float:
    """Returns fraction of an (already-extracted, short) audio file flagged as
    silence. Returns 0.0 on failure."""
    if duration <= 0:
        return 0.0
    cmd = [
        "ffmpeg", "-i", str(audio_path),
        "-af", f"silencedetect=noise={SILENCEDETECT_NOISE_DB}:d={SILENCEDETECT_MIN_DURATION}",
        "-f", "null", "-loglevel", "info", "-",
    ]
    rc, out, err = run_subprocess(cmd)
    combined = (out or "") + (err or "")
    if rc is None:
        return 0.0
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*([\d.]+)", combined)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*([\d.]+)", combined)]
    total_silence = 0.0
    for s, e in zip(starts, ends):
        total_silence += max(0.0, e - s)
    return min(total_silence / duration, 1.0)


def frame_stddev(image_path: Path):
    """Returns grayscale pixel stddev of an extracted frame, or None on failure."""
    try:
        with Image.open(image_path) as img:
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            return stat.stddev[0]
    except Exception:
        return None


def check_named_individual_heuristic(filename: str) -> bool:
    upper = filename.upper()
    return any(kw in upper for kw in NAMED_INDIVIDUAL_KEYWORDS)


def check_stock_music_filename_pattern(filename: str) -> bool:
    return bool(STOCK_MUSIC_FILENAME_PATTERN.match(filename))


# --------------------------------------------------------------------------
# Evidence ID allocation
# --------------------------------------------------------------------------

class EvidenceIdAllocator:
    def __init__(self):
        self._counters = {}

    def next_id(self, artist_id: str) -> str:
        n = self._counters.get(artist_id, 0) + 1
        self._counters[artist_id] = n
        return f"{artist_id}-E{n:03d}"


# --------------------------------------------------------------------------
# Per-media-type processing
# --------------------------------------------------------------------------

def process_image(artist_id, media_record, dataset_root, output_dir, id_alloc, warnings):
    """Photographers: inspect every image directly. No extraction/copy needed -
    the original file itself IS the evidence; we reference its path."""
    src_rel = media_record["relative_path"]
    src_path = dataset_root / src_rel
    filename = media_record["filename"]

    anomaly_notes = []
    status = "ok"

    stddev = frame_stddev(src_path)
    if stddev is None:
        anomaly_notes.append("could_not_compute_pixel_variance")
        status = "flagged_anomaly"
    elif stddev < FRAME_STDDEV_BLANK_THRESHOLD:
        anomaly_notes.append(f"low_pixel_variance_stddev={stddev:.2f}_possible_blank_or_solid_image")
        status = "flagged_anomaly"

    display_label = filename
    if check_named_individual_heuristic(filename):
        display_label = "photographer_media_generic_label.jpg"
        anomaly_notes.append("filename_pattern_anomaly:possible_named_individual_reference")

    evidence = {
        "evidence_id": id_alloc.next_id(artist_id),
        "artist_id": artist_id,
        "source_relative_path": src_rel,
        "display_label": display_label,
        "media_type": "image",
        "locator": {"type": "full_image"},
        "selection_method": "full_inspection",
        "selection_rationale": "Photographer image; total per-artist image volume is small, "
                                "so all supplied images are inspected directly rather than sampled.",
        "extracted_asset_path": None,  # original file is used directly, nothing extracted/copied
        "status": status,
        "anomaly_notes": anomaly_notes,
        "counts_as_independent_evidence": True,
    }
    return [evidence]


def process_audio(artist_id, media_record, dataset_root, output_dir, id_alloc, warnings):
    src_rel = media_record["relative_path"]
    src_path = dataset_root / src_rel
    filename = media_record["filename"]
    duration = media_record.get("duration_seconds") or 0.0

    filename_flags = []
    if check_stock_music_filename_pattern(filename):
        filename_flags.append("filename_pattern_anomaly:resembles_stock_music_library_naming_convention")

    display_label = filename
    if check_named_individual_heuristic(filename):
        display_label = "audio_media_generic_label.wav"
        filename_flags.append("filename_pattern_anomaly:possible_named_individual_reference")

    asset_dir = output_dir / "evidence_assets" / artist_id / "audio_segments"
    evidence_items = []

    if duration <= AUDIO_FULL_INCLUDE_MAX_SECONDS:
        windows = [(0.0, duration)]
        method = "full_inclusion"
        reason_tmpl = f"Audio file is {duration:.1f}s (<= {AUDIO_FULL_INCLUDE_MAX_SECONDS}s threshold); included in full."
    else:
        windows = []
        for frac in AUDIO_WINDOW_FRACTIONS:
            start = frac * duration
            end = min(start + AUDIO_WINDOW_SECONDS, duration)
            if end - start >= 2.0:  # skip degenerate near-zero windows
                windows.append((start, end))
        method = "duration_fraction_window"
        reason_tmpl = None

    for i, (start, end) in enumerate(windows):
        seg_duration = end - start
        eid = id_alloc.next_id(artist_id)
        out_name = f"{eid}.wav"
        out_path = asset_dir / out_name
        ok, err = extract_audio_segment(src_path, start, seg_duration, out_path)

        anomaly_notes = list(filename_flags)
        status = "ok"
        if not ok:
            status = "extraction_failed"
            anomaly_notes.append(f"ffmpeg_extraction_error: {err}")
        else:
            silence_ratio = detect_silence_ratio(out_path, seg_duration)
            if silence_ratio > SILENCE_ANOMALY_RATIO:
                anomaly_notes.append(f"content_anomaly:silence_ratio={silence_ratio:.2f}_exceeds_threshold")
                status = "flagged_anomaly"

        if reason_tmpl:
            rationale = reason_tmpl
        else:
            frac = AUDIO_WINDOW_FRACTIONS[i] if i < len(AUDIO_WINDOW_FRACTIONS) else None
            rationale = (
                f"Audio file is {duration:.1f}s (> {AUDIO_FULL_INCLUDE_MAX_SECONDS}s threshold); "
                f"sampled a {seg_duration:.1f}s window starting at "
                f"{f'{frac*100:.0f}%' if frac is not None else 'n/a'} of duration "
                f"({start:.1f}s-{end:.1f}s) to represent structurally distinct sections "
                f"(intro/core/outro) without processing the full file."
            )

        evidence_items.append({
            "evidence_id": eid,
            "artist_id": artist_id,
            "source_relative_path": src_rel,
            "display_label": display_label,
            "media_type": "audio",
            "locator": {"type": "segment", "start_seconds": round(start, 3), "end_seconds": round(end, 3)},
            "selection_method": method,
            "selection_rationale": rationale,
            "extracted_asset_path": str((asset_dir / out_name).relative_to(output_dir)) if ok else None,
            "status": status,
            "anomaly_notes": anomaly_notes,
            "counts_as_independent_evidence": True,
        })

    return evidence_items


def process_video(artist_id, category, media_record, dataset_root, output_dir, id_alloc, warnings):
    src_rel = media_record["relative_path"]
    src_path = dataset_root / src_rel
    filename = media_record["filename"]
    duration = media_record.get("duration_seconds") or 0.0

    filename_flags = []
    display_label = filename
    if check_named_individual_heuristic(filename):
        display_label = "video_media_generic_label.mp4"
        filename_flags.append("filename_pattern_anomaly:possible_named_individual_reference")

    frames_dir = output_dir / "evidence_assets" / artist_id / "frames"
    audio_dir = output_dir / "evidence_assets" / artist_id / "audio_segments"
    evidence_items = []

    black_ratio = detect_black_ratio(src_path, duration) if duration > 0 else 0.0
    video_level_anomalies = list(filename_flags)
    if black_ratio > BLACK_ANOMALY_RATIO:
        video_level_anomalies.append(f"content_anomaly:black_frame_ratio={black_ratio:.2f}_exceeds_threshold")

    # --- Always-taken temporal anchor frames ---
    anchor_timestamps = []
    for frac in VIDEO_ANCHOR_FRACTIONS:
        ts = round(frac * duration, 3)
        anchor_timestamps.append(ts)
        eid = id_alloc.next_id(artist_id)
        out_path = frames_dir / f"{eid}.jpg"
        ok, err = extract_frame(src_path, ts, out_path)

        anomaly_notes = list(video_level_anomalies)
        status = "ok"
        if not ok:
            status = "extraction_failed"
            anomaly_notes.append(f"ffmpeg_extraction_error: {err}")
        else:
            stddev = frame_stddev(out_path)
            if stddev is not None and stddev < FRAME_STDDEV_BLANK_THRESHOLD:
                anomaly_notes.append(f"low_pixel_variance_stddev={stddev:.2f}_possible_blank_or_solid_frame")
                status = "flagged_anomaly"

        evidence_items.append({
            "evidence_id": eid,
            "artist_id": artist_id,
            "source_relative_path": src_rel,
            "display_label": display_label,
            "media_type": "video",
            "locator": {"type": "frame", "timestamp_seconds": ts},
            "selection_method": "temporal_anchor",
            "selection_rationale": f"Required temporal anchor at {frac*100:.0f}% of {duration:.1f}s duration.",
            "extracted_asset_path": str((frames_dir / f"{eid}.jpg").relative_to(output_dir)) if ok else None,
            "status": status,
            "anomaly_notes": anomaly_notes,
            "counts_as_independent_evidence": True,
        })

    # --- Scene-change candidate frames (video editors: primary signal for pacing/cuts;
    #     musicians: skipped, since anchors + full audio track are sufficient there) ---
    if category == "video_editor" and duration >= SCENE_MIN_VIDEO_DURATION:
        candidates = detect_scene_candidates(src_path, duration)
        selected = 0
        for rank, (ts, score) in enumerate(candidates, start=1):
            if selected >= SCENE_MAX_CANDIDATE_FRAMES:
                break
            if any(abs(ts - a) < SCENE_DEDUPE_SECONDS for a in anchor_timestamps):
                continue
            eid = id_alloc.next_id(artist_id)
            out_path = frames_dir / f"{eid}.jpg"
            ok, err = extract_frame(src_path, ts, out_path)

            anomaly_notes = list(video_level_anomalies)
            status = "ok"
            if not ok:
                status = "extraction_failed"
                anomaly_notes.append(f"ffmpeg_extraction_error: {err}")
            else:
                stddev = frame_stddev(out_path)
                if stddev is not None and stddev < FRAME_STDDEV_BLANK_THRESHOLD:
                    anomaly_notes.append(f"low_pixel_variance_stddev={stddev:.2f}_possible_blank_or_solid_frame")
                    status = "flagged_anomaly"

            evidence_items.append({
                "evidence_id": eid,
                "artist_id": artist_id,
                "source_relative_path": src_rel,
                "display_label": display_label,
                "media_type": "video",
                "locator": {"type": "frame", "timestamp_seconds": round(ts, 3)},
                "selection_method": "scene_change_candidate",
                "selection_rationale": f"selected as a high-scoring scene-change candidate "
                                        f"(score={score:.2f}, rank {rank} of {len(candidates)} candidates found)",
                "extracted_asset_path": str((frames_dir / f"{eid}.jpg").relative_to(output_dir)) if ok else None,
                "status": status,
                "anomaly_notes": anomaly_notes,
                "counts_as_independent_evidence": True,
            })
            selected += 1
        if not candidates:
            warnings.append(
                f"{artist_id}: scene-change detection returned no candidates for {filename} "
                f"(duration {duration:.1f}s) - falling back to anchor frames only."
            )
    elif category == "video_editor":
        warnings.append(
            f"{artist_id}: {filename} is {duration:.1f}s, below the {SCENE_MIN_VIDEO_DURATION}s "
            f"scene-detection floor - anchor frames only."
        )

    # --- Full audio track extraction for musician video (primary evidence there) ---
    if category == "musician":
        eid = id_alloc.next_id(artist_id)
        out_path = audio_dir / f"{eid}.wav"
        if duration <= MUSICIAN_VIDEO_FULL_AUDIO_MAX_SECONDS:
            ok, err = extract_audio_segment(src_path, 0.0, duration, out_path)
            rationale = (
                f"Musician video clip; full audio track extracted as primary evidence "
                f"({duration:.1f}s, at/under the {MUSICIAN_VIDEO_FULL_AUDIO_MAX_SECONDS:.0f}s full-inclusion threshold). "
                f"Video frames above are secondary visual context only."
            )
            locator = {"type": "audio_track", "start_seconds": 0.0, "end_seconds": round(duration, 3)}
        else:
            # Not exercised by current dataset, but kept for reproducibility on future data.
            ok, err = extract_audio_segment(src_path, 0.0, AUDIO_WINDOW_SECONDS, out_path)
            rationale = (
                f"Musician video clip exceeds {MUSICIAN_VIDEO_FULL_AUDIO_MAX_SECONDS:.0f}s; "
                f"sampled opening {AUDIO_WINDOW_SECONDS:.0f}s window instead of full track."
            )
            locator = {"type": "segment", "start_seconds": 0.0, "end_seconds": AUDIO_WINDOW_SECONDS}

        anomaly_notes = list(video_level_anomalies)
        status = "ok"
        if not ok:
            status = "extraction_failed"
            anomaly_notes.append(f"ffmpeg_extraction_error: {err}")
        else:
            silence_ratio = detect_silence_ratio(out_path, duration)
            if silence_ratio > SILENCE_ANOMALY_RATIO:
                anomaly_notes.append(f"content_anomaly:silence_ratio={silence_ratio:.2f}_exceeds_threshold")
                status = "flagged_anomaly"

        evidence_items.append({
            "evidence_id": eid,
            "artist_id": artist_id,
            "source_relative_path": src_rel,
            "display_label": display_label,
            "media_type": "audio",
            "locator": locator,
            "selection_method": "full_audio_track_from_video",
            "selection_rationale": rationale,
            "extracted_asset_path": str((audio_dir / f"{eid}.wav").relative_to(output_dir)) if ok else None,
            "status": status,
            "anomaly_notes": anomaly_notes,
            "counts_as_independent_evidence": True,
        })

    return evidence_items


# --------------------------------------------------------------------------
# Duplicate detection (all 120 files, all types, via SHA-256)
# --------------------------------------------------------------------------

def compute_hash_groups(artists_manifest, dataset_root, warnings):
    """Returns dict: sha256 -> sorted list of relative_path, for hashes shared
    by 2+ files. Also returns dict: relative_path -> sha256 for every file."""
    all_files = []
    for artist in artists_manifest:
        for m in artist["media_files"]:
            all_files.append(m["relative_path"])

    hash_of = {}
    for rel in all_files:
        full_path = dataset_root / rel
        if not full_path.exists():
            warnings.append(f"File listed in manifest but not found on disk: {rel}")
            continue
        hash_of[rel] = sha256_of_file(full_path)

    groups = {}
    for rel, h in hash_of.items():
        groups.setdefault(h, []).append(rel)

    duplicate_groups = {h: sorted(paths) for h, paths in groups.items() if len(paths) > 1}
    return duplicate_groups, hash_of


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate_evidence_manifest(evidence_manifest, dataset_root, output_dir):
    checks = {
        "unique_evidence_ids": {"passed": True, "details": []},
        "source_paths_exist": {"passed": True, "details": []},
        "timestamps_within_duration": {"passed": True, "details": []},
        "extracted_assets_exist": {"passed": True, "details": []},
        "duplicate_relationships_resolve": {"passed": True, "details": []},
        "output_outside_dataset_root": {"passed": True, "details": []},
    }

    all_ids = []
    all_evidence_by_source = {}  # source_relative_path -> list of evidence items (for duplicate resolution)
    duration_by_source = {}

    for artist in evidence_manifest["artists"]:
        for ev in artist["evidence"]:
            all_ids.append(ev["evidence_id"])
            all_evidence_by_source.setdefault(ev["source_relative_path"], []).append(ev)

    # 1. Unique evidence IDs
    seen = set()
    for eid in all_ids:
        if eid in seen:
            checks["unique_evidence_ids"]["passed"] = False
            checks["unique_evidence_ids"]["details"].append(f"Duplicate evidence_id: {eid}")
        seen.add(eid)

    # Build duration lookup from the original dataset manifest media records passed in
    for artist in evidence_manifest["artists"]:
        for rel, dur in artist.get("_source_durations", {}).items():
            duration_by_source[rel] = dur

    for artist in evidence_manifest["artists"]:
        for ev in artist["evidence"]:
            src = dataset_root / ev["source_relative_path"]

            # 2. Source paths exist
            if not src.exists():
                checks["source_paths_exist"]["passed"] = False
                checks["source_paths_exist"]["details"].append(f"{ev['evidence_id']}: missing {ev['source_relative_path']}")

            # 3. Timestamps within duration
            dur = duration_by_source.get(ev["source_relative_path"])
            loc = ev["locator"]
            if dur is not None:
                if loc["type"] == "frame":
                    if not (0.0 <= loc["timestamp_seconds"] <= dur + 0.5):
                        checks["timestamps_within_duration"]["passed"] = False
                        checks["timestamps_within_duration"]["details"].append(
                            f"{ev['evidence_id']}: timestamp {loc['timestamp_seconds']} outside duration {dur}"
                        )
                elif loc["type"] in ("segment", "audio_track"):
                    if not (0.0 <= loc["start_seconds"] <= dur + 0.5) or not (loc["end_seconds"] <= dur + 0.5):
                        checks["timestamps_within_duration"]["passed"] = False
                        checks["timestamps_within_duration"]["details"].append(
                            f"{ev['evidence_id']}: segment {loc} outside duration {dur}"
                        )

            # 4. Extracted assets exist (only for status ok/flagged_anomaly items that claim an asset)
            if ev.get("extracted_asset_path") and ev["status"] in ("ok", "flagged_anomaly"):
                asset_full = output_dir / ev["extracted_asset_path"]
                if not asset_full.exists():
                    checks["extracted_assets_exist"]["passed"] = False
                    checks["extracted_assets_exist"]["details"].append(
                        f"{ev['evidence_id']}: declared asset missing on disk: {ev['extracted_asset_path']}"
                    )

            # 5. Duplicate relationships resolve
            if ev["status"] == "duplicate":
                canon_path = ev.get("duplicate_of_source_relative_path")
                canon_items = all_evidence_by_source.get(canon_path, [])
                canon_ok = any(item["status"] != "duplicate" for item in canon_items)
                if not canon_path or not canon_ok:
                    checks["duplicate_relationships_resolve"]["passed"] = False
                    checks["duplicate_relationships_resolve"]["details"].append(
                        f"{ev['evidence_id']}: duplicate_of '{canon_path}' does not resolve to a canonical evidence item"
                    )

    # 6. No output written inside dataset root
    try:
        output_dir.resolve().relative_to(dataset_root.resolve())
        checks["output_outside_dataset_root"]["passed"] = False
        checks["output_outside_dataset_root"]["details"].append(
            f"output_dir {output_dir} resolves inside dataset_root {dataset_root}"
        )
    except ValueError:
        pass  # good

    return checks


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Stage 2: select and extract evidence (read-only against dataset).")
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path,
                         help="Path to Stage 1 dataset_manifest.json")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()

    if not dataset_root.exists():
        print(f"ERROR: dataset root does not exist: {dataset_root}", file=sys.stderr)
        sys.exit(1)
    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    try:
        output_dir.relative_to(dataset_root)
        print(f"ERROR: --output-dir ({output_dir}) is inside --dataset-root ({dataset_root}). Refusing to run.",
              file=sys.stderr)
        sys.exit(1)
    except ValueError:
        pass

    with open(args.manifest, "r", encoding="utf-8") as f:
        dataset_manifest = json.load(f)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence_assets").mkdir(parents=True, exist_ok=True)

    warnings = []
    id_alloc = EvidenceIdAllocator()

    print("Pass 1/2: computing SHA-256 for all media files (duplicate detection)...")
    duplicate_groups, hash_of = compute_hash_groups(dataset_manifest["artists"], dataset_root, warnings)
    if duplicate_groups:
        print(f"  Found {len(duplicate_groups)} duplicate group(s):")
        for h, paths in duplicate_groups.items():
            print(f"    hash {h[:12]}...: {paths}")
    else:
        print("  No exact duplicates found.")

    # Map: relative_path -> canonical relative_path (only present for duplicate members)
    canonical_of = {}
    for paths in duplicate_groups.values():
        canonical = paths[0]
        for p in paths[1:]:
            canonical_of[p] = canonical

    print("Pass 2/2: selecting and extracting evidence per artist...")
    evidence_manifest = {
        "generated_by": "scripts/select_evidence.py",
        "manual_edits": False,
        "dataset_root": str(dataset_root),
        "selection_thresholds": {
            "audio_full_include_max_seconds": AUDIO_FULL_INCLUDE_MAX_SECONDS,
            "audio_window_seconds": AUDIO_WINDOW_SECONDS,
            "audio_window_fractions": AUDIO_WINDOW_FRACTIONS,
            "audio_extract_sample_rate": AUDIO_EXTRACT_SAMPLE_RATE,
            "video_anchor_fractions": VIDEO_ANCHOR_FRACTIONS,
            "scene_min_video_duration": SCENE_MIN_VIDEO_DURATION,
            "scene_score_threshold": SCENE_SCORE_THRESHOLD,
            "scene_max_candidate_frames_per_video": SCENE_MAX_CANDIDATE_FRAMES,
            "per_artist_frame_soft_budget": PER_ARTIST_FRAME_SOFT_BUDGET,
            "musician_video_full_audio_max_seconds": MUSICIAN_VIDEO_FULL_AUDIO_MAX_SECONDS,
            "black_anomaly_ratio": BLACK_ANOMALY_RATIO,
            "silence_anomaly_ratio": SILENCE_ANOMALY_RATIO,
            "frame_stddev_blank_threshold": FRAME_STDDEV_BLANK_THRESHOLD,
        },
        "duplicate_groups": [
            {"sha256": h, "source_relative_paths": paths, "canonical": paths[0]}
            for h, paths in duplicate_groups.items()
        ],
        "warnings": warnings,
        "artists": [],
    }

    for artist in dataset_manifest["artists"]:
        artist_id = artist["artist_id"]
        category = artist["category"]
        print(f"  {artist_id} ({category})...")

        artist_evidence = []
        source_durations = {}

        for media in artist["media_files"]:
            rel = media["relative_path"]
            media_type = media["media_type"]
            if media.get("duration_seconds") is not None:
                source_durations[rel] = media["duration_seconds"]

            if media["status"] != "ok":
                # Stage 1 already flagged this file as unreadable/corrupt/etc.
                eid = id_alloc.next_id(artist_id)
                artist_evidence.append({
                    "evidence_id": eid,
                    "artist_id": artist_id,
                    "source_relative_path": rel,
                    "display_label": media["filename"],
                    "media_type": media_type,
                    "locator": {"type": "unavailable"},
                    "selection_method": "not_selected",
                    "selection_rationale": "Stage 1 inspection reported this file as not fully readable; "
                                            "treated as unknown/insufficient evidence, not processed further.",
                    "extracted_asset_path": None,
                    "status": "insufficient_evidence",
                    "anomaly_notes": [f"stage1_status:{media['status']}"],
                    "counts_as_independent_evidence": False,
                })
                continue

            if rel in canonical_of:
                # Duplicate - do not re-extract; single marker record only.
                eid = id_alloc.next_id(artist_id)
                artist_evidence.append({
                    "evidence_id": eid,
                    "artist_id": artist_id,
                    "source_relative_path": rel,
                    "display_label": media["filename"],
                    "media_type": media_type,
                    "locator": {"type": "duplicate"},
                    "selection_method": "duplicate_skip",
                    "selection_rationale": f"Identical SHA-256 hash to {canonical_of[rel]}; "
                                            f"not independently processed to avoid double-counting portfolio evidence.",
                    "extracted_asset_path": None,
                    "status": "duplicate",
                    "anomaly_notes": [],
                    "counts_as_independent_evidence": False,
                    "duplicate_of_source_relative_path": canonical_of[rel],
                })
                continue

            if media_type == "image":
                artist_evidence.extend(process_image(artist_id, media, dataset_root, output_dir, id_alloc, warnings))
            elif media_type == "audio":
                artist_evidence.extend(process_audio(artist_id, media, dataset_root, output_dir, id_alloc, warnings))
            elif media_type == "video":
                artist_evidence.extend(process_video(artist_id, category, media, dataset_root, output_dir, id_alloc, warnings))
            else:
                eid = id_alloc.next_id(artist_id)
                artist_evidence.append({
                    "evidence_id": eid,
                    "artist_id": artist_id,
                    "source_relative_path": rel,
                    "display_label": media["filename"],
                    "media_type": media_type,
                    "locator": {"type": "unavailable"},
                    "selection_method": "not_selected",
                    "selection_rationale": f"Unrecognized media_type '{media_type}' from Stage 1 manifest.",
                    "extracted_asset_path": None,
                    "status": "insufficient_evidence",
                    "anomaly_notes": [],
                    "counts_as_independent_evidence": False,
                })

        # Soft-budget check (informational only, logged not enforced retroactively)
        frame_count = sum(1 for e in artist_evidence if e["media_type"] == "video" and e["locator"].get("type") == "frame")
        if frame_count > PER_ARTIST_FRAME_SOFT_BUDGET:
            warnings.append(
                f"{artist_id}: {frame_count} frames selected, exceeding the soft budget of "
                f"{PER_ARTIST_FRAME_SOFT_BUDGET}. Retained as-is per 'do not manufacture evidence to hit a "
                f"budget' - the same principle means we also do not truncate genuinely distinct evidence."
            )

        evidence_manifest["artists"].append({
            "artist_id": artist_id,
            "category": category,
            "evidence": artist_evidence,
            "_source_durations": source_durations,  # used by validator; stripped before final write
        })

    # --- Validate ---
    print("Running validation checks...")
    validation = validate_evidence_manifest(evidence_manifest, dataset_root, output_dir)

    # Strip internal helper field before writing final manifest
    for artist in evidence_manifest["artists"]:
        artist.pop("_source_durations", None)
    evidence_manifest["validation"] = validation

    manifest_path = output_dir / "evidence_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(evidence_manifest, f, indent=2, ensure_ascii=False)
    print(f"Wrote: {manifest_path}")

    # --- Human-readable log ---
    log_lines = ["# Evidence Selection Log", ""]
    log_lines.append("Generated entirely by `scripts/select_evidence.py`. No manual edits.")
    log_lines.append("")
    log_lines.append("## Selection thresholds")
    for k, v in evidence_manifest["selection_thresholds"].items():
        log_lines.append(f"- `{k}`: {v}")
    log_lines.append("")

    if evidence_manifest["duplicate_groups"]:
        log_lines.append("## Duplicate groups (exact SHA-256 match)")
        for g in evidence_manifest["duplicate_groups"]:
            log_lines.append(f"- Canonical: `{g['canonical']}`")
            for p in g["source_relative_paths"]:
                if p != g["canonical"]:
                    log_lines.append(f"    - Duplicate (excluded from independent evidence count): `{p}`")
        log_lines.append("")

    log_lines.append("## Per-artist evidence summary")
    for artist in evidence_manifest["artists"]:
        ev = artist["evidence"]
        n_total = len(ev)
        n_independent = sum(1 for e in ev if e["counts_as_independent_evidence"])
        n_flagged = sum(1 for e in ev if e["status"] == "flagged_anomaly")
        n_failed = sum(1 for e in ev if e["status"] == "extraction_failed")
        n_dup = sum(1 for e in ev if e["status"] == "duplicate")
        n_insufficient = sum(1 for e in ev if e["status"] == "insufficient_evidence")
        log_lines.append(
            f"- **{artist['artist_id']}** ({artist['category']}): {n_total} evidence item(s) - "
            f"{n_independent} independent, {n_dup} duplicate, {n_flagged} flagged anomaly, "
            f"{n_failed} extraction failed, {n_insufficient} insufficient/unavailable"
        )
        for e in ev:
            if e["status"] not in ("ok",):
                log_lines.append(
                    f"    - ⚠️ `{e['evidence_id']}` ({e['source_relative_path']}) -> **{e['status']}**: "
                    f"{'; '.join(e['anomaly_notes']) if e['anomaly_notes'] else e['selection_rationale']}"
                )
    log_lines.append("")

    log_lines.append("## Validation results")
    for check, result in validation.items():
        status_icon = "✅" if result["passed"] else "❌"
        log_lines.append(f"- {status_icon} **{check}**: {'PASSED' if result['passed'] else 'FAILED'}")
        for d in result["details"]:
            log_lines.append(f"    - {d}")
    log_lines.append("")

    if evidence_manifest["warnings"]:
        log_lines.append("## Warnings")
        for w in evidence_manifest["warnings"]:
            log_lines.append(f"- {w}")
        log_lines.append("")

    log_lines.append("## Methodology notes")
    log_lines.append(
        "- Scene-change candidate frames are selected via ffmpeg's built-in single-pass scene scorer. "
        "This necessarily decodes the full video once to compute per-frame scores, but only the "
        "top-scoring candidate frames (up to the per-video cap) are ever saved to disk or passed "
        "downstream - the pipeline does not save or model-analyze every frame."
    )
    log_lines.append(
        "- `filename_pattern_anomaly` flags (stock-music-style naming, possible named-individual "
        "reference) are informational only. They do not reduce or otherwise affect any capability "
        "confidence in this stage, and must not be treated as proof of provenance, licensing, or identity "
        "in later stages."
    )
    log_lines.append(
        "- The per-artist frame soft budget (60) is never padded to reach; artists with fewer strong "
        "candidates simply have fewer frames."
    )
    log_lines.append(
        "- Files Stage 1 already marked non-`ok` are recorded here as `insufficient_evidence` and not "
        "processed further."
    )

    summary_path = output_dir / "evidence_selection_log.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"Wrote: {summary_path}")

    all_passed = all(r["passed"] for r in validation.values())
    print(f"\nDone. Validation: {'ALL PASSED' if all_passed else 'SOME CHECKS FAILED - see evidence_selection_log.md'}")


if __name__ == "__main__":
    main()
