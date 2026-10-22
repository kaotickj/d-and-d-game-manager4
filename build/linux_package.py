"""Package an existing Linux amd64 PyInstaller onedir bundle; never install it."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

APP = "DnDGameManager4"
MAX_FILES = 20000
MAX_BYTES = 2 * 1024 * 1024 * 1024
# Runtime names follow Qt's X11 requirements, not development packages:
# https://doc.qt.io/qt-6/linux-requirements.html
DEPENDS = ("libc6 (>= 2.35)", "libegl1", "libopengl0", "libgl1", "libglib2.0-0",
    "libfontconfig1", "libfreetype6", "fonts-dejavu-core", "libdbus-1-3", "libx11-6", "libx11-xcb1",
    "libxext6", "libxrender1", "libxi6", "libxfixes3", "libxkbcommon0", "libxkbcommon-x11-0",
    "libxcb1", "libxcb-cursor0", "libxcb-glx0", "libxcb-icccm4", "libxcb-image0",
    "libxcb-keysyms1", "libxcb-randr0", "libxcb-render0", "libxcb-render-util0",
    "libxcb-shape0", "libxcb-shm0", "libxcb-sync1", "libxcb-util1", "libxcb-xfixes0", "libxcb-xkb1")
FORBIDDEN_NAMES = {".git", ".ssh", ".aws", ".env", "credentials", "credentials.json", "secrets.json",
    "id_rsa", "id_ed25519", "home", "userdata", "user_data", "appdata", "current_scene.json",
    "battle_trakker.json", "srd35_spells.json", "rules.sqlite3", "library.sqlite3"}
DATA_SUFFIXES = {".zip", ".py", ".pyc", ".json", ".txt", ".md", ".rst", ".ini", ".cfg", ".conf",
    ".xml", ".html", ".css", ".js", ".qml", ".qsb", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".icns",
    ".rcc", ".qm", ".ttf", ".otf", ".woff", ".woff2", ".pak", ".dat", ".typelib", ".hmac"}
DATA_NAMES = {"LICENSE", "COPYING", "NOTICE", "AUTHORS", "WHEEL", "METADATA", "RECORD", "INSTALLER",
              "py.typed", "cacert.pem"}


def _runtime_file(name: str) -> bool:
    return (Path(name).suffix.casefold() in DATA_SUFFIXES or name in DATA_NAMES
            or re.search(r"\.so(?:\.[0-9]+)*$", name) is not None)


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_bundle(bundle: Path) -> int:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("--bundle must be a regular prebuilt PyInstaller onedir directory.")
    if {path.name for path in bundle.iterdir()} != {APP, "_internal"}:
        raise ValueError(f"Bundle root may contain only {APP} and _internal/.")
    executable = bundle / APP
    if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("The bundled application must be a regular executable.")
    with executable.open("rb") as stream:
        header = stream.read(20)
    if (len(header) < 20 or header[:6] != b"\x7fELF\x02\x01"
            or struct.unpack("<H", header[18:20])[0] != 62):
        raise ValueError("The bundled application must be a Linux ELF64 amd64 executable.")
    if (bundle / "_internal").is_symlink() or not (bundle / "_internal").is_dir():
        raise ValueError("_internal must be a regular runtime directory.")
    total = count = 0
    for path in bundle.rglob("*"):
        count += 1
        if count > MAX_FILES:
            raise ValueError("Prebuilt bundle exceeds its file/size limit.")
        relative = path.relative_to(bundle)
        if any(part.casefold() in FORBIDDEN_NAMES for part in relative.parts):
            raise ValueError(f"Private or user-data artifact in bundle: {relative}")
        if any(ord(char) < 32 or char == "\\" for char in relative.as_posix()):
            raise ValueError(f"Unsafe bundle path: {relative!s}")
        if path.is_symlink():
            target = os.readlink(path)
            if os.path.isabs(target) or not path.resolve(strict=True).is_relative_to(bundle):
                raise ValueError(f"Bundle link must stay relative and inside the bundle: {relative}")
            if path.is_file() and not _runtime_file(path.name):
                raise ValueError(f"Link is outside the bundled runtime allowlist: {relative}")
            continue
        if path.is_dir():
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError(f"Unsupported special file or external hard link: {relative}")
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ValueError("Prebuilt bundle exceeds its file/size limit.")
        if path == executable:
            continue
        if not _runtime_file(path.name):
            raise ValueError(f"File is outside the bundled runtime allowlist: {relative}")
    return total


def build_package(bundle: Path, output: Path, version: str, *, portable: bool = False) -> dict:
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[+~.-][A-Za-z0-9.]+)?", version) is None:
        raise ValueError("Version must be a safe Debian-compatible release version, for example 0.10.0.")
    if bundle.is_symlink():
        raise ValueError("--bundle cannot be a symbolic link.")
    bundle, output = bundle.resolve(), output.resolve()
    if output == bundle or output.is_relative_to(bundle):
        raise ValueError("--output must be outside the prebuilt bundle.")
    installed_bytes = validate_bundle(bundle)
    dpkg = shutil.which("dpkg-deb")
    if dpkg is None:
        raise ValueError("Existing dpkg-deb is required; this script never installs software.")
    icon = Path(__file__).resolve().parents[1] / "dndgm4" / "assets" / "dragon_crest.png"
    icon_bytes = icon.read_bytes()
    if icon_bytes[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", icon_bytes[16:24]) != (256, 256):
        raise ValueError("The original 256x256 dragon crest package icon is missing or invalid.")
    names = [f"dndgm4_{version}_amd64.deb"]
    if portable:
        names.append(f"dndgm4-{version}-linux-amd64.tar.gz")
    names.append("SHA256SUMS")
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() or (output / name).is_symlink() for name in names):
        raise ValueError("Output artifacts already exist; use a fresh output directory.")
    with tempfile.TemporaryDirectory(prefix=".linux-package-", dir=output) as temporary:
        temporary = Path(temporary)
        stage = temporary / "package"
        app = stage / "opt" / "dndgm4"
        shutil.copytree(bundle, app, symlinks=True)
        validate_bundle(app)
        metadata = {
            "DEBIAN/control": f"Package: dndgm4\nVersion: {version}\nArchitecture: amd64\n"
                "Maintainer: KaotickJay\nSection: games\nPriority: optional\n"
                f"Installed-Size: {(installed_bytes + 1023) // 1024}\n"
                f"Depends: {', '.join(DEPENDS)}\n"
                "Homepage: https://github.com/kaotickj/d-and-d-game-manager4\n"
                "Description: Dungeons and Dragons 3.5 campaign manager\n"
                " Campaigns, sessions, encounters, rules references, and local DM tools.\n",
            "usr/bin/dndgm4": '#!/bin/sh\nexec "/opt/dndgm4/DnDGameManager4" "$@"\n',
            "usr/share/applications/dndgm4.desktop": "[Desktop Entry]\nType=Application\n"
                "Name=D&D Game Manager 4\nComment=Manage Dungeons and Dragons campaigns\n"
                "Exec=/usr/bin/dndgm4\nIcon=dndgm4\nTerminal=false\nCategories=Game;RolePlaying;\n"
                "Keywords=Dungeons;Dragons;Campaign;RPG;\n",
        }
        for relative, content in metadata.items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755 if relative == "usr/bin/dndgm4" else 0o644)
        icon_path = stage / "usr/share/icons/hicolor/256x256/apps/dndgm4.png"
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        icon_path.write_bytes(icon_bytes)
        for path in (stage, *stage.rglob("*")):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        result = subprocess.run([dpkg, "--root-owner-group", "-Zxz", "--build", str(stage), str(temporary / names[0])],
                                capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise ValueError(f"dpkg-deb failed: {result.stderr.strip() or result.stdout.strip()}")
        if portable:
            with tarfile.open(temporary / names[1], "w:gz", dereference=False) as archive:
                def normalize(info):
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    return info
                archive.add(app, arcname=APP, recursive=True, filter=normalize)
        hashes = {name: _digest(temporary / name) for name in names[:-1]}
        (temporary / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in hashes.items()), encoding="ascii")
        for name in names:
            os.replace(temporary / name, output / name)
    return {"files": [str(output / name) for name in names], "sha256": hashes}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", default=Path("dist"), type=Path)
    parser.add_argument("--version", default="0.10.0")
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_package(args.bundle, args.output, args.version, portable=args.portable)
    except (OSError, ValueError, subprocess.SubprocessError, struct.error) as exc:
        print(f"Linux package FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
