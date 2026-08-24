#!/usr/bin/env python3
"""
Sekeron Stage 3 - Dataset Inspection Utility
==============================================

Recursively inspects the artist_profiles dataset and produces:
  - generated/dataset_manifest.json  (machine-readable)
  - generated/dataset_summary.md     (human-readable)

READ-ONLY GUARANTEE:
This script never writes, renames, deletes, moves, or otherwise mutates
anything under --dataset-root. It only opens files for reading (in 'rb'
or via PIL's Image.open, which does not modify source files) and calls
ffprobe (a read-only inspection tool - never ffmpeg with an output path
against the dataset). All output is written exclusively to --output-dir,
which must not be inside --dataset-root (the script enforces this).

No LLM calls are made in this stage. All metadata is extracted with
Pillow (images) and ffprobe (audio/video).

Usage:
    python3 scripts/inspect_dataset.py \
        --dataset-root "/path/to/Data set" \
        --output-dir generated

Requires: Python 3.9+, Pillow (see requirements.txt), and ffprobe on PATH
(part of the ffmpeg distribution - e.g. `brew install ffmpeg` on macOS).
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov"}
AUDIO_EXTS = {".mp3", ".wav"}
PROFILE_EXTS = {".docx", ".txt"}
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

CATEGORY_DIR_MAP = {
    "photographers": "photographer",
    "musicians": "musician",
    "video_editors": "video_editor",
}


def is_ignored(path: Path) -> bool:
    if path.name.lower() in IGNORED_NAMES:
        return True
    if path.name.startswith("."):
        return True
    return False


def parse_artist_id_and_name(folder_name: str):
    """Split 'P01_Aanya_Rao' -> ('P01', 'Aanya Rao'). Robust to odd naming
    (e.g. 'PO4_Drift' where letter O replaces digit 0) - we do not assume
    a strict ID pattern, we just split on the first underscore."""
    if "_" in folder_name:
        artist_id, rest = folder_name.split("_", 1)
        display_name = rest.replace("_", " ")
    else:
        artist_id = folder_name
        display_name = folder_name
    return artist_id, display_name


def run_ffprobe(path: Path) -> Optional[dict]:
    """Run ffprobe in read-only inspection mode and return parsed JSON, or
    None if ffprobe is unavailable or the file cannot be probed."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(path),
            ],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return {"__ffprobe_missing__": True}
    except subprocess.TimeoutExpired:
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def inspect_image(path: Path) -> dict:
    entry = {
        "media_type": "image",
        "status": "ok",
        "width": None,
        "height": None,
        "format": None,
        "error": None,
    }
    try:
        with Image.open(path) as img:
            img.verify()  # checks integrity without loading full pixel data
        # re-open after verify() (verify() invalidates the file handle for further use)
        with Image.open(path) as img:
            entry["width"], entry["height"] = img.size
            entry["format"] = img.format
    except Exception as e:
        entry["status"] = "corrupt_or_unreadable"
        entry["error"] = f"{type(e).__name__}: {e}"
    return entry


def inspect_video(path: Path) -> dict:
    entry = {
        "media_type": "video",
        "status": "ok",
        "duration_seconds": None,
        "width": None,
        "height": None,
        "fps": None,
        "codec": None,
        "error": None,
    }
    probe = run_ffprobe(path)
    if probe is None:
        entry["status"] = "corrupt_or_unreadable"
        entry["error"] = "ffprobe could not parse this file"
        return entry
    if probe.get("__ffprobe_missing__"):
        entry["status"] = "metadata_tool_missing"
        entry["error"] = "ffprobe not found on PATH"
        return entry

    fmt = probe.get("format", {})
    if fmt.get("duration"):
        try:
            entry["duration_seconds"] = round(float(fmt["duration"]), 3)
        except (TypeError, ValueError):
            pass

    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if video_streams:
        vs = video_streams[0]
        entry["width"] = vs.get("width")
        entry["height"] = vs.get("height")
        entry["codec"] = vs.get("codec_name")
        rate = vs.get("avg_frame_rate") or vs.get("r_frame_rate")
        if rate and rate != "0/0":
            try:
                num, den = rate.split("/")
                den = float(den)
                entry["fps"] = round(float(num) / den, 3) if den else None
            except (ValueError, ZeroDivisionError):
                pass
    else:
        # No video stream found at all - flag rather than silently pass
        entry["status"] = "no_video_stream_found"

    return entry


def inspect_audio(path: Path) -> dict:
    entry = {
        "media_type": "audio",
        "status": "ok",
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "codec": None,
        "error": None,
    }
    probe = run_ffprobe(path)
    if probe is None:
        entry["status"] = "corrupt_or_unreadable"
        entry["error"] = "ffprobe could not parse this file"
        return entry
    if probe.get("__ffprobe_missing__"):
        entry["status"] = "metadata_tool_missing"
        entry["error"] = "ffprobe not found on PATH"
        return entry

    fmt = probe.get("format", {})
    if fmt.get("duration"):
        try:
            entry["duration_seconds"] = round(float(fmt["duration"]), 3)
        except (TypeError, ValueError):
            pass

    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if audio_streams:
        aus = audio_streams[0]
        entry["sample_rate"] = int(aus["sample_rate"]) if aus.get("sample_rate") else None
        entry["channels"] = aus.get("channels")
        entry["codec"] = aus.get("codec_name")
    else:
        entry["status"] = "no_audio_stream_found"

    return entry


def classify_and_inspect(path: Path) -> dict:
    ext = path.suffix.lower()
    size_bytes = path.stat().st_size

    base = {
        "filename": path.name,
        "relative_path": None,  # filled by caller
        "size_bytes": size_bytes,
    }

    if size_bytes == 0:
        base.update({"media_type": "unknown", "status": "empty_file", "error": "0-byte file"})
        return base

    if ext in IMAGE_EXTS:
        base.update(inspect_image(path))
    elif ext in VIDEO_EXTS:
        base.update(inspect_video(path))
    elif ext in AUDIO_EXTS:
        base.update(inspect_audio(path))
    elif ext in PROFILE_EXTS:
        base.update({
            "media_type": "profile_document",
            "status": "ok",
            "error": None,
        })
    else:
        base.update({
            "media_type": "other_unclassified",
            "status": "unclassified_extension",
            "error": f"Unrecognized extension: {ext}",
        })

    return base


def inspect_dataset(dataset_root: Path):
    artists = []
    warnings = []

    profiles_root = dataset_root / "artist_profiles"
    if not profiles_root.exists():
        # Fall back to dataset_root itself in case the caller points
        # directly at artist_profiles/
        if dataset_root.name == "artist_profiles":
            profiles_root = dataset_root
        else:
            warnings.append(
                f"Expected 'artist_profiles' subdirectory under {dataset_root} - not found. "
                f"Scanning {dataset_root} directly instead."
            )
            profiles_root = dataset_root

    for category_dir in sorted(profiles_root.iterdir()):
        if not category_dir.is_dir() or is_ignored(category_dir):
            continue
        category = CATEGORY_DIR_MAP.get(category_dir.name, category_dir.name)
        if category_dir.name not in CATEGORY_DIR_MAP:
            warnings.append(
                f"Category folder '{category_dir.name}' not in expected set "
                f"{list(CATEGORY_DIR_MAP)} - recording as-is."
            )

        for artist_dir in sorted(category_dir.iterdir()):
            if not artist_dir.is_dir() or is_ignored(artist_dir):
                continue

            artist_id, display_name = parse_artist_id_and_name(artist_dir.name)

            profile_files = []
            media_files = []
            other_files = []

            for f in sorted(artist_dir.rglob("*")):
                if f.is_dir() or is_ignored(f):
                    continue
                rel = f.relative_to(dataset_root)
                record = classify_and_inspect(f)
                record["relative_path"] = str(rel)

                if record["media_type"] == "profile_document":
                    profile_files.append(record)
                elif record["media_type"] in ("image", "video", "audio"):
                    media_files.append(record)
                else:
                    other_files.append(record)

            artists.append({
                "artist_id": artist_id,
                "folder_name": artist_dir.name,
                "display_name": display_name,
                "category": category,
                "profile_files": profile_files,
                "media_files": media_files,
                "other_files": other_files,
                "profile_file_count": len(profile_files),
                "media_file_count": len(media_files),
            })

    return artists, warnings


def build_summary(artists, warnings, dataset_root: Path) -> str:
    lines = ["# Dataset Inspection Summary", ""]
    lines.append(f"**Dataset root:** `{dataset_root}`")
    lines.append(f"**Total artists found:** {len(artists)}")
    lines.append("")

    by_category = {}
    for a in artists:
        by_category.setdefault(a["category"], []).append(a)

    total_media = 0
    total_size = 0
    status_counts = {}

    for category, members in sorted(by_category.items()):
        lines.append(f"## {category} ({len(members)} artists)")
        for a in members:
            n_media = a["media_file_count"]
            n_profile = a["profile_file_count"]
            artist_size = sum(m["size_bytes"] for m in a["media_files"] + a["profile_files"] + a["other_files"])
            total_size += artist_size
            total_media += n_media
            lines.append(
                f"- **{a['artist_id']}** ({a['display_name']}) - "
                f"{n_media} media file(s), {n_profile} profile doc(s), "
                f"{artist_size / (1024*1024):.1f} MB"
            )
            for m in a["media_files"] + a["other_files"]:
                status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1
                if m["status"] != "ok":
                    lines.append(
                        f"    - ⚠️ `{m['relative_path']}` -> status: **{m['status']}** "
                        f"({m.get('error') or 'no further detail'})"
                    )
        lines.append("")

    lines.append("## Aggregate stats")
    lines.append(f"- Total media files inspected: {total_media}")
    lines.append(f"- Total inspected size: {total_size / (1024*1024):.1f} MB")
    lines.append("- File status breakdown:")
    for status, count in sorted(status_counts.items()):
        lines.append(f"    - {status}: {count}")
    lines.append("")

    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Notes")
    lines.append(
        "- This summary and the accompanying `dataset_manifest.json` were generated "
        "entirely by `scripts/inspect_dataset.py` with no manual edits."
    )
    lines.append(
        "- Files with status other than `ok` (corrupt, unreadable, missing streams, "
        "0-byte, or unclassified) are flagged above and must be treated as "
        "`unknown / insufficient evidence` downstream - never silently skipped."
    )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Inspect the Sekeron Stage 3 artist dataset (read-only).")
    parser.add_argument("--dataset-root", required=True, type=Path,
                         help="Path to the 'Data set' directory (containing artist_profiles/).")
    parser.add_argument("--output-dir", required=True, type=Path,
                         help="Directory to write generated manifest/summary into. Must not be inside dataset-root.")
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    output_dir = args.output_dir.resolve()

    if not dataset_root.exists():
        print(f"ERROR: dataset root does not exist: {dataset_root}", file=sys.stderr)
        sys.exit(1)

    # Safety guard: refuse to write output inside the dataset root.
    try:
        output_dir.relative_to(dataset_root)
        print(
            f"ERROR: --output-dir ({output_dir}) is inside --dataset-root ({dataset_root}). "
            f"Refusing to write generated output inside the protected dataset.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError:
        pass  # good - output_dir is NOT inside dataset_root

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Inspecting dataset at: {dataset_root}")
    artists, warnings = inspect_dataset(dataset_root)

    manifest = {
        "dataset_root": str(dataset_root),
        "artist_count": len(artists),
        "generated_by": "scripts/inspect_dataset.py",
        "manual_edits": False,
        "warnings": warnings,
        "artists": artists,
    }

    manifest_path = output_dir / "dataset_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Wrote manifest: {manifest_path}")

    summary_md = build_summary(artists, warnings, dataset_root)
    summary_path = output_dir / "dataset_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_md)
    print(f"Wrote summary: {summary_path}")

    print(f"\nDone. {len(artists)} artists inspected.")


if __name__ == "__main__":
    main()
