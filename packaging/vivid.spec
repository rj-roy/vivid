%global debug_package %{nil}

Name:           vivid
Version:        1.0.0
Release:        1%{?dist}
Summary:        Independent per-display saturation control for KDE Plasma Wayland
License:        MIT
URL:            https://github.com/rj-roy/vivid
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  python3-devel
BuildRequires:  python3dist(setuptools)
BuildRequires:  python3dist(wheel)
BuildRequires:  pyproject-rpm-macros

Requires:       hicolor-icon-theme
Requires:       kwin
Requires:       lcms2
Requires:       libkscreen
Requires:       plasma-workspace
Requires:       plasma5support
Requires:       python3
Requires:       python3-pyside6

%description
Vivid adjusts the colour saturation of each physical display independently on
KDE Plasma Wayland. It generates a synthetic ICC profile for the selected
output, assigns it through KScreen, and verifies that KWin reports the new
per-output colour state before claiming success.

Changing one monitor does not change another. Settings are stored per physical
display and restored after login, reboot, or monitor reconnection. Vivid records
the original profile assignment before the first change and restores it on reset
or uninstall.

Vivid requires KDE Plasma 6 on a native Wayland session. It does not use root
privileges, a global shader, xrandr, or a generic sRGB fallback. HDR output is
not supported.

%prep
%autosetup -n %{name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files vivid

install -Dpm0644 packaging/vivid.desktop \
  %{buildroot}%{_datadir}/applications/io.github.vivid.DisplaySaturation.desktop
install -Dpm0644 packaging/io.github.vivid.DisplaySaturation.metainfo.xml \
  %{buildroot}%{_datadir}/metainfo/io.github.vivid.DisplaySaturation.metainfo.xml
install -Dpm0644 packaging/icons/hicolor/scalable/apps/io.github.vivid.DisplaySaturation.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.vivid.DisplaySaturation.svg
install -Dpm0644 packaging/plasmoid/metadata.json \
  %{buildroot}%{_datadir}/plasma/plasmoids/io.github.vivid.DisplaySaturation/metadata.json
install -Dpm0644 packaging/plasmoid/contents/ui/main.qml \
  %{buildroot}%{_datadir}/plasma/plasmoids/io.github.vivid.DisplaySaturation/contents/ui/main.qml

%check
desktop-file-validate packaging/vivid.desktop

%files -f %{pyproject_files}
%license LICENSE
%doc README.md SECURITY.md
%doc docs/COMPATIBILITY.md docs/INSTALLATION.md docs/RECOVERY.md
%doc docs/TROUBLESHOOTING.md docs/CLI.md
%{_bindir}/vivid
%{_bindir}/vivid-gui
%{_datadir}/applications/io.github.vivid.DisplaySaturation.desktop
%{_datadir}/metainfo/io.github.vivid.DisplaySaturation.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.vivid.DisplaySaturation.svg
%{_datadir}/plasma/plasmoids/io.github.vivid.DisplaySaturation/

%changelog
* Fri Oct 30 2026 Vivid contributors <vivid@localhost> - 1.0.0-1
- Initial release: per-display KWin ICC backend, GUI, CLI, recovery, and docs.
