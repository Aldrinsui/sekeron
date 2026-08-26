# AI Usage

## Tools used

### Gemini

Gemini was used to generate the evidence-backed artist intelligence and parse the supplied hirer briefs into structured requirements.

The final artist-intelligence run produced 15 artist records using Gemini 3.6 Flash. The final combined output passed the project's validation checks. Hirer parsing produced structured capability requirements, operational constraints, mapped capability dimensions and parsing metadata.

### AI coding assistant

An AI coding assistant in the IDE was used to assist with implementation and iteration of the Python scripts and tests.

It assisted with parser, scoring, orchestration and follow-up update implementation, test creation, debugging and code inspection.

## Human verification

I remained responsible for the submitted implementation and verified:

- repository structure and Git history
- Python syntax using `py_compile`
- the recommendation test suite
- confidence and importance weighting
- insufficient-evidence handling
- deterministic tie-breaking
- exclusion of operational constraints from scoring
- top-two recommendation output
- reasons, trade-offs, assumptions and uncertainty
- refinement-question limits
- follow-up requirement replacement and rescoring
- generated output structure
- evidence references and generation metadata

The final generated JSON outputs were produced by code and were not manually repaired.

## API limitation

During development, a Gemini API quota/rate-limit error occurred after the free-tier request quota for one project/model was exhausted. This prevented two artist records and a follow-up parsing request from completing on that configuration.

A separate authorized Gemini API project with available quota was then used for the remaining required generation. The final artist-intelligence output contains 15 successful Gemini-generated records, and the final recommendation and follow-up pipelines completed successfully.

No credentials are included in the repository.

## Time spent

Approximately 5 hours, including implementation, testing, debugging and final verification.