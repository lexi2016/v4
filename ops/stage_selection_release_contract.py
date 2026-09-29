"""Frozen Stage import closure, not a dirty-worktree packaging recipe.

Pins are reviewed source identities at this repair, not discovered at build
runtime. The existing release builder still preserves the verified active
inventory outside its explicit overlays. External/dynamic provider imports
remain subject to Mac runtime acceptance; this checks local Stage imports.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Sequence

STAGE_SELECTION_SHA256 = {
    "domains/research.py": "8cb2b0e81f3da1c686c444ab528c19f089c83f9663218fcfe030c594296df361",
    "stage_center/__init__.py": "f5bc18e6c6143feaa23627ac8b66885810adbf77fb2135a295526fd188949955",
    "stage_center/_formula_margin_shadow_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_formula_margin_shadow_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_formula_margin_shadow_parts/artifact_evidence.py": "8c2cc2c5fefbbfd05f4da94f17e063650f7378d1a015f27dd5b2915a2b422571",
    "stage_center/_formula_margin_shadow_parts/capture_payload.py": "c635c8a25a1240a58bd2bf60282fa7a978ed61eebc0f35fdaf4b4215e3969dbd",
    "stage_center/_formula_margin_shadow_parts/capture_policy.py": "64f2fbbfe8f8123be53574b9194a35df11c2694391cad148657a59559fd404f1",
    "stage_center/_formula_margin_shadow_parts/capture_price_receipt.py": "57c394aaee4c0bde7096e10a5d3d5cbe1563252dd030c42236600f328b988a35",
    "stage_center/_formula_margin_shadow_parts/capture_request.py": "301b394871c90bf72bb6533d09dfffe3e8d9c08e2433d5a75438cf2b6e30c02d",
    "stage_center/_formula_margin_shadow_parts/evaluation.py": "11fcfefd9b7ffe2b9d53dee2375be9efd0338e3f31d5c54dc222da6f01afe790",
    "stage_center/_formula_margin_shadow_parts/frozen_readers.py": "2a8ee586e86d7a305e66fa1051639a331119d1848008d7575a56f6dae257b297",
    "stage_center/_formula_margin_shadow_parts/label_truth.py": "0cb06a866a47d77682c70960d114a57077c2058b0e33d9e7bfc16a5c01ea9cd2",
    "stage_center/_formula_margin_shadow_parts/live_capture.py": "b9efd1038a3c682141b5befd5e4b22f3af93974a1084a23ba070076a5b53bce7",
    "stage_center/_formula_margin_shadow_parts/manifest_binding.py": "2af37f8ded7860276cbdf10b11575801acd82a5f8283f679891fc7a6072a7f48",
    "stage_center/_formula_margin_shadow_parts/row_scoring.py": "5240e96c0bf22769c91075b7345e7f21f46218351be11b2cf84be30bf40f0318",
    "stage_center/_formula_margin_shadow_parts/shadow_build.py": "26ecdb136ab8cf134005eed4444baf8e4e54306369a7dd1442a95b238e48519f",
    "stage_center/_formula_margin_shadow_parts/snapshot_freeze.py": "3f66ecd9f3cc274de27510aba49fd924a75403abf59145fb5c4e6377fa8aed69",
    "stage_center/_live_collectors_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_live_collectors_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_live_collectors_parts/a_auction.py": "b74756748e98035d8058447f5f2644aa5709e4739bfe0ee9f365d4f0c7094e2c",
    "stage_center/_live_collectors_parts/a_minute.py": "5d56f92766b9b802c4b403d8f5af25cc82a9ef6b3f82675d1406fb4752c4362e",
    "stage_center/_live_collectors_parts/collector_registry.py": "b8c366267f611ff76d0228093a9d826ee7c367b938aa4ab098f022a687245999",
    "stage_center/_live_collectors_parts/hk_active_snapshot.py": "5079d283c25d8bc778e749e29b5c590eae25d90b3a9d5ffc785e32ce02e5f5b9",
    "stage_center/_live_collectors_parts/hk_auction.py": "7658e15fbaffeb0846dad2eecc31c079f22968892c149385673eb6fa373e6dea",
    "stage_center/_live_collectors_parts/hk_minute.py": "89c3d03f742559dff3eba8c1553c7546893c3135c3e3672d61b2c25cf5a288ba",
    "stage_center/_live_collectors_parts/hk_replay.py": "89456aaf429390a41604dc3d9f564c23f9ec6d7a36e2a5ec32948f9d53b9a108",
    "stage_center/_live_collectors_parts/selection_builder_registry.py": "5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22",
    "stage_center/_live_collectors_parts/shared_module_loading.py": "a24bb9cfbc4449796df6d0abacb60a1766b4554357a58ca95520e25f1c154fc2",
    "stage_center/_live_collectors_parts/temporal_validation.py": "61c8fec0021fb66356cf31791a5bc3af576681fa1e576bbf142463b581dc2961",
    "stage_center/_raw_store_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_raw_store_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_raw_store_parts/codec.py": "504b97a64f483db17026dbeed6d5084fbc18ee972be60ad9e069ebd038708572",
    "stage_center/_raw_store_parts/filesystem_io.py": "f904f4086d4debfc32f5ad33ec2717cda522a59f2e15a3518c7aa83b91eef2b1",
    "stage_center/_raw_store_parts/receipt_identity.py": "b33c496a6052b450959a9b886c79ad8d5686230e320dbc99bfd98a3e8265a8f0",
    "stage_center/_raw_store_parts/transaction_publish.py": "4c28d92667428cfeced54e074e800337ca88b7e87d8a5468a9464b668ca9b24e",
    "stage_center/_raw_store_parts/transaction_read.py": "8b7e88dc5e5f41456e5222f1a5c08c5dcd05f5e5d7f2c179fd26652bff2932b6",
    "stage_center/_runner_parts/__init__.py": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8",
    "stage_center/_runner_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_runner_parts/a_candidate_authority.py": "ffe9a6a9f8fa06772e45468b9b00269427ff091be260cb78e633481663835560",
    "stage_center/_runner_parts/a_name_authority.py": "a2f86dd7819bd76acba555b3a18a6f913f71689b284536ea3086225f5d8cf556",
    "stage_center/_runner_parts/configuration.py": "713ac5b8ac81fe186904eca38c8e7a28a2edb83a0cf98766546a09f7169c7486",
    "stage_center/_runner_parts/hk_candidate_authority.py": "1fd933e8436e4316832c29f89da16c1ccf3ed78b14ee853262ed758e476d2f95",
    "stage_center/_runner_parts/hk_input_validation.py": "f703a8aa5e79742785b07d29778f42f53035e56b15f695aebc92d56c680531cd",
    "stage_center/_runner_parts/row_evidence.py": "f1659b68c8983c789c9306027e3e90d0dcce8c137674a5cf34edfa7d7fdbde3a",
    "stage_center/_runner_parts/runner_receipts.py": "3d0d3fcc244d94b2e289e97429cd7863d2272c4151a733fef96920b47c741b0e",
    "stage_center/_runner_parts/selection_input_validation.py": "23e8afa65fa9fe0b24baefb8e778af3c475e1affaa34a2734ea80ea0aca9d44c",
    "stage_center/_runner_parts/slot_execution.py": "a6584015f7196091f69b25f810b6e83755b86d7ac8ce36891e479a4203b1945c",
    "stage_center/_runner_parts/slot_idempotency.py": "2f79cdfedd50e047f22beaafe254edff420a7fb28be6379ba9a92a475abfa39c",
    "stage_center/_runner_parts/slot_lock.py": "f90d3c8e3fba34d157bf45e1f544e9169a575931a3f2f33340e97c25879f5c1d",
    "stage_center/_runner_parts/tick_planning.py": "c27cb9717ec2940364d1e1186529e6df1b37b07aae0c56f65334f6f9bf06dd15",
    "stage_center/_selection_parts/__init__.py": "b56739ecc4a80eaa081f3ea124cf3199683fd470d71a770c9f91cc14de128140",
    "stage_center/_selection_parts/_namespace.py": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
    "stage_center/_selection_parts/a_auction.py": "2ca86af78b7d24b5a156dd3ca1b26aef5728d9df289dba9eef4f7481f7b9b2a9",
    "stage_center/_selection_parts/a_live.py": "b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d",
    "stage_center/_selection_parts/a_stage.py": "05a681a0e0d6de765fee6c84242747aaf233a6abdad3e982ae1d5f0909195cf2",
    "stage_center/_selection_parts/artifact_codec.py": "6c0ddaed1dfe7a066be9aeb1c726e2357f5c1814b0baca834c37bb1879aeeb9d",
    "stage_center/_selection_parts/hk_auction_filter.py": "2b3b3bb94dde8f35afabd4bd4072a4482a82f4cd0a9b8ee0d878046f1a5c4d4c",
    "stage_center/_selection_parts/hk_auction_reference.py": "d02e852313f6430a0102a029c22fe399400085ec4a317849b27987e8db64286d",
    "stage_center/_selection_parts/hk_formula_score.py": "4e42a0e6c233f649f8937dc5b5de231ce59fce8363d05025e9df77a78c4f00d7",
    "stage_center/_selection_parts/hk_four_lanes.py": "d44cd657b15b806922dd99317cfe759849a0d59884a0e39a533f0204f530ae71",
    "stage_center/_selection_parts/market_quality.py": "726cd4987a070bf78ac7416756f3cbba86633b1176f6f43535ac747263474b3f",
    "stage_center/_selection_parts/primitives_io.py": "6e2d288cb555281b1e3870417ed874d38299fd5945215efe017fd27afd7b3394",
    "stage_center/_selection_parts/schema_values.py": "80b0c21556c78c89132a08ca24eb80b5a211791719cb54801497dbe74472e458",
    "stage_center/_selection_parts/selection_envelope.py": "be7748ff72fd85375fc6575a6a40281fb1518c8faf0e55f352f167fbbc42bd89",
    "stage_center/_selection_parts/shadow_capture.py": "92875f5e1b969ec73790b31cd91378059d3f3eb07c3fcbd70c3ad16675ee66e5",
    "stage_center/_selection_parts/store_publication.py": "e3ee42413c35aa098cddc136795fcf04a37898bc2224d815cbe9e2b854c5c968",
    "stage_center/_selection_parts/store_verification.py": "af061784202e35bd7c497208407ce1313876683544d89bcb05153ebca1e7af0f",
    "stage_center/acquisition.py": "33e5003faed8127ec3393eb36af473c0d63ee3a79843418ef1a950ce7b697397",
    "stage_center/attempt_evidence.py": "f98a9070ade0c26a3cfa0bf60acd4798ec011330ca83bc172c64856bd88dc1bf",
    "stage_center/calendar.py": "31fed97066d9b804a71f15c48d4e0f8baa5d9af621e1d81dc0340fd6619e4099",
    "stage_center/candidate_input.py": "59c6bb0ef13a5aaa576477708385ec4ac68b7d20a69e3fc61d984da4a8284aff",
    "stage_center/consumer.py": "ea54316237846f33d664086321a240fbd4a9e35d863e7c852a584014c12324b2",
    "stage_center/contracts.py": "6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d",
    "stage_center/end_to_end_deadline.py": "f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e",
    "stage_center/formula_margin_shadow.py": "5e637c8650a7779b24148d6341743765045b252804bc450f755a9f448acdbb2b",
    "stage_center/historical_readback.py": "251345eba31431a78e44890eefbb46a9a8a6ba566c8461862b7713f278331bda",
    "stage_center/hk_stage8/__init__.py": "d33f9f7ba2135f35073c92fdae1cd8b877f1fa9271f4c1c22217c1e969455f0b",
    "stage_center/hk_stage8/builders.py": "231b8c0acc1092663b3236ad0415242280c4951b17a0aa094b632f7be0fe5a7c",
    "stage_center/hk_stage8/precapture.py": "09e2140a6a3dd5516556193dec4a4e67b7d5db425be2282f187ea8c819d1f002",
    "stage_center/hk_stage8/rtdata.py": "a85317c29df499162c7c805be19e89e198f77ad1d51811912da0c29d27bb8547",
    "stage_center/hk_stage8/snapshot.py": "d1658e72a03a6842c2e6b1b3ae63f6889aa00f28c69ad0a7aa5c7400bf6f5267",
    "stage_center/input_contracts.py": "9521a336709286ab301368a70e2c99f6db6a8ffe288347977328619de7611fd2",
    "stage_center/live_collectors.py": "77265053ea2bc9b6aa3e63b5b18a10a0300ef446873e10cb0f788b8ac255ef20",
    "stage_center/raw_store.py": "15052b23c62d38b65d65b96bf3b837782ebfa6fca7fe83f7c1d9374400bbdbde",
    "stage_center/research_context.py": "d4c7ff8123427c5b3d7ed753c52ed57c541dfa6e515f83c567d04c11504d2c2e",
    "stage_center/runner.py": "648fe7af52df1b4eba31802361f9af2d03decbbebb3286ecc7a5dc0b06523205",
    "stage_center/scheduler.py": "e56651ec7bb481b28e383cb403d60ba48747ddf7426f9fb380f5ae24fc3a37a4",
    "stage_center/selection.py": "ccf7dddfb72fe88b5bff68ce9501e0a8ef9f41a212008a495824017943675294"
}


def require_selection_closure(*, source_root: Path, overlay_paths: Sequence[str]) -> None:
    """Reject incomplete cohorts, drift, links and newly unreviewed Stage imports."""
    selected = set(overlay_paths)
    if not selected.intersection(STAGE_SELECTION_SHA256):
        return
    missing = sorted(set(STAGE_SELECTION_SHA256) - selected)
    if missing:
        raise ValueError(f"Stage selection closure is incomplete: {missing}")
    for relative, expected in STAGE_SELECTION_SHA256.items():
        path = source_root / relative
        current = source_root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"Stage selection closure symlink is forbidden: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"Stage selection closure source missing: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Stage selection closure SHA-256 mismatch: {relative}")
        if relative.startswith("stage_center/"):
            _require_declared_imports(source_root, relative, selected)


def _module_path(root: Path, module: str) -> str | None:
    stem = module.replace(".", "/")
    for relative in (f"{stem}.py", f"{stem}/__init__.py"):
        if (root / relative).is_file():
            return relative
    return None


def _require_declared_imports(root: Path, relative: str, selected: set[str]) -> None:
    module = relative.removesuffix(".py").replace("/", ".")
    package = module.removesuffix(".__init__") if module.endswith(".__init__") else module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse((root / relative).read_bytes(), filename=relative)):
        if isinstance(node, ast.Import):
            required = [item.name for item in node.names]
            optional = []
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = package.split(".")[:len(package.split(".")) - node.level + 1]
                base = ".".join(prefix + ([base] if base else []))
            required = [base]
            optional = [f"{base}.{item.name}" for item in node.names if item.name != "*"]
        else:
            continue
        for name in required + optional:
            if name != "stage_center" and not name.startswith("stage_center."):
                continue
            dependency = _module_path(root, name)
            if dependency is None and name in optional:
                continue  # from-module attributes are not assumed to be modules.
            if dependency is None or dependency not in STAGE_SELECTION_SHA256 or dependency not in selected:
                raise ValueError(f"Stage selection dependency is missing or unreviewed: {relative} -> {name}")
