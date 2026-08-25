#!/usr/bin/env python3
"""
Sekeron Stage 4 - Update Recommendation
==========================================

Handles a follow-up brief (like the cafe music update) by:
1. Parsing the follow-up brief
2. Finding the original recommendation for that hirer
3. Re-scoring artists based on the NEW parsed requirements
4. Emitting updated_recommendation.json

Usage:
    python3 scripts/update_recommendation.py \\
        --original generated/recommendations.json \\
        --update-brief briefs/01_cafe_music_update.txt \\
        --hirer-id H081 \\
        --intelligence generated/artist_intelligence.jsonl \\
        --output-dir generated \\
        --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add current directory to path to import local modules
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_hirer_brief import parse_brief
from recommendation_scoring import rank_artists, build_improve_your_matches

def main():
    parser = argparse.ArgumentParser(description="Update recommendation based on follow-up brief.")
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--update-brief", required=True, type=Path)
    parser.add_argument("--hirer-id", required=True, type=str)
    parser.add_argument("--intelligence", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: GEMINI_API_KEY environment variable is not set. Refusing to run without it.", file=sys.stderr)
        sys.exit(1)

    if not args.original.exists():
        print(f"ERROR: --original file does not exist: {args.original}", file=sys.stderr)
        sys.exit(1)
        
    if not args.update_brief.exists():
        print(f"ERROR: --update-brief file does not exist: {args.update_brief}", file=sys.stderr)
        sys.exit(1)
        
    if not args.intelligence.exists():
        print(f"ERROR: --intelligence file does not exist: {args.intelligence}", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load original recommendations
    with open(args.original, "r", encoding="utf-8") as f:
        orig_data = json.load(f)
        
    # Find the target original recommendation
    orig_rec = None
    for rec in orig_data.get("recommendations", []):
        if rec.get("hirer_id") == args.hirer_id:
            orig_rec = rec
            break
            
    if not orig_rec:
        print(f"ERROR: Hirer ID {args.hirer_id} not found in {args.original}", file=sys.stderr)
        sys.exit(1)

    # Load all artist intelligence records
    all_artists = []
    with open(args.intelligence, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            all_artists.append(json.loads(line))

    print(f"Processing follow-up brief: {args.update_brief.name}")
    with open(args.update_brief, "r", encoding="utf-8") as f:
        brief_text = f.read()

    # The parse_brief logic is designed to fully replace requirements if it's the follow-up brief
    parsed_update, warnings = parse_brief(brief_text, args.update_brief.name, api_key=api_key, dry_run=args.dry_run)
    
    # Check that artist_category is preserved
    parsed_update["artist_category"] = orig_rec["artist_category"]
    
    ranked_artists = rank_artists(parsed_update, all_artists)[:2]
    top_two_artists = ranked_artists[:2]

    # Build change summary comparing old ranking and new ranking
    old_ranks = {a["artist_id"]: a["rank"] for a in orig_rec.get("ranked_artists", [])}
    new_ranks = {a["artist_id"]: a["rank"] for a in ranked_artists}
    
    rank_changes = {}
    for artist_id, new_rank in new_ranks.items():
        old_rank = old_ranks.get(artist_id)
        if old_rank is not None and old_rank != new_rank:
            rank_changes[artist_id] = f"Moved from {old_rank} to {new_rank}"
        elif old_rank is not None:
            rank_changes[artist_id] = "Unchanged"
        else:
            rank_changes[artist_id] = f"New in top rankings (rank {new_rank})"
            
    change_summary = {
        "original_requirements_count": len(orig_rec.get("parsed_requirements", {}).get("capability_requirements", [])),
        "updated_requirements_count": len(parsed_update.get("capability_requirements", [])),
        "ranking_shifts": rank_changes,
        "is_genuine_rerank": any(old != new for old, new in zip(
            [a["artist_id"] for a in orig_rec.get("ranked_artists", [])],
            [a["artist_id"] for a in top_two_artists]
        ))
    }
    
    if not change_summary["is_genuine_rerank"]:
        change_summary["notes"] = "Ranking remained identical. This means artists scored equally relatively under both the old and new criteria."

    improve_matches = build_improve_your_matches(parsed_update)

    rec_reasons = []
    rec_trade_offs = []
    rec_assumptions = []
    rec_uncertainties = []
    for a in top_two_artists:
        rec_reasons.extend(a.get("reasons", []))
        rec_trade_offs.extend(a.get("trade_offs", []))
        rec_assumptions.extend(a.get("assumptions", []))
        rec_uncertainties.extend(a.get("uncertainty", []))

    out_data = {
        "generated_by": "scripts/update_recommendation.py",
        "hirer_id": args.hirer_id,
        "original_source": orig_rec.get("source_file"),
        "update_source": args.update_brief.name,
        "artist_category": parsed_update["artist_category"],
        "change_summary": change_summary,
        "updated_requirements": parsed_update,
        "ranked_artists": top_two_artists,
        "reasons": rec_reasons,
        "trade_offs": list(dict.fromkeys(rec_trade_offs)),
        "assumptions": list(dict.fromkeys(rec_assumptions)),
        "uncertainty": list(dict.fromkeys(rec_uncertainties)),
        "improve_your_matches": improve_matches,
        "refinement_questions": improve_matches["refinement_questions"],
        "warnings": warnings
    }
    
    out_path = args.output_dir / "updated_recommendation.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)
        
    print(f"Wrote: {out_path}")
    if warnings:
        print(f"Warnings: {len(warnings)}")

if __name__ == "__main__":
    main()
