"""Produce a PNG from the exact frozen SVG on the A-side Mac."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from research.act070a.case_contract import require
from research.act070a.chart import HEIGHT, WIDTH

SIPS = "/usr/bin/sips"
RENDERER = "ACT071A_SIPS_316_SVG_TO_PNG"


def render_png(svg: bytes) -> bytes:
    version = subprocess.run([SIPS, "--version"], capture_output=True, check=True)
    require(version.stdout.strip() == b"sips-316", "RENDERER_MISMATCH", "expected sips-316")
    with TemporaryDirectory(prefix="act071a-chart-") as directory:
        source, target = Path(directory) / "chart.svg", Path(directory) / "chart.png"
        source.write_bytes(svg)
        process = subprocess.run([SIPS, "-s", "format", "png", str(source), "--out", str(target)],
                                 capture_output=True)
        require(process.returncode == 0 and target.is_file(), "RENDERER_FAILED", "sips SVG conversion")
        png = target.read_bytes()
    require(len(png) >= 24 and png.startswith(b"\x89PNG\r\n\x1a\n")
            and struct.unpack(">II", png[16:24]) == (WIDTH, HEIGHT),
            "RENDERER_FAILED", "PNG signature or chart dimensions")
    return png
