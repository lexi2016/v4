# ZSXQ PDF automatic continuation

The old success hook processed only a bounded fragment after each hourly fetch. This change makes that hook enqueue references and lets one bounded background child in the existing scheduler continue the owned PDF queue without further chat prompts. It preserves source/date/SHA boundaries, saved page progress, locks and explicit failures. A verified cached 51-page PDF can recover once from the old 40-page cap under the new bounded 64-page cap.

Candidate source and full runtime packages passed independent focused acceptance (29 cases, with the packaged hook correction rerun separately). API and scheduler were deployed through isolated releases while preserving non-target bytes. Runtime review independently confirmed automatic batch progression and authentic page-cap recovery. The 11:00 natural fetch enqueued two more references.

At the last recorded snapshot, 59 of the original 79 documents were READY, with 795/1042 pages processed and no failures. This includes the previously completed canary; finishing the remaining 78 is still in progress. Final all-document/API/browser acceptance is NOT_RUN pending completion. The user requested no continued chat polling; the observer was stopped while the existing scheduler continues. A single delayed acceptance is scheduled.

`delivery.json` binds source and runtime identities, before/after hashes and validation states. Runtime patches apply to their recorded accepted base files; canonical source and runtime layout differ. No raw PDFs, OCR text, credentials or source business data are included.
