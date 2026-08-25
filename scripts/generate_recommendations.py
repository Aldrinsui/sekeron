#!/usr/bin/env python3
"""
Sekeron Stage 4 - Generate Recommendations
===========================================

Orchestrates the recommendation pipeline:
1. Parse all hirer briefs in the input directory (via Gemini or dry-run stub)
2. Score all eligible artists against each brief deterministically
3. Output a combined recommendations.json file with ranked results

Usage:
    python3 scripts/generate_recommendations.py \\
        --briefs-dir briefs/ \\
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
    parser = argparse.ArgumentParser(description="Generate recommendations for hirer briefs.")
    parser.add_argument("--briefs-dir", required=True, type=Path)
    parser.add_argument("--intelligence", required=True, type=Path)
    parser.add_argument("--profiles", type=Path, help="Unused, kept for backwards compatibility.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: GEMINI_API_KEY environment variable is not set. Refusing to run without it.", file=sys.stderr)
        sys.exit(1)

    if not args.briefs_dir.exists():
        print(f"ERROR: --briefs-dir does not exist: {args.briefs_dir}", file=sys.stderr)
        sys.exit(1)
        
    if not args.intelligence.exists():
        print(f"ERROR: --intelligence file does not exist: {args.intelligence}", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load all artist intelligence records
    all_artists = []
    with open(args.intelligence, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            all_artists.append(json.loads(line))

    # Read all briefs
    brief_files = sorted([f for f in args.briefs_dir.iterdir() if f.is_file() and not f.name.startswith(".")])
    
    recommendations = []
    global_warnings = []
    
    for brief_path in brief_files:
        # Skip follow-up briefs in the initial generation
        if "update" in brief_path.name.lower():
            continue
            
        print(f"Processing brief: {brief_path.name}")
        with open(brief_path, "r", encoding="utf-8") as f:
            brief_text = f.read()

        parsed, warnings = parse_brief(brief_text, brief_path.name, api_key=api_key, dry_run=args.dry_run)
        if warnings:
            global_warnings.extend(warnings)
            
        ranked_artists = rank_artists(parsed, all_artists)[:2]
        top_two_artists = ranked_artists[:2]

        improve_matches = build_improve_your_matches(parsed)

        # Aggregate contextual fields across top recommendations
        rec_reasons = []
        rec_trade_offs = []
        rec_assumptions = []
        rec_uncertainties = []
        for a in top_two_artists:
            rec_reasons.extend(a.get("reasons", []))
            rec_trade_offs.extend(a.get("trade_offs", []))
            rec_assumptions.extend(a.get("assumptions", []))
            rec_uncertainties.extend(a.get("uncertainty", []))

        recommendations.append({
            "hirer_id": parsed["hirer_id"],
            "source_file": brief_path.name,
            "artist_category": parsed["artist_category"],
            "parsed_requirements": parsed,
            "ranked_artists": top_two_artists,
            "reasons": rec_reasons,
            "trade_offs": list(dict.fromkeys(rec_trade_offs)),
            "assumptions": list(dict.fromkeys(rec_assumptions)),
            "uncertainty": list(dict.fromkeys(rec_uncertainties)),
            "improve_your_matches": improve_matches,
            "refinement_questions": improve_matches["refinement_questions"],
        })
        
    out_data = {
        "generated_by": "scripts/generate_recommendations.py",
        "recommendations": recommendations,
        "warnings": global_warnings
    }
    
    out_path = args.output_dir / "recommendations.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)
        
    print(f"Wrote: {out_path} ({len(recommendations)} recommendations generated)")
    if global_warnings:
        print(f"Warnings: {len(global_warnings)}")

if __name__ == "__main__":
    main()
