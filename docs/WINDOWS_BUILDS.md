# Installing Windows test builds

The **Windows installer** GitHub Actions workflow builds on pull requests against
`main`, every push to `main`, manual dispatch, and tags starting with `v`.

## Testing a new build

1. Open the repository's **Actions** tab.
2. Select **Windows installer**, then choose the latest successful run.
3. Download the `DnDGameManager4-Windows-...` artifact.
4. Extract it and run `DnDGameManager4-Setup.exe`.
5. Install over the previous version. You do not need to uninstall first.

The installer uses a fixed Inno Setup AppId and installation directory so
upgrades replace the application rather than adding a second installation.
Close the running application before upgrading. The installer may request
closing it.

## Character and monster safety

The application stores the SQLite library at
`%LOCALAPPDATA%\DnDGameManager4\library.sqlite3`, outside the installation
directory. Upgrading or uninstalling the application does not remove this file.

**Still back up your library** before testing new development builds.
Later database schema changes may not be backward-compatible.

Version 0.10.0 uses library schema v6. Before upgrading, use **Library → Create
Complete Campaign Backup…** to preserve the library, standalone scene and battle
JSON, rules references, and managed map and handout images together. **Restore
Complete Backup…** validates a copy in a new folder. SQLite-only backups include
campaign parties, session journals/scenes, and named encounter combat state, but
omit the standalone JSON, rules databases, and image files. Older app versions
refuse a database schema newer than they support.

## Portable ZIP and releases

Each successful run also publishes `DnDGameManager4-Portable.zip`.
Version tags such as `v0.1.0` additionally create a GitHub Release
with the installer and portable ZIP.

The workflow builds on Windows GitHub-hosted runners and checks the packaged
application, silent installation, reinstallation, retained campaign data, and
schema migration. Check that the entire Actions run succeeded before choosing
a build. An interactive upgrade from an older installed version and placement
of the Player View on a physical second monitor still require manual testing.
