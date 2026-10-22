# Linux desktop installer

The **Linux installer** workflow publishes an amd64 Debian package and a
portable archive. Builds target Ubuntu 22.04 or newer and Debian 12 or newer
on x86-64; the installed Python interpreter is not required. ARM systems and
older glibc distributions need a separate build.

Open the repository's Actions tab, select a successful **Linux installer** run,
and download its `DnDGameManager4-Linux-...` artifact. Extract the artifact, then
verify and install from that folder:

```sh
sha256sum --check SHA256SUMS
sudo apt install ./dndgm4_0.10.0_amd64.deb
```

Open **D&D Game Manager 4** from the applications menu, or run `dndgm4`.
The package installs its bundled application under `/opt/dndgm4`, a launcher
under `/usr/bin`, and a desktop entry and icon under `/usr/share`. Apt installs
the declared graphics, fonts and desktop runtime dependencies.

Close the application before upgrading, then install the newer `.deb` in the
same way. Remove the application with `sudo apt remove dndgm4`; purging the
package also leaves personal campaign data intact. No package scripts delete,
migrate or copy user files, stop applications, or download models.

Campaign data remains under `${XDG_DATA_HOME:-$HOME/.local/share}/DnDGameManager4`
unless a different library was explicitly selected. Before trying a development
build, **Library → Create Complete Campaign Backup** preserves the library,
standalone saves, rules references, spell index and managed images together.
An older application may refuse the schema created by a newer one.

The portable archive contains `DnDGameManager4/`. Extract it into a new folder
and run `./DnDGameManager4/DnDGameManager4`. It needs the same system runtime
libraries as the Debian package; it does not create a menu entry.

CI launches the actual bundled and installed executables with native X11/xcb
rendering under Xvfb. It checks artwork, font glyphs, startup, migration,
backup/restore and the campaign desks. Install, reinstall, removal and purge
must preserve an isolated populated legacy library byte-for-byte. The runner is
disposable; these checks do not install over the user's live application.
