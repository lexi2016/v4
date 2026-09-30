# A1445 archive pin correction

The authoritative original archive pin is 811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0. The source raw SHA is 4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571. A direct owner-root check bound the exact source, archive bytes, parsed-payload canonical SHA, store receipt, and store manifest; the binding passed.

An earlier evidence-side transcription used 811b7803b540ec22e8c3f061804229e59fa51179f20a55a56ccc12d946af4af0. Its captured run exited 1 before writing a witness. The corrected original script used the c8e3 value, exited 0, and recorded 27 pointer differences at /cannot_confirm/1 through /cannot_confirm/27. The previous review finding against the frozen pin was withdrawn. See the sanitized direct owner recheck and command capture for the measured values and execution record.

The package reproduction script is a transformed copy: it adds explicit --app-root, --data-root, and --output-dir arguments. Its exported SHA therefore differs from the original evidence script SHA. It reads the caller-supplied original inputs and writes only a derived witness; it does not run Stage, collector, producer, scheduler, or service, and it does not copy market rows.
