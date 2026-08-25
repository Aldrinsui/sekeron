import pytest
import sys
import json
import subprocess
from pathlib import Path

# Add scripts to path so we can import parse_hirer_brief and recommendation_scoring
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from parse_hirer_brief import validate_parsed_brief, dry_run_stub_parse
from recommendation_scoring import score_artist, rank_artists


def test_validation_rejects_invalid_mapped_dimension():
    parsed = {
        "hirer_id": "H081",
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Need good music",
                "mapped_dimensions": ["genre_style_signal", "invalid_dimension_key"],
                "importance": "must_have"
            }
        ],
        "operational_constraints": []
    }
    
    with pytest.raises(ValueError, match="Invalid mapped_dimension 'invalid_dimension_key' for category 'musician'"):
        validate_parsed_brief(parsed, "test_brief.txt")


def test_validation_rejects_invalid_operational_constraint():
    parsed = {
        "hirer_id": "H081",
        "artist_category": "musician",
        "capability_requirements": [],
        "operational_constraints": [
            {
                "category": "budget",
                "detail": "10k",
                "hard_limit": True
            },
            {
                "category": "invalid_constraint_key",
                "detail": "Some detail",
                "hard_limit": False
            }
        ]
    }
    
    with pytest.raises(ValueError, match="Invalid operational constraint category 'invalid_constraint_key'"):
        validate_parsed_brief(parsed, "test_brief.txt")


def test_scoring_weights_and_importance():
    parsed_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Req 1",
                "mapped_dimensions": ["vocal_or_instrumental_role"],
                "importance": "must_have"
            },
            {
                "requirement_text": "Req 2",
                "mapped_dimensions": ["genre_style_signal"],
                "importance": "nice_to_have"
            }
        ]
    }
    
    artist_high_low = {
        "artist_id": "M01",
        "category": "musician",
        "demonstrated_capabilities": [
            {"capability": "vocal_or_instrumental_role", "status": "demonstrated", "confidence": "high"},
            {"capability": "genre_style_signal", "status": "demonstrated", "confidence": "low"}
        ]
    }
    
    # Must have + high = 3.0
    # Nice to have + low = 1 * 0.5 = 0.5
    # Total = 3.5
    res = score_artist(parsed_brief, artist_high_low)
    assert res["total_score"] == 3.5
    assert res["score_breakdown"]["vocal_or_instrumental_role"]["points"] == 3.0
    assert res["score_breakdown"]["genre_style_signal"]["points"] == 0.5


def test_scoring_insufficient_evidence_no_penalty():
    parsed_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Req 1",
                "mapped_dimensions": ["vocal_or_instrumental_role"],
                "importance": "must_have"
            }
        ]
    }
    
    artist_insufficient = {
        "artist_id": "M01",
        "category": "musician",
        "demonstrated_capabilities": [
            {"capability": "vocal_or_instrumental_role", "status": "insufficient_evidence", "confidence": "insufficient"}
        ]
    }
    
    res = score_artist(parsed_brief, artist_insufficient)
    # Insufficient evidence should result in 0, not a negative penalty
    assert res["total_score"] == 0.0


def test_tie_breaking_alphabetical():
    parsed_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Req 1",
                "mapped_dimensions": ["vocal_or_instrumental_role"],
                "importance": "must_have"
            }
        ]
    }
    
    # Three artists with exactly the same capabilities
    caps = [{"capability": "vocal_or_instrumental_role", "status": "demonstrated", "confidence": "medium"}]
    artists = [
        {"artist_id": "M03", "category": "musician", "demonstrated_capabilities": caps},
        {"artist_id": "M01", "category": "musician", "demonstrated_capabilities": caps},
        {"artist_id": "M02", "category": "musician", "demonstrated_capabilities": caps},
    ]
    
    ranked = rank_artists(parsed_brief, artists)
    
    # Check that they all have score 2.0 but are ordered alphabetically
    assert ranked[0]["total_score"] == 2.0
    assert ranked[0]["artist_id"] == "M01"
    assert ranked[1]["artist_id"] == "M02"
    assert ranked[2]["artist_id"] == "M03"
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2
    assert ranked[2]["rank"] == 3


def test_operational_constraints_excluded_from_scoring():
    parsed_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Req 1",
                "mapped_dimensions": ["vocal_or_instrumental_role"],
                "importance": "must_have"
            }
        ],
        "operational_constraints": [
            {"category": "budget", "detail": "very low budget", "hard_limit": True}
        ]
    }
    
    artist = {
        "artist_id": "M01",
        "category": "musician",
        "demonstrated_capabilities": [
            {"capability": "vocal_or_instrumental_role", "status": "demonstrated", "confidence": "low"}
        ]
    }
    
    # Scoring should just be based on the capability (low * 1.0 = 1.0)
    res = score_artist(parsed_brief, artist)
    assert res["total_score"] == 1.0
    
    ranked = rank_artists(parsed_brief, [artist])
    # The operational constraint is passed verbatim to notes, but doesn't affect score
    notes = ranked[0]["operational_constraint_notes"]
    assert len(notes) == 1
    assert "budget: very low budget [HARD LIMIT] — verify with artist" in notes[0]


def test_cafe_followup_requirement_replacement():
    original = dry_run_stub_parse("live music next friday for our cafe, background music", "01_cafe_music_whatsapp.txt")
    followup = dry_run_stub_parse("change of plan, headline set", "01_cafe_music_update.txt")
    
    # Verify original has background music / performance_format as must_have
    orig_reqs = original["capability_requirements"]
    has_background = any("performance_format" in r["mapped_dimensions"] and "acoustic" in r["requirement_text"] for r in orig_reqs)
    
    # Verify followup has headline set as must_have
    followup_reqs = followup["capability_requirements"]
    has_headline = any("performance_format" in r["mapped_dimensions"] and "headline set" in r["requirement_text"] for r in followup_reqs)
    
    assert has_background is True
    assert has_headline is True


def test_full_pipeline_and_update(tmp_path):
    root_dir = Path(__file__).resolve().parent.parent
    
    # 1. Run generate_recommendations.py in dry-run mode
    cmd1 = [
        sys.executable, str(root_dir / "scripts" / "generate_recommendations.py"),
        "--briefs-dir", str(root_dir / "briefs"),
        "--intelligence", str(root_dir / "generated" / "artist_intelligence.jsonl"),
        "--output-dir", str(tmp_path),
        "--dry-run"
    ]
    res1 = subprocess.run(cmd1, capture_output=True, text=True)
    assert res1.returncode == 0, f"generate_recommendations failed: {res1.stderr}"
    
    recs_file = tmp_path / "recommendations.json"
    assert recs_file.exists()
    
    with open(recs_file) as f:
        recs = json.load(f)
    assert len(recs["recommendations"]) == 4  # Should process the 4 original briefs (skips update)
    
    # 2. Run update_recommendation.py in dry-run mode
    cmd2 = [
        sys.executable, str(root_dir / "scripts" / "update_recommendation.py"),
        "--original", str(recs_file),
        "--update-brief", str(root_dir / "briefs" / "01_cafe_music_update.txt"),
        "--hirer-id", "H081",
        "--intelligence", str(root_dir / "generated" / "artist_intelligence.jsonl"),
        "--output-dir", str(tmp_path),
        "--dry-run"
    ]
    res2 = subprocess.run(cmd2, capture_output=True, text=True)
    assert res2.returncode == 0, f"update_recommendation failed: {res2.stderr}"
    
    update_file = tmp_path / "updated_recommendation.json"
    assert update_file.exists()
    
    with open(update_file) as f:
        update = json.load(f)
        
    assert update["hirer_id"] == "H081"
    assert update["artist_category"] == "musician"
    assert "change_summary" in update

    # 3. Verify top-two limit on recommendations.json and updated_recommendation.json
    for rec in recs["recommendations"]:
        assert len(rec["ranked_artists"]) <= 2, f"Brief {rec['hirer_id']} returned more than 2 artists"
        assert len(rec["ranked_artists"]) == 2
        # Check required recommendation fields
        assert "reasons" in rec
        assert "trade_offs" in rec
        assert "assumptions" in rec
        assert "uncertainty" in rec
        assert "improve_your_matches" in rec
        
        # Check refinement questions limit & structure
        improve = rec["improve_your_matches"]
        questions = improve.get("refinement_questions", [])
        assert len(questions) <= 2
        assert len(questions) > 0
        for q in questions:
            assert "question" in q and q["question"]
            assert "expected_impact" in q and q["expected_impact"]

        # Check artist-level contextual content
        for artist in rec["ranked_artists"]:
            assert "reasons" in artist and len(artist["reasons"]) > 0
            assert "trade_offs" in artist
            assert "assumptions" in artist
            assert "uncertainty" in artist

    # Check updated recommendation top two & contextual fields
    assert len(update["ranked_artists"]) <= 2
    assert len(update["ranked_artists"]) == 2
    assert "improve_your_matches" in update
    assert len(update["improve_your_matches"]["refinement_questions"]) <= 2
    for q in update["improve_your_matches"]["refinement_questions"]:
        assert "question" in q and q["question"]
        assert "expected_impact" in q and q["expected_impact"]


def test_contextual_fields_and_refinement_questions_direct():
    from recommendation_scoring import (
        generate_artist_context,
        generate_refinement_questions,
        build_improve_your_matches,
    )
    parsed_brief = {
        "hirer_id": "H081",
        "source_file": "01_cafe_music_whatsapp.txt",
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "Acoustic background music",
                "mapped_dimensions": ["genre_style_signal"],
                "importance": "must_have",
            }
        ],
        "operational_constraints": [
            {
                "category": "budget",
                "detail": "around 7k-9k",
                "hard_limit": True,
            }
        ],
    }

    artist_rec = {
        "artist_id": "M01",
        "category": "musician",
        "demonstrated_capabilities": [
            {
                "capability": "genre_style_signal",
                "status": "demonstrated",
                "confidence": "high",
                "observation": "Demonstrated acoustic guitar and vocal style",
            }
        ],
    }

    ctx = generate_artist_context(parsed_brief, artist_rec, {"total_score": 3.0})
    assert len(ctx["reasons"]) > 0
    assert any("genre_style_signal" in r for r in ctx["reasons"])
    assert len(ctx["assumptions"]) > 0
    assert any("budget" in a for a in ctx["assumptions"])
    assert len(ctx["uncertainty"]) > 0

    # Test refinement questions strictly <= 2 and expected_impact exists
    questions = generate_refinement_questions(parsed_brief)
    assert 0 < len(questions) <= 2
    for q in questions:
        assert "question" in q and len(q["question"]) > 5
        assert "expected_impact" in q and len(q["expected_impact"]) > 5

    improve = build_improve_your_matches(parsed_brief)
    assert improve["section_title"] == "Improve your matches"
    assert len(improve["refinement_questions"]) <= 2

