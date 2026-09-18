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

During development, a Gemini API request failed with an HTTP 503 (Service Unavailable) error on the VO5 (video editor) artist. The generation pipeline retried automatically and received a successful HTTP response with valid JSON on a later attempt, but that response's own content indicated the supplied evidence for VO5 could not be read in that run. As a result, VO5's record has `insufficient_evidence` across all 7 of its standard capability dimensions, with `generation_metadata.status: "ok"` because the API call itself succeeded even though the model reported it could not process the attached media.

This is disclosed rather than hidden: `insufficient_evidence` is the correct, honest representation of that outcome per this pipeline's own rules (an inability to assess is never presented as a negative capability finding), but it is not the same as a substantive assessment, and I have not yet re-run VO5 to obtain one. All other 14 artist records show substantial demonstrated-capability coverage (4 of 8 to 8 of 8 standard dimensions), and the recommendation and follow-up pipelines completed successfully using the full 15-record intelligence file as-is.

No credentials are included in the repository.

## Time spent

Approximately 5 hours, including implementation, testing, debugging and final verification.