"""Ports used by the independent manager research service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence


class ObservationReader(Protocol):
    """Read the already materialized stage observation for one exact date."""

    def read(self, target_trade_date: str) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class SourceResponse:
    """A public source response captured by an injected transport."""

    url: str
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    retrieved_at: str
    final_url: str | None = None


class SourceTransport(Protocol):
    def __call__(
        self,
        url: str,
        *,
        timeout: float,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SourceResponse:
        ...


class ResearchSourceProvider(Protocol):
    """Collect one independently sourced research observation."""

    provider_id: str

    def collect(
        self,
        *,
        target_trade_date: str,
        cutoff_at: str,
        observation: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class ManagerResearchObserver(Protocol):
    def __call__(self, target_trade_date: str) -> Mapping[str, Any]:
        ...


class ManagerResearchProvider(Protocol):
    def __call__(
        self,
        *,
        target_trade_date: str,
        cutoff_at: str,
        observation: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...
