# AI Usage

## Tools used

### Gemini

Gemini was used to generate the evidence-backed artist intelligence and parse the supplied hirer briefs into structured requirements.

The artist intelligence run produced 15 artist records and passed validation. Hirer parsing produced structured capability requirements, operational constraints, mapped capability dimensions and parsing metadata.

### AI coding assistant

An AI coding assistant in the IDE was used to assist with implementation and iteration of the Python scripts and tests.

It assisted with parser, scoring, orchestration and follow-up update implementation, test creation, debugging and code inspection.

## Human verification

I remained responsible for the submitted implementation and verified:

- repository structure and Git history
- Python syntax using py_compile
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

The final generated JSON outputs were produced by code and were not manually repaired.

## API limitation

The real Gemini-generated artist intelligence and parsed hirer requirements were successfully produced.

During one final regeneration attempt, an API quota/rate-limit error occurred because the configured API key belonged to a different project. After switching to the Sekeron project key, the real recommendation and follow-up pipelines completed successfully.

No credentials are included in the repository.

## Time spent

Approximately 5 hours, including implementation, testing, debugging and final verification.
