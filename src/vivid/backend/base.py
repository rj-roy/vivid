"""Backend interface shared by the KWin implementation and the fallback."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from ..models import ApplyResult, CapabilityReport, DisplayInfo


class Backend(ABC):
    name = "unsupported"

    @property
    @abstractmethod
    def capabilities(self) -> CapabilityReport:
        raise NotImplementedError

    @abstractmethod
    def apply(self, display: DisplayInfo, percent: int) -> ApplyResult:
        raise NotImplementedError

    @abstractmethod
    def reset(self, display: DisplayInfo) -> ApplyResult:
        raise NotImplementedError

    def reset_all(self, displays: Iterable[DisplayInfo]) -> list[ApplyResult]:
        return [self.reset(display) for display in displays]
