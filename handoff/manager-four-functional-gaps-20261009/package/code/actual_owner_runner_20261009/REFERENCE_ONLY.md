# Reference-only runner source

These files are copied from the previously executed isolated recovery workflow so Chat can inspect the actual owner calls and exact source identity. They are not a ready-to-run local package. The runners expect the original recovery inputs and source trees and write new outputs under the recovery folder; this handoff task did not authorize rerunning them. Do not execute these copies as part of the offline contract smoke. The offline fixture is intentionally synthetic, fail-closed, and separate.

A Mac-side run must use the current approved local owner workflow and exact date-bound inputs after checking source/run/manifest SHA and output location. These source files do not include original owner state, market payloads, or credentials.
