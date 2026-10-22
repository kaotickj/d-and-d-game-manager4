#!/usr/bin/env bash
# Install/remove acceptance belongs only on the disposable GitHub Actions host.
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: bash build/linux_acceptance.sh --package FILE.deb --bundle-exe FILE [--report-root DIR]

Creates a fresh run-* directory (default root: dist/linux-acceptance), checks
the bundle, installs/reinstalls dndgm4, checks its launcher, then removes/purges
it. All GUI checks run under Xvfb with the native xcb platform. Requires the
disposable GitHub Actions Linux runner and passwordless sudo. Never run on a
personal machine. HOME is inherited unchanged; test data uses isolated XDG dirs.
USAGE
}

fail() { printf 'Linux acceptance FAILED: %s\n' "$*" >&2; exit 1; }
package=''
bundle_exe=''
report_root='dist/linux-acceptance'
while (($#)); do
    case "$1" in
        --package|--bundle-exe|--report-root)
            (($# >= 2)) || fail "Missing value for $1"
            case "$1" in
                --package) package=$2 ;;
                --bundle-exe) bundle_exe=$2 ;;
                --report-root) report_root=$2 ;;
            esac
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; fail "Unknown argument: $1" ;;
    esac
done
[[ -n "$package" && -n "$bundle_exe" ]] || { usage >&2; fail 'Package and bundle executable are required.'; }
[[ ${GITHUB_ACTIONS:-} == true && ${RUNNER_OS:-} == Linux ]] || fail 'Installation acceptance requires a disposable GitHub Actions Linux runner.'
for tool in python3 sudo dpkg dpkg-deb dpkg-query timeout xvfb-run mktemp realpath; do
    command -v "$tool" >/dev/null || fail "Required runner tool is unavailable: $tool"
done
[[ -f "$package" && ! -L "$package" ]] || fail 'Package must be a regular .deb file.'
[[ -f "$bundle_exe" && -x "$bundle_exe" && ! -L "$bundle_exe" ]] || fail 'Bundle executable is missing or not executable.'
package=$(realpath -- "$package")
bundle_exe=$(realpath -- "$bundle_exe")
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repository_directory=$(dirname -- "$script_directory")
fixture_script="$script_directory/windows_upgrade_fixture.py"
[[ -f "$fixture_script" ]] || fail 'Isolated upgrade fixture helper is missing.'
[[ $(dpkg-deb --field "$package" Package) == dndgm4 ]] || fail 'Unexpected Debian package name.'
[[ $(dpkg-deb --field "$package" Version) == 0.10.0 ]] || fail 'Unexpected Debian package version.'
[[ $(dpkg-deb --field "$package" Architecture) == "$(dpkg --print-architecture)" ]] || fail 'Package architecture does not match the runner.'
if dpkg-query --show dndgm4 >/dev/null 2>&1; then
    fail 'Refusing to replace/remove a package already present before this acceptance run.'
fi
sudo -n true || fail 'Passwordless sudo is required on the disposable runner.'
[[ ! -L "$report_root" ]] || fail 'Report root cannot be a symbolic link.'
mkdir -p -- "$report_root"
report_root=$(realpath -- "$report_root")
report_directory=$(mktemp -d "$report_root/run-XXXXXXXXXXXX")
printf 'Linux acceptance evidence: %s\n' "$report_directory"
profile_root="$report_directory/retained-profile"
fixture_report="$report_directory/retained-library.json"
original_home=${HOME:?HOME must remain unchanged}
mkdir -- "$report_directory/isolated-config" "$report_directory/isolated-cache" "$report_directory/isolated-runtime"
chmod 700 -- "$report_directory/isolated-runtime"
trap 'printf "Linux acceptance stopped; evidence retained at %s\n" "$report_directory" >&2' ERR

check_preserved() {
    local phase=$1
    python3 "$fixture_script" check "$profile_root" "$fixture_report" > "$report_directory/$phase-data-preservation.json"
    [[ $HOME == "$original_home" ]] || fail 'HOME changed during acceptance.'
}

validate_smoke() {
    local report=$1
    python3 - "$report" <<'PY'
from pathlib import Path
import json
import struct
import sys
import zlib

report_path = Path(sys.argv[1])
def require(condition, message):
    if not condition:
        raise SystemExit("Linux smoke validation FAILED: " + message)

require(report_path.is_file() and not report_path.is_symlink(), "report is missing or linked")
require(report_path.stat().st_size <= 8 * 1024 * 1024, "report exceeds limit")
report = json.loads(report_path.read_text(encoding="utf-8"))
require(report.get("status") == "passed" and report.get("errors") == [], "application reported a failure")
require(report.get("frozen") is True and report.get("platform", "").startswith("Linux"), "report is not from a frozen Linux application")
require(report.get("app_version") == "0.10.0", "application version differs from package")
require(report.get("temporary_data_removed") is True, "smoke temporary game data remains")
qt = report.get("qt", {})
require(qt.get("backend") == "xcb", "GUI did not use native xcb")
require(all(isinstance(qt.get(key), str) and qt[key] for key in
            ("qt_version", "pyqt_version", "application_font_family")), "Qt/font metadata is missing")
checks = report.get("checks", [])
required_checks = {
    "packaged_artwork_and_svg", "create_core_v3_fixture", "v3_to_current_migration",
    "new_campaign_tools_saved_state", "main_window_desktop", "main_window_830x540",
    "render_campaign", "render_world", "render_map", "render_player-map", "render_time",
    "render_resources", "render_reviewed-drafts", "render_handouts", "render_player-handout",
    "render_spells", "render_multiclass", "complete_backup", "restore_to_new_folder",
    "reopened_restored_core_records", "restored_campaign_tools_and_assets", "restart_restored_main_window",
}
require(isinstance(checks, list) and len(checks) == 22, "expected exactly 22 checks")
require(all(isinstance(check, dict) and check.get("status") == "passed" for check in checks), "one or more checks did not pass")
require({check.get("name") for check in checks} == required_checks, "check coverage differs from the required release gates")
art = next(check for check in checks if check["name"] == "packaged_artwork_and_svg")["details"]
font = art.get("font", {})
probe = "D&D Game Manager 4"
glyphs = font.get("glyph_indexes", [])
require(font.get("probe") == probe and isinstance(glyphs, list) and len(glyphs) == len(probe), "font probe is missing")
require(all(type(glyphs[index]) is int and glyphs[index] > 0 for index, character in enumerate(probe) if not character.isspace()), "ASCII font glyphs are missing")
require(font.get("backend") == "xcb" and font.get("qt_version") == qt["qt_version"], "font check used a different backend/runtime")
require(isinstance(font.get("resolved_font_family"), str) and bool(font["resolved_font_family"]), "resolved font family is missing")
require("svg" in art.get("qt_image_formats", []), "Qt SVG decoder is missing")
required_assets = {"app_banner.jpg", "dragon_crest.png", "name_genie_crest.png", "app_icon.ico", "checkmark.svg", "chevron_up.svg", "chevron_down.svg"}
require(set(art.get("assets", [])) == required_assets, "packaged artwork coverage is incomplete")
screenshots = report.get("screenshots", [])
expected_names = {name + ".png" for name in ("main-desktop", "main-compact", "campaign", "world", "map", "player-map", "time", "resources", "reviewed-drafts", "handouts", "player-handout", "spells", "multiclass", "restored-main")}
require(isinstance(screenshots, list) and len(screenshots) == 14 and len(set(screenshots)) == 14, "expected 14 distinct PNG captures")
capture_root = report_path.with_name(report_path.stem + "-screenshots").resolve()
require({Path(name).name for name in screenshots} == expected_names, "capture coverage is incomplete")
for filename in screenshots:
    path = Path(filename)
    require(path.is_absolute() and path.is_file() and not path.is_symlink() and path.resolve().parent == capture_root, "capture is missing, linked, or outside the evidence directory")
    require(0 < path.stat().st_size <= 25 * 1024 * 1024, "capture exceeds its bounded size")
    payload = path.read_bytes()
    require(payload[:8] == b"\x89PNG\r\n\x1a\n", "capture has no PNG signature")
    cursor, dimensions, compressed, ended = 8, None, bytearray(), False
    while cursor < len(payload):
        require(cursor + 12 <= len(payload), "PNG chunk is truncated")
        length = struct.unpack(">I", payload[cursor:cursor + 4])[0]
        kind = payload[cursor + 4:cursor + 8]
        require(cursor + 12 + length <= len(payload), "PNG chunk payload is truncated")
        data = payload[cursor + 8:cursor + 8 + length]
        checksum = struct.unpack(">I", payload[cursor + 8 + length:cursor + 12 + length])[0]
        require((zlib.crc32(kind + data) & 0xffffffff) == checksum, "PNG chunk checksum differs")
        if kind == b"IHDR":
            require(cursor == 8 and length == 13, "PNG header is invalid")
            dimensions = struct.unpack(">II", data[:8])
            require(all(0 < edge <= 10000 for edge in dimensions), "PNG dimensions are invalid")
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            require(length == 0 and cursor + 12 == len(payload), "PNG has an invalid ending")
            ended = True
        cursor += length + 12
    require(dimensions is not None and compressed and ended, "PNG image chunks are incomplete")
    decoded = zlib.decompressobj()
    pixels = decoded.decompress(bytes(compressed), 80 * 1024 * 1024 + 1)
    require(decoded.eof and not decoded.unused_data and len(pixels) <= 80 * 1024 * 1024 and len(pixels) > dimensions[1], "PNG pixel stream is incomplete or exceeds limit")
print(json.dumps({"status": "passed", "report": str(report_path), "checks": 22,
                  "screenshots": 14, "backend": "xcb", "font": font["resolved_font_family"],
                  "app_version": report["app_version"]}))
PY
}

run_smoke() {
    local phase=$1 executable=$2
    local report="$report_directory/$phase.json"
    if env XDG_DATA_HOME="$profile_root" XDG_CONFIG_HOME="$report_directory/isolated-config" \
        XDG_CACHE_HOME="$report_directory/isolated-cache" XDG_RUNTIME_DIR="$report_directory/isolated-runtime" \
        QT_QPA_PLATFORM=xcb timeout --signal=TERM --kill-after=5s 120s \
        xvfb-run -a -s '-screen 0 1920x1080x24' "$executable" --smoke-test "$report" \
        > "$report_directory/$phase-process.log" 2>&1; then
        :
    else
        local status=$?
        cat "$report_directory/$phase-process.log" >&2
        fail "$phase application failed or timed out (exit $status)."
    fi
    validate_smoke "$report" > "$report_directory/$phase-validation.json"
    cat "$report_directory/$phase-validation.json"
    check_preserved "$phase-after-smoke"
}

verify_package_files() {
    local phase=$1
    dpkg-query --listfiles dndgm4 > "$report_directory/$phase-package-files.txt"
    python3 - "$repository_directory" "$report_directory/$phase-package-files.txt" <<'PY'
from pathlib import Path
import hashlib
import json
import sys
root = Path(sys.argv[1])
listed = set(Path(sys.argv[2]).read_text().splitlines())
paths = ("/opt/dndgm4/DnDGameManager4", "/usr/bin/dndgm4", "/usr/share/applications/dndgm4.desktop", "/usr/share/icons/hicolor/256x256/apps/dndgm4.png")
for name in paths:
    path = Path(name)
    if name not in listed or not path.is_file() or path.is_symlink():
        raise SystemExit("Package entry is missing, unowned, or linked: " + name)
if not all(Path(name).stat().st_mode & 0o111 for name in paths[:2]):
    raise SystemExit("Package launcher/binary is not executable")
launcher = Path(paths[1]).read_text(encoding="utf-8")
if launcher != '#!/bin/sh\nexec "/opt/dndgm4/DnDGameManager4" "$@"\n':
    raise SystemExit("Launcher does not execute the installed binary with forwarded arguments")
desktop = dict(line.split("=", 1) for line in Path(paths[2]).read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
for key, value in {"Exec": "/usr/bin/dndgm4", "Icon": "dndgm4", "Type": "Application", "Terminal": "false", "Categories": "Game;RolePlaying;"}.items():
    if desktop.get(key) != value:
        raise SystemExit("Incorrect desktop entry: " + key)
icon = Path(paths[3]).read_bytes()
if icon != (root / "dndgm4/assets/dragon_crest.png").read_bytes():
    raise SystemExit("Installed desktop icon differs from the original bundled artwork")
print(json.dumps({"status": "passed", "package_files": list(paths), "icon_sha256": hashlib.sha256(icon).hexdigest()}))
PY
}

python3 "$fixture_script" seed "$profile_root" "$fixture_report" > "$report_directory/fixture-seed.json"
run_smoke bundled "$bundle_exe"
for phase in installed reinstalled; do
    timeout --signal=TERM --kill-after=10s 120s sudo -n dpkg --install "$package" > "$report_directory/$phase-dpkg.log" 2>&1
    check_preserved "$phase"
    verify_package_files "$phase" > "$report_directory/$phase-package-validation.json"
    run_smoke "$phase" /usr/bin/dndgm4
done
timeout --signal=TERM --kill-after=10s 120s sudo -n dpkg --remove dndgm4 > "$report_directory/removed-dpkg.log" 2>&1
check_preserved removed
timeout --signal=TERM --kill-after=10s 120s sudo -n dpkg --purge dndgm4 > "$report_directory/purged-dpkg.log" 2>&1
check_preserved purged
for name in /opt/dndgm4/DnDGameManager4 /usr/bin/dndgm4 /usr/share/applications/dndgm4.desktop /usr/share/icons/hicolor/256x256/apps/dndgm4.png; do
    [[ ! -e "$name" && ! -L "$name" ]] || fail "Package file remains after purge: $name"
done
printf '{"status":"passed","bundled":true,"installed":true,"reinstalled":true,"removed":true,"purged":true,"retained_fixture_unchanged":true}\n' > "$report_directory/acceptance-summary.json"
printf 'Linux acceptance PASSED; evidence retained at %s\n' "$report_directory"
