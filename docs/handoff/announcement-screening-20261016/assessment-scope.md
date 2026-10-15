# Small-sample announcement screening assessment

Use the local qwen3_8_flash_next with the frozen range-v2 prompt, temperature 0, thinking disabled, original 13-field contract, and one attempt per article. Only complete source text, source metadata and deterministic facts enter model messages. History labels, prior answers and reviewer judgments stay outside model input.

The six-item set contains three unseen routine notices, two development samples and one retest. A separate newly captured nonroutine notice is absent from the prior 170 actual-request IDs. Report these histories accurately; the whole set is not a sealed holdout. The two Guoen regressions are counted separately.

Independently record these dimensions without hiding gaps in one score:

- Research relevance: recognize the disclosed operating/performance event, risk or corporate action and correctly explain routine notices. A risk can be research-relevant. NOT_SELECTED alone does not mean no research value.
- Direction and disposition: positive conclusions need direct evidence; disposition, selection_basis, direction and evidence_sufficiency must satisfy the frozen contract.
- Citations: every model claim must be fully supported by its continuous source range, including subjects, figures, bounds, growth, conditions and qualifiers. Mechanical success is not semantic success.
- Uncertainty: missing material, unaudited status, conditions, PIT and unknown official first-publication time remain explicit.
- Performance: report actual requests, wall and first-content times; preparation and model loading are separate.

Do not tune prompts or repeat these samples to obtain a pass. Preserve real failures, gate rejections and unknowns. This small test supports an initial capability assessment, not whole-market autonomous selection reliability.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
