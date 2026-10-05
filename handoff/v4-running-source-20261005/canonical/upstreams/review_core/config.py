"""Configuration for the standalone review_core producer.

The configuration intentionally contains only local roots and public capture
tools.  It has no V3 imports, scheduler registration, account credentials, or
trading capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProducerConfig:
    """Immutable settings injected into a producer run."""

    data_root: Path
    source_root: Path | None = None
    funasr_path: Path | None = None
    ffmpeg_path: Path | None = None
    ytdlp_path: Path | None = None
    python_path: Path | None = None
    target_mid: str = "3546557003598528"
    target_uploader: str = "比巴卜作手"
    public_base_url: str = "https://www.bilibili.com"
    network_allowed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root).absolute())
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).absolute())
        if self.funasr_path is not None:
            object.__setattr__(self, "funasr_path", Path(self.funasr_path).absolute())
        if self.ffmpeg_path is not None:
            object.__setattr__(self, "ffmpeg_path", Path(self.ffmpeg_path).absolute())
        if self.ytdlp_path is not None:
            object.__setattr__(self, "ytdlp_path", Path(self.ytdlp_path).absolute())
        if self.python_path is not None:
            object.__setattr__(self, "python_path", Path(self.python_path).absolute())

    @staticmethod
    def _fingerprint_value(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if callable(value):
            return {
                "module": str(getattr(value, "__module__", "")),
                "qualname": str(getattr(value, "__qualname__", getattr(value, "__name__", ""))),
            }
        if isinstance(value, dict):
            return {str(key): ProducerConfig._fingerprint_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [ProducerConfig._fingerprint_value(item) for item in value]
        return value

    def fingerprint(self) -> dict[str, Any]:
        """Return a deterministic, secret-free configuration fingerprint."""

        return {
            "data_root": str(self.data_root),
            "source_root": str(self.source_root) if self.source_root else "",
            "funasr_path": str(self.funasr_path) if self.funasr_path else "",
            "ffmpeg_path": str(self.ffmpeg_path) if self.ffmpeg_path else "",
            "ytdlp_path": str(self.ytdlp_path) if self.ytdlp_path else "",
            "python_path": str(self.python_path) if self.python_path else "",
            "target_mid": self.target_mid,
            "target_uploader": self.target_uploader,
            "public_base_url": self.public_base_url,
            "network_allowed": bool(self.network_allowed),
            "extra": self._fingerprint_value(self.extra),
        }
