📄 Product Requirements Document (PRD)

# Sekeron Stage 3 — Artist Intelligence & Recommendation

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | Aug 25, 2026 |
| **Author** | Aldrin |
| **Status** | Submitted, under active fix |
| **Target** | Stage 3 practical assessment |

---

## 1. Product Overview
A small, reproducible, evidence-led system that builds evidence-backed capability records for a roster of freelance artists, matches them against natural-language hirer briefs, and re-ranks when new information arrives — without ever inventing a capability the supplied media doesn't support.

## 2. Problem Statement
Hirers describe what they need in messy, incomplete conversations (WhatsApp chats, emails, phone notes). Artist portfolios mix unverified profile claims with real media evidence. A naive system either takes profile claims at face value (unsupported inference) or ignores uncertainty entirely (false confidence). This system has to do neither.

## 3. Goals
- ✅ Separate profile CLAIMS from DEMONSTRATED capabilities, always.
- ✅ Represent uncertainty honestly — `insufficient_evidence` is not a penalty, it's information.
- ✅ Every ranking decision must be traceable to specific evidence, reproducible on rerun.
- ✅ Selective media processing — never blindly process every frame/second.

## 4. Dataset
| Category | Count |
|---|---|
| Photographers | 5 |
| Musicians | 5 |
| Video editors | 5 |
| **Total artists** | **15** |
| Hirer briefs | 4 |
| Follow-up updates | 1 |
| Original media | 120 files, 941.8 MB |

## 5. Core Features (MVP)
1. Dataset inspection — file-level integrity check, read-only.
2. Evidence selection — sampled, deduplicated, budget-capped per artist.
3. Artist intelligence generation — category-specific capability dimensions via Gemini 3.6 Flash.
4. Hirer brief parsing — explicit constraints, preferences, operational needs, separated from capability requirements.
5. Deterministic scoring & ranking — top-2 recommendations, reproducible given the same inputs.
6. Follow-up re-ranking — reprocess new information, explain what changed and why.

## 6. Hard Constraints
- Max ~6 hours effort · No frontend · No scraping · No model training · No deployment · No RAG/embeddings/agent frameworks
- Paid API capped at ₹300 (actual: ~$0.15–0.25 total, well under)
- Generated outputs must never be manually repaired
- Every claim must be defensible live

## 7. Evaluation Rubric (100 pts)
| Category | Points |
|---|---|
| Hirer intent understanding | 15 |
| Artist capability intelligence | 15 |
| Contextual recommendations | 20 |
| Technical execution | 10 |
| Evaluation and uncertainty | 10 |
| **Live working discussion** | **30** |
