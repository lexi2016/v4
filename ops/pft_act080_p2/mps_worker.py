"""Worker for the verified separate PyTorch MPS Python environment."""

import argparse
import os
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from torch import nn

from .contracts import METHOD, claim, write_json


class ResidualMLP(nn.Module):
    def __init__(self, inputs):
        super().__init__()
        config = METHOD["family_parameters"]["MLP_MPS"]
        width = config["width"]
        self.input = nn.Linear(inputs, width)
        self.residual = nn.Sequential(nn.Linear(width, width), nn.ReLU(), nn.Dropout(config["dropout"]))
        self.output = nn.Linear(width, 1)

    def forward(self, values):
        hidden = torch.relu(self.input(values))
        return self.output(hidden + self.residual(hidden)).squeeze(-1)


def _setup():
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") != "0":
        raise RuntimeError("MPS fallback must be disabled before interpreter import")
    if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
        raise RuntimeError("verified PyTorch MPS device unavailable")
    device = torch.device("mps")
    seed = METHOD["seed"]
    torch.manual_seed(seed)
    torch.mps.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    return device


def _tensor(matrix, device):
    result = torch.as_tensor(matrix, dtype=torch.float32, device=device)
    if result.device.type != "mps":
        raise RuntimeError("a workload tensor is off MPS")
    return result


def _to_scores(module, values):
    module.eval()
    with torch.no_grad():
        logits = module(values)
        if logits.device.type != "mps":
            raise RuntimeError("logits tensor off MPS")
        scores = (1 - torch.sigmoid(logits)).cpu().numpy()
    torch.mps.synchronize()
    return scores, str(logits.device)


def _evidence(model, device, logits_device):
    parameters = sorted({str(p.device) for p in model.parameters()})
    if any(not place.startswith("mps") for place in [*parameters, logits_device]):
        raise RuntimeError("MPS parameter/output device evidence failed")
    return {
        "torch": str(torch.__version__), "device": str(device), "parameter_devices": parameters,
        "logit_device": logits_device, "mps_built": torch.backends.mps.is_built(),
        "mps_available": torch.backends.mps.is_available(), "cpu_fallback": False,
        "synchronized": True, "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "seed": METHOD["seed"],
    }


def _load(weight, width, device):
    model = ResidualMLP(width).to(device)
    state = torch.load(weight, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    return model


def train(input_path, weights, output, evidence, started, attempt):
    device = _setup()
    config = METHOD["family_parameters"]["MLP_MPS"]
    with np.load(input_path, allow_pickle=False) as data:
        x_gradient, y_gradient, x_early, y_early, x_train, x_val = (
            _tensor(data[name], device) for name in ("x_gradient", "y_gradient", "x_early", "y_early", "x_train", "x_val")
        )
    model = ResidualMLP(x_gradient.shape[1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"], foreach=False)
    loss = nn.BCEWithLogitsLoss()
    shuffle = np.random.default_rng(METHOD["seed"])
    best_epoch, stale, best_loss, best = 0, 0, float("inf"), None
    train_started = perf_counter()
    claim(started, fit_id=attempt, family="MLP_MPS", invoked=True,
          torch=str(torch.__version__), actual_device=str(x_gradient.device), fallback=0)
    evaluations = []
    for epoch in range(1, config["max_epochs"] + 1):
        model.train()
        order = shuffle.permutation(len(x_gradient))
        for start in range(0, len(order), config["batch_size"]):
            members = torch.as_tensor(order[start:start + config["batch_size"]], device=device)
            optimizer.zero_grad(set_to_none=True)
            batch_loss = loss(model(x_gradient[members]), y_gradient[members])
            batch_loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            early_logits = model(x_early)
            value = float(loss(early_logits, y_early).item())
        if not np.isfinite(value):
            raise ValueError("nonfinite MPS EARLY_STOP BCE")
        evaluations.append(value)
        if value < best_loss:
            best_loss, best_epoch, stale = value, epoch, 0
            best = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
        else:
            stale += 1
            if stale >= config["patience"]:
                break
    model.load_state_dict(best)
    torch.save(best, weights)
    train_scores, _ = _to_scores(model, x_train)
    val_scores, val_logits_device = _to_scores(model, x_val)
    reloaded = _load(weights, x_val.shape[1], device)
    if not np.array_equal(val_scores, _to_scores(reloaded, x_val)[0]):
        raise ValueError("MPS readback differs from in-memory validation score")
    np.savez_compressed(output, train_scores=train_scores, val_scores=val_scores)
    write_json(evidence, {
        **_evidence(model, device, val_logits_device),
        "actual_train_seconds": perf_counter() - train_started,
        "epochs": epoch, "best_epoch": best_epoch, "best_early_stop_bce": best_loss,
        "early_stop_losses": evaluations, "readback_exact": True,
        "x_gradient_device": str(x_gradient.device), "y_gradient_device": str(y_gradient.device),
        "x_early_device": str(x_early.device),
    })


def score(weight, matrix, output, evidence):
    device = _setup()
    with np.load(matrix, allow_pickle=False) as data:
        x = _tensor(data["values"], device)
    model = _load(weight, x.shape[1], device)
    scores, logit_device = _to_scores(model, x)
    np.savez_compressed(output, scores=scores)
    write_json(evidence, _evidence(model, device, logit_device))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("train", "score"))
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.action == "score" and len(args.paths) == 4:
        score(*(Path(name) for name in args.paths))
    elif args.action == "train" and len(args.paths) == 6:
        train(*(Path(name) for name in args.paths[:5]), args.paths[5])
    else:
        parser.error("invalid worker argument count")


if __name__ == "__main__":
    main()
