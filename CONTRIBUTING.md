# Contributing to RecallNest

RecallNest is a local personal knowledge application. Contributions should keep archived source records traceable and preserve users' ability to inspect and correct derived knowledge and memory.

## Working on a change

1. Describe the user-visible behavior in an issue or pull request.
2. Use synthetic conversations and temporary data directories in tests. Do not submit your real conversation exports, model credentials or local database.
3. Add a behavior test for changes to import, storage, memory, review, capture or model processing. Reproduce a bug before fixing it.
4. Keep source adapters, persistence, model providers and presentation separate. Reuse the existing service contract for external integrations.
5. Run the relevant tests, then the backend suite and frontend build before submitting.

## Design constraints

- Raw conversations remain available after consolidation.
- Derived knowledge points to actual source messages and quotes.
- AI-generated personal memory starts as a candidate. Only active, confirmed memory enters personal context.
- Corrections and supersession preserve history. Rejected or expired memory must not silently return.
- Replaying an import or capture does not duplicate records.
- A model failure does not erase the original conversation or pretend that consolidation succeeded.
- Basic import, reading and manual review remain available without a model.
- UI statistics come from actual data. Demonstration data is explicitly labeled.
- The default deployment is local single-user. Multi-user or public-network changes need a separate design.

## Pull requests

Explain the original behavior, the resulting behavior, and the commands you ran. Include a screenshot for a visible layout change. Update the API contract and integration documentation when a public interface changes. Credit any new dependency or borrowed code according to its license.
