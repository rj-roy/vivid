"""Vivid: independent per-display saturation control for KDE Plasma Wayland."""

from __future__ import annotations

APP_ID = "io.github.vivid.DisplaySaturation"
APP_NAME = "Vivid"
APP_VERSION = "1.0.0"
CONFIG_SCHEMA_VERSION = 1
MAX_SATURATION = 100
MIN_SATURATION = -100

__all__ = [
    "APP_ID",
    "APP_NAME",
    "APP_VERSION",
    "CONFIG_SCHEMA_VERSION",
    "MAX_SATURATION",
    "MIN_SATURATION",
]
