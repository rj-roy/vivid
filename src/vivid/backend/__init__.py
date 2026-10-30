"""Compositor backends."""

from __future__ import annotations

from .base import Backend
from .capabilities import detect_capabilities
from .kwin_icc import KWinIccBackend
from .unsupported import UnsupportedBackend

__all__ = [
    "Backend",
    "KWinIccBackend",
    "UnsupportedBackend",
    "detect_capabilities",
]
