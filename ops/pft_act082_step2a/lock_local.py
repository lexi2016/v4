"""Lock authentic local DEV outcomes and the independent rerating unit at rest."""

from argparse import ArgumentParser
import json
from pathlib import Path

from .evidence import canonical_json
from .pipeline import FRAME_NAME, QFQ, VAULT_B, require_prepared_source
from .sources import digest, verified_qfq_basis
from .vault import encrypt_directory, require_private_directory, write_new


def lock_dev(root, owner_basis_reference):
    private = root / VAULT_B
    lock = json.loads((private / "PRE_RENDER_LOCK.json").read_bytes())
    live_source = require_prepared_source(lock)
    run_state = json.loads((root / "DEV_PREPARATION_RECEIPT.json").read_bytes())
    render_state = json.loads((root / "DEV_RENDER_RECEIPT.json").read_bytes())
    if len({run_state["sampling_frame_sha256"], render_state["input_lock_sha256"], lock["sha256"],
            digest(private / FRAME_NAME)}) != 1 or render_state["verified_prepared_source_sha256"] != live_source:
        raise ValueError("render lock and source sample identities differ")
    if run_state["dev_label_end_max"] != "2025-09-30" or render_state["review_groups"] != 260:
        raise ValueError("unverified DEV receipt")
    basis = verified_qfq_basis(owner_basis_reference)
    if (private / QFQ).read_bytes() != canonical_json(basis) or len({
        digest(private / QFQ), lock["qfq_basis_sha256"], render_state["qfq_basis_sha256"],
    }) != 1:
        raise ValueError("QFQ basis registration mismatched render and prepared source")
    custody = require_private_directory(root / "KEY_CUSTODY_LOCAL_ONLY")
    locked = require_private_directory(root / "LOCAL_DEV_CIPHERTEXT")
    outcomes = encrypt_directory(
        private, locked / "DEV_OUTCOME_EXEC_AND_SAMPLING.aesgcm",
        custody / "DEV_OUTCOME_EXEC_AND_SAMPLING.key", "DEV_OUTCOME_EXEC_AND_SAMPLING",
    )
    alternate = encrypt_directory(
        root / "PRIVATE_RELABEL_REVIEW", locked / "CHANNEL_A_RELABEL.aesgcm",
        custody / "CHANNEL_A_RELABEL.key", "CHANNEL_A_RELABEL",
    )
    receipt = {
        "stage2a_status": "PARTIAL_INSUFFICIENT_VERIFIED_SEALED_STRATA", "real_sealed_open_count": 0,
        "dev_ciphertext": outcomes, "channel_a_relabel_ciphertext": alternate,
        "encrypted_artifacts_local_only": True, "no_export_archives_created": True,
        "basis_registration": basis, "independent_user_account_custody": "NOT_ATTESTED",
        "verified_prepared_source_sha256": live_source, "qfq_basis_sha256": lock["qfq_basis_sha256"],
        "private_source_vault_retained_for_independent_review": True,
    }
    require_prepared_source(lock)
    write_new(root / "LOCAL_DEV_LOCK_RECEIPT.json", canonical_json(receipt))
    return receipt


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owner-basis-reference", type=Path, required=True)
    args = parser.parse_args()
    report = lock_dev(args.root, args.owner_basis_reference)
    print(json.dumps({
        "stage2a_status": report["stage2a_status"],
        "dev_ciphertext_sha256": report["dev_ciphertext"]["ciphertext_sha256"],
        "relabel_ciphertext_sha256": report["channel_a_relabel_ciphertext"]["ciphertext_sha256"],
    }))


if __name__ == "__main__":
    main()

