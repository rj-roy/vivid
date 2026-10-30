# Compatibility

Vivid supports independent per-output saturation only when KWin exposes the
required per-output ICC and colour-source controls through KScreen. Capability
detection is deliberately conservative: the application reports unsupported
rather than falling back to a global effect.

## Requirement matrix

| Environment | Result |
| --- | --- |
| Fedora KDE, verified Plasma version, AMD Radeon, Wayland, two displays | Intended per-monitor adjustment; verify behavior on the target hardware |
| Fedora KDE, one display | Single-display adjustment; no independent two-output evidence |
| Fedora KDE, two or more displays | Independent adjustment per output where identity is unambiguous |
| Wayland with a compositor other than KWin | Unsupported with a clear reason |
| X11 session | Unsupported |
| HDR output | Unsupported |
| KScreen without `iccprofile` / `colorProfileSource` | Unsupported with a clear reason |
| KScreen unavailable or no outputs | Unsupported; discovery error |
| Monitor hotplug | Saved preferences reapplied when stable identity can be matched |
| Monitor without stable identity | Ambiguous; automatic restoration disabled until explicit confirmation |
| Duplicate EDID and no UUID | Ambiguous; explicit confirmation required |
| Missing or unreadable Little CMS 2 | Unsupported; profile generation disabled |

## Verified development environment

These versions were used to validate parsing, capability detection, profile
generation, simulated backend behaviour, and read-only live discovery:

| Component | Version |
| --- | --- |
| Fedora Linux | 44 |
| KDE Plasma | 6.7.5 |
| KWin | 6.7.5 |
| KScreen | 6.7.5-1.fc44 |
| Python | 3.14.8 |
| PySide6 | 6.11.2 |
| Little CMS | 2.16.0 |

The live session reported two outputs: an internal `eDP-1` panel and an external
`HDMI-A-1` monitor. `vivid backend` reported `Supported: yes`, and `vivid list`
reported both outputs as active with ICC profile support.

This evidence proves that the interfaces are present and discovery works. It is
not evidence that a particular profile produces the intended physical output.
Validate the result on the target displays, ideally with controlled test images
or a colorimeter, before relying on independent physical output behavior.

## Expected but unverified

- Plasma 6.8 and newer when the same KScreen arguments and JSON fields are
  available. Vivid emits a warning for Plasma versions outside the verified set.
- Intel and NVIDIA graphics when KWin and KScreen expose the same interfaces.
- AMD discrete GPUs; the primary target is an AMD laptop with an external monitor.
- Multiple external monitors, subject to the same identity rules.

No unverified configuration is described as tested merely because the
application starts.

## Unsupported

- X11/Xorg sessions.
- GNOME, COSMIC, Sway, and other compositors.
- HDR output and HDR-specific colour pipelines.
- Global saturation, global gamma, or global shader adjustment.
- Per-application or per-game colour control.
- Monitor firmware changes, GPU overclocking, or driver modification.
- Running routine operations as root.
- Custom Wayland compositors or privileged GPU driver workarounds.
- Colourimeter-grade calibration; Vivid is an adjustment tool, not a calibration
  system.

## Known limitations

- The user-facing value is an adjustment scale, not a calibrated percentage of
  perceived saturation. `-100` is grayscale, `0` is baseline, and `+100` is
  approximately twice the baseline saturation in the gamma-encoded RGB transform.
- The transform clips to the displayable RGB range.
- Applications with their own colour-management pipeline may not show the same
  result.
- KWin runs the ICC shader, including the B2A CLUT, only when the output prefers
  colour accuracy. Vivid sets and verifies that preference while an adjustment is
  active, then restores the recorded original.
- A monitor with a duplicate EDID and no usable UUID is treated as ambiguous.
  Vivid will not restore it automatically.
- If the original ICC file has been deleted, KScreen may reject the restore.
  Vivid reports the failure and preserves the snapshot.
- A disconnected display can prevent a full uninstall restore. Reconnect it and
  run `vivid uninstall` again.
- Plasma or KScreen argument changes can break the backend. Capability detection
  is conservative, but future releases must still be verified.

## Reporting a compatibility result

When reporting a compatibility result, include:

```bash
vivid --version
vivid backend --json
vivid doctor --json
rpm -q plasma-workspace kwin kscreen lcms2
```

State whether the test was read-only or destructive, how many physical displays
were active, and whether the second display's colour state was unchanged. Do not
report a release as verified based on mocks or a single output.
