# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |
| Older or unreleased snapshots | No |

## Reporting a vulnerability

Do not open a public issue for a vulnerability. Use GitHub's private
vulnerability reporting for this repository:

https://github.com/rj-roy/vivid/security/advisories/new

Include:

- The affected version and commit.
- Fedora, Plasma, KWin, KScreen, Python, PySide6, and Little CMS versions.
- Whether the issue requires a malicious local user, a crafted settings file, a
  crafted ICC profile, or physical access.
- Reproduction steps and the expected impact.
- Relevant log excerpts with personal information removed.

If the private advisory form is unavailable, contact the maintainers through the
repository's listed maintainer contact and ask for a private channel before
sharing details.

## Scope

Vivid runs as the logged-in user and does not require root. Security-relevant
areas include:

- Parsing KScreen JSON, KWin configuration, EDID data, settings JSON, recovery
  JSON, and ICC files.
- Writing settings, recovery state, logs, and generated profiles with safe
  permissions.
- Invoking `kscreen-doctor` with output names and profile paths derived from
  display data.
- Loading `liblcms2` through `ctypes`.
- Importing PySide6 for the graphical interface.
- Restoring display state during reset and uninstall.

## Security properties

- Settings and recovery files are written atomically with mode `0600` and
  directory mode `0700` where possible.
- Generated profiles are written atomically and validated before and after
  writing.
- Vivid does not disable SELinux or system security controls.
- Vivid does not change system-wide colour configuration.
- Vivid does not use `sudo` for routine operation.
- Vivid does not download profiles or require network access at runtime.
- Uninstall stops if display restoration fails and preserves recovery data.

## Out of scope

- A user intentionally editing their own settings or recovery files.
- A compromised local account, compositor, kernel, or system library.
- Denial of service caused by removing required Fedora packages.
- Colour accuracy claims or monitor calibration disputes.

## Disclosure

Maintainers will acknowledge a report as soon as practical, investigate it, and
coordinate a fix and disclosure timeline with the reporter. Credit is given
unless the reporter requests anonymity.
