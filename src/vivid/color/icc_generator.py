"""Synthetic ICC profile generation for KWin's per-output colour pipeline.

KWin applies a display profile's B2A (PCS to device) transform.  Vivid builds an
ICC v2 ``lut16Type`` B2A tag whose pipeline is:

1. a 3x3 matrix converting the scaled PCS XYZ(D50) values KWin provides into
   linear sRGB;
2. a 1D sRGB encoding curve, recovering the original gamma-encoded signal;
3. a 17x17x17 CLUT implementing the saturation matrix in gamma space;
4. 1D curves undoing the CLUT offset and clipping to [0, 1].

The CLUT contains a linear function, so trilinear interpolation reproduces it
exactly.  KWin feeds ``XYZ * 65536 / (2 * 65535)`` into the B2A tag, hence the
matching scale in the first matrix.

The B2A construction follows the method documented by the MIT-licensed
plasma-vibrance project.  Vivid reimplements it with explicit validation,
content-addressed caching, deterministic output, and a narrower architecture.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import re
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import VividError, validate_percent
from .transform import (
    BRADFORD_D65_TO_D50,
    CLUT_GRID,
    CLUT_OFFSET,
    CLUT_SPAN,
    CURVE_SAMPLES,
    D65_WHITEPOINT,
    SRGB_PRIMARIES,
    SRGB_TO_XYZ_D65,
    XYZ_D65_TO_SRGB,
    apply_percent,
    clut_uint16,
    matmul,
    srgb_decode,
    srgb_encode_curve_uint16,
)

KWIN_XYZ_SCALE = 65536.0 / (2.0 * 65535.0)
D50_TO_D65 = (
    (0.9555766, -0.0230393, 0.0631636),
    (-0.0282895, 1.0099416, 0.0210077),
    (0.0122982, -0.0204830, 1.3299098),
)
PCS_TO_LINEAR_SRGB = matmul(XYZ_D65_TO_SRGB, D50_TO_D65)
FIXED_CREATION_DATE = (2025, 1, 1, 0, 0, 0)

SIG_DESC = 0x64657363
SIG_B2A0 = 0x42324130
SIG_B2A1 = 0x42324131
SIG_RGB = 0x52474220
SIG_XYZ = 0x58595A20


class IccError(VividError):
    """Raised when an ICC profile cannot be generated or validated."""


class _CIExyY(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("Y", ctypes.c_double)]


class _CIExyYTRIPLE(ctypes.Structure):
    _fields_ = [
        ("Red", _CIExyY),
        ("Green", _CIExyY),
        ("Blue", _CIExyY),
    ]


class _Lcms:
    _instance: _Lcms | None = None

    def __init__(self, library: str | None = None) -> None:
        name = library or os.environ.get("VIVID_LCMS2") or ctypes.util.find_library("lcms2")
        if not name:
            name = "liblcms2.so.2"
        try:
            lib = ctypes.CDLL(name)
        except OSError as exc:
            raise IccError("Little CMS 2 (liblcms2) is required but could not be loaded") from exc
        vp = ctypes.c_void_p
        u16p = ctypes.POINTER(ctypes.c_uint16)
        dp = ctypes.POINTER(ctypes.c_double)
        fp = ctypes.POINTER(ctypes.c_float)
        u32p = ctypes.POINTER(ctypes.c_uint32)

        lib.cmsGetEncodedCMMversion.restype = ctypes.c_int
        lib.cmsGetEncodedCMMversion.argtypes = []
        lib.cmsBuildGamma.restype = vp
        lib.cmsBuildGamma.argtypes = [vp, ctypes.c_double]
        lib.cmsBuildTabulatedToneCurve16.restype = vp
        lib.cmsBuildTabulatedToneCurve16.argtypes = [vp, ctypes.c_uint32, u16p]
        lib.cmsCreateRGBProfile.restype = vp
        lib.cmsCreateRGBProfile.argtypes = [
            ctypes.POINTER(_CIExyY),
            ctypes.POINTER(_CIExyYTRIPLE),
            ctypes.POINTER(vp),
        ]
        lib.cmsSetProfileVersion.argtypes = [vp, ctypes.c_double]
        lib.cmsPipelineAlloc.restype = vp
        lib.cmsPipelineAlloc.argtypes = [vp, ctypes.c_uint32, ctypes.c_uint32]
        lib.cmsPipelineInsertStage.restype = ctypes.c_int
        lib.cmsPipelineInsertStage.argtypes = [vp, ctypes.c_int, vp]
        lib.cmsPipelineFree.argtypes = [vp]
        lib.cmsStageAllocMatrix.restype = vp
        lib.cmsStageAllocMatrix.argtypes = [vp, ctypes.c_uint32, ctypes.c_uint32, dp, dp]
        lib.cmsStageAllocToneCurves.restype = vp
        lib.cmsStageAllocToneCurves.argtypes = [vp, ctypes.c_uint32, ctypes.POINTER(vp)]
        lib.cmsStageAllocCLut16bit.restype = vp
        lib.cmsStageAllocCLut16bit.argtypes = [
            vp,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            u16p,
        ]
        lib.cmsMLUalloc.restype = vp
        lib.cmsMLUalloc.argtypes = [vp, ctypes.c_uint32]
        lib.cmsMLUsetASCII.restype = ctypes.c_int
        lib.cmsMLUsetASCII.argtypes = [vp, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.cmsWriteTag.restype = ctypes.c_int
        lib.cmsWriteTag.argtypes = [vp, ctypes.c_uint32, vp]
        lib.cmsSaveProfileToMem.restype = ctypes.c_int
        lib.cmsSaveProfileToMem.argtypes = [vp, ctypes.c_void_p, u32p]
        lib.cmsCloseProfile.restype = ctypes.c_int
        lib.cmsCloseProfile.argtypes = [vp]
        lib.cmsOpenProfileFromMem.restype = vp
        lib.cmsOpenProfileFromMem.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.cmsReadTag.restype = vp
        lib.cmsReadTag.argtypes = [vp, ctypes.c_uint32]
        lib.cmsPipelineEvalFloat.restype = None
        lib.cmsPipelineEvalFloat.argtypes = [fp, fp, vp]
        lib.cmsGetProfileInfoASCII.restype = ctypes.c_uint32
        lib.cmsGetProfileInfoASCII.argtypes = [
            vp,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        lib.cmsGetColorSpace.restype = ctypes.c_uint32
        lib.cmsGetColorSpace.argtypes = [vp]
        lib.cmsGetPCS.restype = ctypes.c_uint32
        lib.cmsGetPCS.argtypes = [vp]
        lib.cmsGetProfileVersion.restype = ctypes.c_double
        lib.cmsGetProfileVersion.argtypes = [vp]
        lib.cmsGetTagCount.restype = ctypes.c_uint32
        lib.cmsGetTagCount.argtypes = [vp]
        lib.cmsGetTagSignature.restype = ctypes.c_uint32
        lib.cmsGetTagSignature.argtypes = [vp, ctypes.c_uint32]
        self.lib = lib
        self.vp = vp

    @classmethod
    def get(cls) -> _Lcms:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def version(self) -> str:
        encoded = int(self.lib.cmsGetEncodedCMMversion())
        major, remainder = divmod(encoded, 1000)
        minor, patch = divmod(remainder, 10)
        return f"{major}.{minor}.{patch}"


def lcms_version() -> str:
    return _Lcms.get().version()


def _new_profile(lcms: _Lcms) -> int:
    lib = lcms.lib
    white = _CIExyY(
        D65_WHITEPOINT[0],
        D65_WHITEPOINT[1],
        1.0,
    )
    primaries = _CIExyYTRIPLE(
        *[_CIExyY(x, y, 1.0) for x, y in SRGB_PRIMARIES],
    )
    gamma = lib.cmsBuildGamma(None, 2.2)
    curves = (lcms.vp * 3)(gamma, gamma, gamma)
    profile = lib.cmsCreateRGBProfile(ctypes.byref(white), ctypes.byref(primaries), curves)
    if not profile:
        raise IccError("Little CMS could not create the base RGB profile")
    lib.cmsSetProfileVersion(profile, 2.1)
    return profile


def _write_description(lcms: _Lcms, profile: int, text: str) -> None:
    lib = lcms.lib
    mlu = lib.cmsMLUalloc(None, 1)
    if not mlu:
        raise IccError("Little CMS could not allocate a description string")
    if not lib.cmsMLUsetASCII(mlu, b"en", b"US", text.encode("ascii", "replace")):
        raise IccError("Little CMS could not set the profile description")
    if not lib.cmsWriteTag(profile, SIG_DESC, mlu):
        raise IccError("Little CMS could not write the profile description")


def _insert_stage(lcms: _Lcms, pipeline: int, stage: int) -> None:
    if not stage:
        raise IccError("Little CMS could not allocate a pipeline stage")
    if not lcms.lib.cmsPipelineInsertStage(pipeline, 1, stage):
        raise IccError("Little CMS could not append a pipeline stage")


def _build_b2a_pipeline(lcms: _Lcms, percent: int) -> int:
    lib = lcms.lib
    pipeline = lib.cmsPipelineAlloc(None, 3, 3)
    if not pipeline:
        raise IccError("Little CMS could not allocate a B2A pipeline")

    matrix = (ctypes.c_double * 9)(
        *[
            PCS_TO_LINEAR_SRGB[row][column] / KWIN_XYZ_SCALE
            for row in range(3)
            for column in range(3)
        ]
    )
    _insert_stage(lcms, pipeline, lib.cmsStageAllocMatrix(None, 3, 3, matrix, None))

    curve_values = (ctypes.c_uint16 * CURVE_SAMPLES)(*srgb_encode_curve_uint16())
    encode_curve = lib.cmsBuildTabulatedToneCurve16(None, CURVE_SAMPLES, curve_values)
    if not encode_curve:
        raise IccError("Little CMS could not build the sRGB encoding curve")
    curve_array = (lcms.vp * 3)(encode_curve, encode_curve, encode_curve)
    _insert_stage(lcms, pipeline, lib.cmsStageAllocToneCurves(None, 3, curve_array))

    clut_values = clut_uint16(percent, CLUT_GRID)
    clut = (ctypes.c_uint16 * len(clut_values))(*clut_values)
    _insert_stage(
        lcms,
        pipeline,
        lib.cmsStageAllocCLut16bit(None, CLUT_GRID, 3, 3, clut),
    )

    inverse_values = [
        int(
            round(
                max(0.0, min(1.0, (index / (CURVE_SAMPLES - 1)) * CLUT_SPAN - CLUT_OFFSET))
                * 65535.0
            )
        )
        for index in range(CURVE_SAMPLES)
    ]
    inverse_table = (ctypes.c_uint16 * CURVE_SAMPLES)(*inverse_values)
    inverse_curve = lib.cmsBuildTabulatedToneCurve16(None, CURVE_SAMPLES, inverse_table)
    if not inverse_curve:
        raise IccError("Little CMS could not build the output curve")
    inverse_array = (lcms.vp * 3)(inverse_curve, inverse_curve, inverse_curve)
    _insert_stage(lcms, pipeline, lib.cmsStageAllocToneCurves(None, 3, inverse_array))
    return pipeline


def _save_profile_to_bytes(lcms: _Lcms, profile: int) -> bytes:
    lib = lcms.lib
    size = ctypes.c_uint32(0)
    if not lib.cmsSaveProfileToMem(profile, None, ctypes.byref(size)):
        raise IccError("Little CMS could not measure the generated profile")
    if size.value < 132:
        raise IccError("Little CMS produced an implausibly short profile")
    buffer = ctypes.create_string_buffer(size.value)
    if not lib.cmsSaveProfileToMem(profile, buffer, ctypes.byref(size)):
        raise IccError("Little CMS could not serialise the generated profile")
    data = bytearray(buffer.raw[: size.value])
    if len(data) < 132:
        raise IccError("Little CMS produced an implausibly short profile")
    data[24:26] = FIXED_CREATION_DATE[0].to_bytes(2, "big")
    data[26:28] = FIXED_CREATION_DATE[1].to_bytes(2, "big")
    data[28:30] = FIXED_CREATION_DATE[2].to_bytes(2, "big")
    data[30:32] = FIXED_CREATION_DATE[3].to_bytes(2, "big")
    data[32:34] = FIXED_CREATION_DATE[4].to_bytes(2, "big")
    data[34:36] = FIXED_CREATION_DATE[5].to_bytes(2, "big")
    data[84:100] = b"\x00" * 16
    return bytes(data)


def generate_profile_bytes(percent: int) -> bytes:
    percent = validate_percent(percent)
    if percent == 0:
        raise IccError("0% is the sRGB baseline and does not need an ICC profile")
    lcms = _Lcms.get()
    lib = lcms.lib
    profile = _new_profile(lcms)
    pipeline = 0
    try:
        _write_description(lcms, profile, f"Vivid {percent:+d}% SDR saturation")
        pipeline = _build_b2a_pipeline(lcms, percent)
        if not lib.cmsWriteTag(profile, SIG_B2A0, pipeline):
            raise IccError("Little CMS could not write the perceptual B2A tag")
        if not lib.cmsWriteTag(profile, SIG_B2A1, pipeline):
            raise IccError("Little CMS could not write the colorimetric B2A tag")
        data = _save_profile_to_bytes(lcms, profile)
    finally:
        if pipeline:
            lib.cmsPipelineFree(pipeline)
        lib.cmsCloseProfile(profile)
    validation = validate_profile_bytes(data)
    errors = [issue for issue in validation["issues"] if issue["severity"] == "error"]
    if errors:
        raise IccError(f"generated profile failed validation: {errors[0]['message']}")
    return data


@dataclass(frozen=True)
class ProfileValidation:
    valid: bool
    description: str
    version: float
    color_space: str
    pcs: str
    tags: tuple[str, ...]
    issues: tuple[dict[str, str], ...]
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "description": self.description,
            "version": self.version,
            "color_space": self.color_space,
            "pcs": self.pcs,
            "tags": list(self.tags),
            "issues": list(self.issues),
            "sha256": self.sha256,
        }


def _signature(value: int) -> str:
    return value.to_bytes(4, "big").decode("ascii", "replace")


def _open_profile_from_bytes(data: bytes) -> int:
    lcms = _Lcms.get()
    buffer = ctypes.create_string_buffer(data)
    profile = lcms.lib.cmsOpenProfileFromMem(buffer, len(data))
    if not profile:
        raise IccError("Little CMS could not open the ICC profile")
    return profile


def validate_profile_bytes(data: bytes) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    sha = hashlib.sha256(data).hexdigest()
    if len(data) < 132:
        return ProfileValidation(
            valid=False,
            description="",
            version=0.0,
            color_space="",
            pcs="",
            tags=(),
            issues=({"severity": "error", "message": "profile is shorter than an ICC header"},),
            sha256=sha,
        ).to_dict()
    if data[36:40] != b"acsp":
        issues.append({"severity": "error", "message": "missing acsp signature"})
    profile = 0
    try:
        profile = _open_profile_from_bytes(data)
        lcms = _Lcms.get()
        lib = lcms.lib
        version = float(lib.cmsGetProfileVersion(profile))
        color_space = _signature(lib.cmsGetColorSpace(profile))
        pcs = _signature(lib.cmsGetPCS(profile))
        tag_count = int(lib.cmsGetTagCount(profile))
        tags = tuple(
            _signature(int(lib.cmsGetTagSignature(profile, index))) for index in range(tag_count)
        )
        description_buffer = ctypes.create_string_buffer(256)
        lib.cmsGetProfileInfoASCII(
            profile, 0, b"en", b"US", description_buffer, len(description_buffer)
        )
        description = description_buffer.value.decode("ascii", "replace")
        if color_space != "RGB ":
            issues.append(
                {"severity": "error", "message": f"unexpected colour space {color_space!r}"}
            )
        if pcs != "XYZ ":
            issues.append({"severity": "error", "message": f"unexpected PCS {pcs!r}"})
        for signature in ("B2A0", "B2A1"):
            if signature not in tags:
                issues.append({"severity": "error", "message": f"missing {signature} tag"})
            elif not lib.cmsReadTag(profile, SIG_B2A1 if signature == "B2A1" else SIG_B2A0):
                issues.append({"severity": "error", "message": f"{signature} tag is unreadable"})
        if tag_count > 64:
            issues.append({"severity": "warning", "message": "unusually large tag table"})
        return ProfileValidation(
            valid=not any(issue["severity"] == "error" for issue in issues),
            description=description,
            version=version,
            color_space=color_space,
            pcs=pcs,
            tags=tags,
            issues=tuple(issues),
            sha256=sha,
        ).to_dict()
    except IccError as exc:
        issues.append({"severity": "error", "message": str(exc)})
        return ProfileValidation(
            valid=False,
            description="",
            version=0.0,
            color_space="",
            pcs="",
            tags=(),
            issues=tuple(issues),
            sha256=sha,
        ).to_dict()
    finally:
        if profile:
            _Lcms.get().lib.cmsCloseProfile(profile)


def validate_profile_file(path: str | Path) -> dict[str, Any]:
    return validate_profile_bytes(Path(path).read_bytes())


def evaluate_profile_rgb(
    profile_path: str | Path, rgb: Sequence[float]
) -> tuple[float, float, float]:
    """Evaluate the KWin-facing B2A1 transform for an 8-bit-style sRGB colour."""
    if len(rgb) != 3:
        raise ValueError("rgb must contain exactly three components")
    profile = _open_profile_from_bytes(Path(profile_path).read_bytes())
    try:
        lcms = _Lcms.get()
        lib = lcms.lib
        pipeline = lib.cmsReadTag(profile, SIG_B2A1)
        if not pipeline:
            raise IccError("profile does not contain a readable B2A1 pipeline")
        linear = [srgb_decode(float(component)) for component in rgb]
        xyz_d65 = [
            sum(SRGB_TO_XYZ_D65[row][column] * linear[column] for column in range(3))
            for row in range(3)
        ]
        xyz_d50 = [
            sum(BRADFORD_D65_TO_D50[row][column] * xyz_d65[column] for column in range(3))
            for row in range(3)
        ]
        inputs = (ctypes.c_float * 3)(*[component * KWIN_XYZ_SCALE for component in xyz_d50])
        outputs = (ctypes.c_float * 3)()
        lib.cmsPipelineEvalFloat(inputs, outputs, pipeline)
        return (
            float(outputs[0]),
            float(outputs[1]),
            float(outputs[2]),
        )
    finally:
        _Lcms.get().lib.cmsCloseProfile(profile)


def transform_error_report(profile_path: str | Path, percent: int) -> dict[str, Any]:
    percent = validate_percent(percent)
    corpus = [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.5, 0.5, 0.5),
        (0.25, 0.25, 0.25),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.9, 0.1, 0.1),
        (0.1, 0.9, 0.1),
        (0.1, 0.1, 0.9),
        (0.2, 0.4, 0.8),
        (0.8, 0.4, 0.2),
        (0.05, 0.1, 0.2),
        (0.95, 0.85, 0.1),
        (0.33, 0.66, 0.5),
        (0.6, 0.2, 0.9),
    ]
    errors: list[float] = []
    neutral_errors: list[float] = []
    worst = ("", 0.0)
    for rgb in corpus:
        actual = evaluate_profile_rgb(profile_path, rgb)
        expected = apply_percent(rgb, percent)
        channel_errors = [abs(actual[index] - expected[index]) for index in range(3)]
        for error in channel_errors:
            errors.append(error)
        maximum = max(channel_errors)
        if maximum > worst[1]:
            worst = (repr(rgb), maximum)
        if rgb[0] == rgb[1] == rgb[2]:
            neutral_errors.extend(channel_errors)
    mean_error = sum(errors) / len(errors) if errors else 0.0
    max_error = max(errors) if errors else 0.0
    neutral_max = max(neutral_errors) if neutral_errors else 0.0
    mean_code = mean_error * 255.0
    max_code = max_error * 255.0
    neutral_code = neutral_max * 255.0
    return {
        "percent": percent,
        "samples": len(corpus),
        "mean_absolute_error": mean_error,
        "max_absolute_error": max_error,
        "mean_absolute_error_8bit": mean_code,
        "max_absolute_error_8bit": max_code,
        "neutral_max_error_8bit": neutral_code,
        "worst_sample": worst[0],
        "mean_below_one_code": mean_code < 1.0,
        "neutral_below_one_code": neutral_code < 1.0,
        "within_tolerance": mean_code < 1.0 and max_code < 4.0 and neutral_code < 1.0,
        "lcms_version": lcms_version(),
    }


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return (cleaned or "display")[:64]


def profile_prefix(stable_id: str) -> str:
    return f"vivid-{_safe_component(stable_id)}-"


def profile_filename(stable_id: str, percent: int, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{profile_prefix(stable_id)}{percent:+04d}-{digest}.icc"


def write_profile(
    percent: int,
    stable_id: str,
    directory: str | Path,
    data: bytes | None = None,
) -> Path:
    percent = validate_percent(percent)
    if percent == 0:
        raise IccError("0% is the sRGB baseline and does not need an ICC profile")
    profile_data = data if data is not None else generate_profile_bytes(percent)
    validation = validate_profile_bytes(profile_data)
    if not validation["valid"]:
        raise IccError("refusing to write an invalid ICC profile")
    target_dir = Path(directory).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = profile_filename(stable_id, percent, profile_data)
    target = target_dir / filename
    if target.exists():
        existing = target.read_bytes()
        if hashlib.sha256(existing).hexdigest() == hashlib.sha256(profile_data).hexdigest():
            return target
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=".vivid-", suffix=".icc.tmp", dir=target_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(temporary_fd, "wb") as handle:
            handle.write(profile_data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        directory_fd = os.open(target_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    written = validate_profile_file(target)
    if not written["valid"]:
        raise IccError("ICC profile failed validation after writing")
    return target


def cleanup_for_display(
    directory: str | Path, stable_id: str, keep: str | Path | None
) -> list[Path]:
    target_dir = Path(directory).expanduser()
    if not target_dir.exists():
        return []
    prefix = profile_prefix(stable_id)
    keep_path = Path(keep).resolve() if keep else None
    removed: list[Path] = []
    for path in target_dir.glob(f"{prefix}*.icc"):
        if keep_path is not None and path.resolve() == keep_path:
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed


def prune_cache(
    directory: str | Path,
    keep: Iterable[str | Path],
    max_age_seconds: float | None = None,
) -> list[Path]:
    target_dir = Path(directory).expanduser()
    if not target_dir.exists():
        return []
    import time

    keep_paths = {Path(item).resolve() for item in keep}
    removed: list[Path] = []
    now = time.time()
    for path in target_dir.glob("vivid-*.icc"):
        if path.resolve() in keep_paths:
            continue
        try:
            if max_age_seconds is not None and now - path.stat().st_mtime < max_age_seconds:
                continue
            path.unlink()
            removed.append(path)
        except OSError:
            continue
    return removed
