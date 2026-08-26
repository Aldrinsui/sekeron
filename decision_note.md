# Sekeron Stage 3 — Decision Note

## Decision supported

The system supports an initial, evidence-led decision about which artists are plausible matches for an incomplete hirer brief. It first separates demonstrated capabilities from unsupported profile claims, then connects relevant demonstrated dimensions to hirer requirements using deterministic scoring. Follow-up information is parsed again and the ranking is recomputed rather than manually adjusted.

## First-version scope

- Build capability records for 15 artists across musicians, photographers and video editors.
- Use supplied profile text and selected portfolio evidence only.
- Parse four sparse hirer briefs and one follow-up update.
- Separate capability requirements from operational constraints.
- Rank artists within the matching category using deterministic confidence-weighted scoring.
- Return the top two initial matches, with reasons, trade-offs, assumptions, uncertainty and up to two questions that could improve the match.
- Recompute the recommendation when the follow-up changes the requirement.

## Category-specific dimensions

**Musicians:** genre/style signal, performance format, live-vs-studio context, vocal/instrumental role, audio arrangement characteristics, instrumental/technical signals.

**Photographers:** subject/domain, composition/framing, lighting treatment, color/tone treatment, environment context, technical control indicators, shooting context/style.

**Video editors:** pacing/rhythm, shot composition/framing, visual sequencing, color treatment, content/format context, motion graphics/overlay evidence, audio/dialogue handling.

The vocabulary is centralized in `scripts/capability_vocabulary.py`.

## Non-goals

No frontend, web scraping, model training, deployment, identity inference or trust/reputation scoring. Portfolio media is not used to infer reliability, punctuality, popularity, character or professionalism.

## Assumptions and risks

- Portfolio evidence is incomplete, so absence of evidence is treated as unknown rather than incapability.
- Confidence reflects evidence strength; insufficient evidence receives zero points and no negative penalty.
- Operational constraints such as budget, date and equipment are surfaced for human verification but are not algorithmically scored.
- Hirer briefs can contain ambiguity or unknowns; recommendations are therefore provisional.
- Gemini is used for structured brief parsing and artist intelligence; ranking remains deterministic and reproducible.
- Additional observed capabilities may be recorded when directly supported by supplied media, but they remain supplementary to the standard category dimensions.