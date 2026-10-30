"""Fallback backend that reports an unsupported environment honestly."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import ApplyResult, CapabilityReport, DisplayInfo, DisplayStatus
from .base import Backend


class UnsupportedBackend(Backend):
    name = "unsupported"

    def __init__(self, capabilities: CapabilityReport) -> None:
        self._capabilities = capabilities

    @property
    def capabilities(self) -> CapabilityReport:
        return self._capabilities

    def _message(self) -> str:
        return (
            "; ".join(self._capabilities.reasons)
            or "per-output saturation is not supported in this session"
        )

    def apply(self, display: DisplayInfo, percent: int) -> ApplyResult:
        return ApplyResult(
            success=False,
            status=DisplayStatus.UNSUPPORTED,
            message=self._message(),
            requested_percent=percent,
            display=display,
        )

    def reset(self, display: DisplayInfo) -> ApplyResult:
        return ApplyResult(
            success=False,
            status=DisplayStatus.UNSUPPORTED,
            message=self._message(),
            requested_percent=0,
            display=display,
        )

    def reset_all(self, displays: Iterable[DisplayInfo]) -> list[ApplyResult]:
        return [self.reset(display) for display in displays]
