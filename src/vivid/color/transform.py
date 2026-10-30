"""Digital-vibrance-style saturation mathematics.

The user-facing adjustment is a percentage ``p`` from -100 to +100, where 0
means the normal baseline, -100 is grayscale, and +100 means twice the baseline
saturation. The multiplier is ``s = 1 + p / 100``.

For gamma-encoded RGB the transform is::

    Y' = 0.2126 R' + 0.7152 G' + 0.0722 B'
    R'' = Y' + s (R' - Y')

and likewise for green and blue, followed by clipping to [0, 1].  The BT.709
luma weights are the ones used by GPU digital-vibrance implementations on
nonlinear RGB; they are not linear-light luminance coefficients.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import isfinite

from ..models import MAX_SATURATION, MIN_SATURATION, validate_percent

BT709_LUMA = (0.2126, 0.7152, 0.0722)
SRGB_PRIMARIES = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
D65_WHITEPOINT = (0.3127, 0.3290)
SRGB_TO_XYZ_D65 = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
XYZ_D65_TO_SRGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)
BRADFORD_D65_TO_D50 = (
    (1.0478112, 0.0228866, -0.0501270),
    (0.0295424, 0.9904844, -0.0170491),
    (-0.0092345, 0.0150436, 0.7521316),
)
BRADFORD_D50_TO_D65 = (
    (0.9555766, -0.0230393, 0.0631636),
    (-0.0282895, 1.0099416, 0.0210077),
    (0.0122982, -0.0204830, 1.3299098),
)
CLUT_GRID = 17
CLUT_OFFSET = 2.0
CLUT_SPAN = 5.0
CURVE_SAMPLES = 4096


def matmul(
    a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def invert3(m: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-15:
        raise ZeroDivisionError("matrix is not invertible")
    return (
        ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
        ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
        ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det),
    )


def clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def saturation_scale(percent: int) -> float:
    percent = validate_percent(percent)
    return max(0.0, 1.0 + percent / 100.0)


def saturation_matrix(multiplier: float) -> tuple[tuple[float, ...], ...]:
    if not isfinite(multiplier) or multiplier < 0:
        raise ValueError("saturation multiplier must be a finite non-negative number")
    return tuple(
        tuple(
            (multiplier if row == column else 0.0) + (1.0 - multiplier) * BT709_LUMA[column]
            for column in range(3)
        )
        for row in range(3)
    )


def apply_saturation(rgb: Sequence[float], multiplier: float) -> tuple[float, float, float]:
    if len(rgb) != 3:
        raise ValueError("rgb must contain exactly three components")
    r, g, b = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    luma = BT709_LUMA[0] * r + BT709_LUMA[1] * g + BT709_LUMA[2] * b
    return (
        clamp01(luma + multiplier * (r - luma)),
        clamp01(luma + multiplier * (g - luma)),
        clamp01(luma + multiplier * (b - luma)),
    )


def apply_percent(rgb: Sequence[float], percent: int) -> tuple[float, float, float]:
    return apply_saturation(rgb, saturation_scale(percent))


def srgb_decode(value: float) -> float:
    value = clamp01(value)
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def srgb_encode(value: float) -> float:
    value = clamp01(value)
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * (value ** (1.0 / 2.4)) - 0.055


def clut_uint16(percent: int, grid: int = CLUT_GRID) -> list[int]:
    if grid < 2:
        raise ValueError("CLUT grid must be at least 2")
    multiplier = saturation_scale(percent)
    values: list[int] = []
    for red_index in range(grid):
        red = red_index / (grid - 1)
        for green_index in range(grid):
            green = green_index / (grid - 1)
            for blue_index in range(grid):
                blue = blue_index / (grid - 1)
                for channel in apply_saturation((red, green, blue), multiplier):
                    encoded = (channel + CLUT_OFFSET) / CLUT_SPAN
                    values.append(int(round(encoded * 65535.0)))
    return values


def srgb_encode_curve_uint16(samples: int = CURVE_SAMPLES) -> list[int]:
    if samples < 2:
        raise ValueError("curve must contain at least two samples")
    return [int(round(srgb_encode(index / (samples - 1)) * 65535.0)) for index in range(samples)]


def mean_absolute_error(
    actual: Iterable[Sequence[float]], expected: Iterable[Sequence[float]]
) -> float:
    total = 0.0
    count = 0
    for left, right in zip(actual, expected, strict=True):
        for a, b in zip(left, right, strict=True):
            total += abs(float(a) - float(b))
            count += 1
    return total / count if count else 0.0


def valid_percent(value: int) -> bool:
    return MIN_SATURATION <= value <= MAX_SATURATION
