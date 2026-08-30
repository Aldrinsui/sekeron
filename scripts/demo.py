import json


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


artists = load_jsonl("generated/artist_intelligence.jsonl")
recommendations = load_json("generated/recommendations.json")
updated = load_json("generated/updated_recommendation.json")


# ======================================================================
# SEKERON STAGE 3 — EVIDENCE-LED ARTIST INTELLIGENCE & RECOMMENDATION
# ======================================================================

print("=" * 70)
print("SEKERON STAGE 3 — EVIDENCE-LED ARTIST INTELLIGENCE & RECOMMENDATION")
print("15 artists | 4 hirer briefs | 1 follow-up | deterministic ranking")
print("=" * 70)


# ======================================================================
# 1. M04 KILLRUSH — PERFORMANCE FORMAT EVIDENCE
# ======================================================================

m04 = next(a for a in artists if a["artist_id"] == "M04")

capability = next(
    c
    for c in m04["demonstrated_capabilities"]
    if c["capability"] == "performance_format"
)

print("\n" + "=" * 70)
print("1. M04 KILLRUSH — PERFORMANCE FORMAT EVIDENCE")
print("=" * 70)

print("Artist:", m04["display_name"])
print("Capability:", capability["capability"])
print("Status:", capability["status"])
print("Confidence:", capability["confidence"])
print("Observation:", capability["observation"])

print("\nEvidence references:")
for ref in capability["evidence_references"]:
    print(
        f"  {ref['evidence_id']} | "
        f"{ref.get('note', '')}"
    )


# ======================================================================
# 2. H081 — INITIAL ARTIST RECOMMENDATION
# ======================================================================

h081 = next(
    r for r in recommendations["recommendations"]
    if r["hirer_id"] == "H081"
)

print("\n" + "=" * 70)
print("2. H081 — INITIAL ARTIST RECOMMENDATION")
print("=" * 70)

print("Top two:")
for artist in h081["ranked_artists"][:2]:
    print(
        f"  #{artist['rank']} "
        f"{artist['artist_id']} — "
        f"{artist['display_name']} "
        f"(score={artist['total_score']:.1f})"
    )

print("\nWhy:")
for reason in h081["reasons"][:3]:
    print("  -", reason[:220])


# ======================================================================
# 3. H081 — FOLLOW-UP REQUIREMENT CHANGE & RE-SCORING
# ======================================================================

print("\n" + "=" * 70)
print("3. H081 — FOLLOW-UP REQUIREMENT CHANGE & RE-SCORING")
print("=" * 70)

print("Updated top two:")
for artist in updated["ranked_artists"][:2]:
    print(
        f"  #{artist['rank']} "
        f"{artist['artist_id']} — "
        f"{artist['display_name']} "
        f"(score={artist['total_score']:.1f})"
    )

summary = updated["change_summary"]

print("\nScore transition:")
print("  Before:", summary["old_top_two_scores"])
print("  After: ", summary["new_top_two_scores"])
print("  Old gap:", summary["old_score_gap"])
print("  New gap:", summary["new_score_gap"])
print("  Ordinal rank flip:", summary["is_genuine_rerank"])
print("  Score gap changed:", summary["score_gap_changed"])

print("\nInterpretation:")
print(" ", summary["notes"])


# ======================================================================
# 4. M01 — ANOMALOUS AUDIO & CONFIDENCE LIMIT
# ======================================================================

m01 = next(a for a in artists if a["artist_id"] == "M01")

print("\n" + "=" * 70)
print("4. M01 — ANOMALOUS AUDIO & CONFIDENCE LIMIT")
print("=" * 70)

for cap in m01["demonstrated_capabilities"]:
    if cap["capability"] not in {
        "genre_style_signal",
        "audio_arrangement_characteristics",
    }:
        continue

    print("\nCapability:", cap["capability"])
    print("Confidence:", cap["confidence"])
    print(
        "Evidence:",
        [x["evidence_id"] for x in cap["evidence_references"]]
    )

print("\nEvidence-quality signal:")
evidence_manifest = load_json("generated/evidence_manifest.json")
m01_manifest = next(
    a
    for a in evidence_manifest["artists"]
    if a["artist_id"] == "M01"
)

target_ids = {
    "M01-E004",
    "M01-E008",
    "M01-E012",
    "M01-E016",
}

for evidence in m01_manifest["evidence"]:
    if evidence["evidence_id"] in target_ids:
        print(
            f"  {evidence['evidence_id']}: "
            f"{evidence.get('anomaly_notes', [])}"
        )

print("\nResult: anomalous evidence limits confidence rather than")
print("        being treated as proof of incapability.")