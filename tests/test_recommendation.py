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


def test_multi_dimension_requirement_does_not_inflate_score():
    """Regression test for a real bug found in audit (2026-08-25): a
    requirement mapped to N dimensions must NOT contribute up to N times
    the points of an equivalent single-dimension requirement. Contribution
    is averaged across mapped_dimensions, not summed."""
    artist = {
        "artist_id": "M99",
        "category": "musician",
        "demonstrated_capabilities": [
            {"capability": "performance_format", "status": "demonstrated", "confidence": "high"},
            {"capability": "live_vs_studio_context", "status": "demonstrated", "confidence": "high"},
            {"capability": "audio_arrangement_characteristics", "status": "demonstrated", "confidence": "high"},
            {"capability": "genre_style_signal", "status": "demonstrated", "confidence": "high"},
        ],
    }

    single_dim_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {"requirement_text": "R", "mapped_dimensions": ["genre_style_signal"], "importance": "must_have"}
        ],
    }
    multi_dim_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {
                "requirement_text": "R",
                "mapped_dimensions": ["performance_format", "live_vs_studio_context", "audio_arrangement_characteristics"],
                "importance": "must_have",
            }
        ],
    }

    single_result = score_artist(single_dim_brief, artist)
    multi_result = score_artist(multi_dim_brief, artist)

    # Both requirements are must_have, all cited dimensions are demonstrated+high
    # for this artist. A 3-dimension requirement must contribute the SAME
    # maximum as a 1-dimension requirement (3.0 = high weight * must_have
    # multiplier), not 3x that (9.0), which was the bug.
    assert single_result["total_score"] == 3.0
    assert multi_result["total_score"] == 3.0
    assert multi_result["total_score"] == single_result["total_score"]

    # The full per-requirement audit trail must be visible and non-lossy.
    rb = multi_result["requirement_breakdown"][0]
    assert rb["mapped_dimensions"] == ["performance_format", "live_vs_studio_context", "audio_arrangement_characteristics"]
    assert rb["requirement_contribution"] == 3.0
    assert set(rb["per_dimension"].keys()) == {"performance_format", "live_vs_studio_context", "audio_arrangement_characteristics"}


def test_score_breakdown_does_not_silently_overwrite_shared_dimension():
    """Regression test for a related bug: if two DIFFERENT requirements map
    to the same dimension, the flat score_breakdown dict can only show one
    entry per dimension key (a real, acknowledged limitation of that flat
    shape) - but requirement_breakdown must show BOTH requirements' full
    contribution, never silently dropping one."""
    artist = {
        "artist_id": "M99",
        "category": "musician",
        "demonstrated_capabilities": [
            {"capability": "performance_format", "status": "demonstrated", "confidence": "medium"},
        ],
    }
    parsed_brief = {
        "artist_category": "musician",
        "capability_requirements": [
            {"requirement_text": "R1", "mapped_dimensions": ["performance_format"], "importance": "must_have"},
            {"requirement_text": "R2", "mapped_dimensions": ["performance_format"], "importance": "nice_to_have"},
        ],
    }
    result = score_artist(parsed_brief, artist)

    # R1: medium(2) * must_have(1.0) = 2.0 ; R2: medium(2) * nice_to_have(0.5) = 1.0
    assert result["total_score"] == 3.0
    assert len(result["requirement_breakdown"]) == 2
    assert result["requirement_breakdown"][0]["requirement_contribution"] == 2.0
    assert result["requirement_breakdown"][1]["requirement_contribution"] == 1.0


def test_capability_vocabulary_is_single_source_of_truth():
    """Regression test for the actual bug found in audit (2026-08-25):
    generate_artist_intelligence.py had its own stale, locally-duplicated
    copy of CATEGORY_DIMENSIONS instead of importing capability_vocabulary.py,
    silently defeating the module's whole single-source-of-truth purpose.
    This test fails loudly if that ever regresses, in either file."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import capability_vocabulary as cv
    import generate_artist_intelligence as gai
    importlib.reload(gai)

    assert gai.CATEGORY_DIMENSIONS is cv.CATEGORY_DIMENSIONS, (
        "generate_artist_intelligence.py must import CATEGORY_DIMENSIONS from "
        "capability_vocabulary.py, not define its own copy."
    )
    assert gai.STATUS_LEVELS == cv.STATUS_LEVELS
    assert "conflicting_evidence" not in gai.STATUS_LEVELS, (
        "status must remain evidence-derived only (demonstrated/insufficient_evidence); "
        "profile conflicts are surfaced via the separate profile_conflict boolean flag, "
        "never by overwriting status."
    )