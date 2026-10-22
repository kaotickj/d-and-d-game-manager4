"""Real dpkg-deb structure checks and unsafe bundle rejection without installs."""
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "build/linux_package.py"
spec = importlib.util.spec_from_file_location("linux_package", SCRIPT)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux packaging requires POSIX filesystem semantics")
class LinuxPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "_internal").mkdir(parents=True)
        executable = self.bundle / package.APP
        executable.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 11 + struct.pack("<H", 62) + b"\0" * 44)
        executable.chmod(0o755)
        (self.bundle / "_internal/base_library.zip").write_bytes(b"bundled Python runtime fixture")
        (self.bundle / "_internal/libfixture.so.1").write_bytes(b"runtime fixture")
        (self.bundle / "_internal/libfixture.so").symlink_to("libfixture.so.1")
        self.output = self.root / "packages"

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb unavailable")
    def test_cli_builds_real_debian_package_portable_archive_and_checksums(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--bundle", str(self.bundle),
            "--output", str(self.output), "--version", "0.10.0", "--portable"], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(len(report["files"]), 3)
        deb = self.output / "dndgm4_0.10.0_amd64.deb"
        fields = subprocess.run(["dpkg-deb", "--field", str(deb)], capture_output=True, text=True, check=True).stdout
        for field in ("Package: dndgm4", "Version: 0.10.0", "Architecture: amd64", "libc6 (>= 2.35)", "libxcb-cursor0", "libxcb-icccm4"):
            self.assertIn(field, fields)
        extracted = self.root / "extracted"
        subprocess.run(["dpkg-deb", "--extract", str(deb), str(extracted)], check=True)
        self.assertEqual((extracted / "opt/dndgm4/DnDGameManager4").read_bytes(), (self.bundle / package.APP).read_bytes())
        self.assertEqual((extracted / "usr/bin/dndgm4").read_text(), '#!/bin/sh\nexec "/opt/dndgm4/DnDGameManager4" "$@"\n')
        desktop = (extracted / "usr/share/applications/dndgm4.desktop").read_text()
        self.assertIn("Exec=/usr/bin/dndgm4\n", desktop)
        self.assertIn("Icon=dndgm4\n", desktop)
        icon = SCRIPT.parent.parent / "dndgm4/assets/dragon_crest.png"
        self.assertEqual((extracted / "usr/share/icons/hicolor/256x256/apps/dndgm4.png").read_bytes(), icon.read_bytes())
        self.assertTrue((extracted / "opt/dndgm4/_internal/libfixture.so").is_symlink())
        control = subprocess.run(["dpkg-deb", "--ctrl-tarfile", str(deb)], capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(control)) as archive:
            self.assertFalse(any(Path(name).name in {"preinst", "postinst", "prerm", "postrm"} for name in archive.getnames()))
        with tarfile.open(self.output / "dndgm4-0.10.0-linux-amd64.tar.gz") as archive:
            self.assertTrue(archive.getmember("DnDGameManager4/_internal/libfixture.so").issym())
            self.assertEqual(archive.getmember("DnDGameManager4/_internal/libfixture.so").linkname, "libfixture.so.1")
            self.assertTrue(all(name.startswith("DnDGameManager4") for name in archive.getnames()))
        for name, digest in report["sha256"].items():
            self.assertEqual(sha256((self.output / name).read_bytes()).hexdigest(), digest)
            self.assertIn(f"{digest}  {name}\n", (self.output / "SHA256SUMS").read_text())

    def test_rejects_user_data_private_files_and_unexpected_root_files(self):
        for relative in ("_internal/library.sqlite3", "_internal/creatures.db", "_internal/.env",
                         "_internal/voice.gguf", "_internal/home/private.txt", "extra.txt"):
            with self.subTest(path=relative):
                path = self.bundle / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"must not ship")
                with self.assertRaises(ValueError):
                    package.validate_bundle(self.bundle)
                path.unlink()
                if path.parent.name == "home":
                    path.parent.rmdir()
        self.assertFalse(self.output.exists())

    def test_rejects_escaping_absolute_and_broken_symlinks(self):
        outside = self.root / "outside.so"
        outside.write_bytes(b"outside runtime")
        link = self.bundle / "_internal/unsafe.so"
        for target in ("../../outside.so", str(outside), "missing.so"):
            with self.subTest(target=target):
                link.symlink_to(target)
                with self.assertRaises((ValueError, OSError)):
                    package.validate_bundle(self.bundle)
                link.unlink()
        unsafe_name = self.bundle / "_internal/private.db"
        unsafe_name.symlink_to("libfixture.so.1")
        with self.assertRaisesRegex(ValueError, "allowlist"):
            package.validate_bundle(self.bundle)

    def test_rejects_wrong_architecture_versions_and_output_inside_bundle(self):
        with self.assertRaisesRegex(ValueError, "Version"):
            package.build_package(self.bundle, self.output, "0.10.0\nDepends: injected")
        with self.assertRaisesRegex(ValueError, "outside"):
            package.build_package(self.bundle, self.bundle / "dist", "0.10.0")
        executable = self.bundle / package.APP
        executable.write_bytes(b"MZ not a Linux executable")
        with self.assertRaisesRegex(ValueError, "ELF64 amd64"):
            package.validate_bundle(self.bundle)
        self.assertFalse(self.output.exists())
