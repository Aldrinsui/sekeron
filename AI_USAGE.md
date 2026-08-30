# AI Usage

## Tools used

### Gemini

Gemini 3.6 Flash was used to generate the evidence-backed artist intelligence and parse the supplied hirer briefs into structured requirements.

The final artist-intelligence run produced 15 artist records. Hirer parsing produced structured capability requirements, operational constraints, mapped capability dimensions and parsing metadata.

Gemini was used for interpretation and multimodal assessment; deterministic Python was responsible for evidence validation, confidence ceilings, scoring and ranking.

### AI coding assistant

An AI coding assistant in the IDE was used to assist with implementation and iteration of the Python scripts and tests.

It assisted with parser, scoring, orchestration and follow-up update implementation, test creation, debugging, repository inspection and code review.

## Human verification

I remained responsible for the submitted implementation and verified:

- repository structure and Git history
- Python syntax using `py_compile`
- the recommendation test suite
- confidence and importance weighting
- insufficient-evidence handling
- deterministic tie-breaking
- exclusion of operational constraints from scoring
- multi-dimension requirement normalization
- non-lossy requirement-level score breakdowns
- top-two recommendation output
- reasons, trade-offs, assumptions and uncertainty
- refinement-question limits
- follow-up requirement replacement and rescoring
- generated output structure
- evidence references and generation metadata
- final 15-artist validation

The final generated JSON outputs were produced by code and were not manually repaired.

## API limitation

During development, a Gemini API service/rate-limit error occurred on one configured project/model combination. The generation pipeline retried failed requests, and subsequent required generation completed successfully.

The final artist-intelligence output contains 15 successfully generated records, and the final recommendation and follow-up pipelines completed successfully.

No credentials are included in the repository.

## Time spent

Approximately 5 hours, including implementation, testing, debugging and final verification.
