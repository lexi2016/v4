# Cross-market workbench 21-node candidate

Source base: `881bbb4392e36b7ddac5b893580b099074dbfc8a`. The local candidate uses the API role of `v4-v45-parallel-p0-20261113-r2-api` and the existing Research UI role. Deployment: `NOT_RUN`. Source, release inventory, and browser receipts are retained locally.

The existing workbench displays full Shanghai time windows, the observation and source dates, execution timestamps, results, and missing evidence. Plan 21 is the existing 21:15 next-day pool publication slot. A date-pinned `workflow_node_evidence` operator binding links to reviewed records. An explicit workbench read verifies SHA-256. The completion feed uses descriptor and file metadata for change detection without repeatedly reading evidence bytes. Future work dates can show a prior-day input, but preserve their own not-due execution states.

Independent review passed. Fifteen targeted Python tests, four existing deep-link checks, and syntax/diff checks passed. The isolated API role exposes the existing workbench and rejects mutation methods.

Original November 13 Stage receipts preserve six A-share selection failures. The owner validator rejected an older pinned Main release inventory whose entry count was absent. A local clone of the historical release was resealed from its unchanged file inventory and the existing aggregate digest, then pinned in an isolated Stage role. The original research reader passed all six cutoffs with this pin. The original selector processed 341 cached rows per cutoff and wrote 10 watch-only rows per cutoff to an isolated selection store. This was a historical replay. Natural run and point-in-time qualification were not upgraded.

The original two next-day pool builders still report CANNOT_CONFIRM for signal date November 13 and target November 16. The close-review pool has no qualifying same-day Review Bundle. The Stage7 pool has no qualifying tail source in its original store, and the retained tail raw manifest does not certify the original cutoff. The candidate displays both original failures and the isolated recovery evidence without substituting the replay for either pool.
