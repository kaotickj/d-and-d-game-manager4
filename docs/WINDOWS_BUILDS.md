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

Campaign builds use schema v3. SQLite backups now include campaign parties,
session journals/scenes, and named encounter combat state. The previous standalone
scene and battle JSON files remain outside SQLite unless explicitly copied into
a campaign session. Preserve those files separately when backing up standalone
play. Older app versions refuse a database schema newer than they support.

## Portable ZIP and releases

Each successful run also publishes `DnDGameManager4-Portable.zip`.
Version tags such as `v0.1.0` additionally create a GitHub Release
with the installer and portable ZIP.

The workflow creates build artifacts only on Windows GitHub-hosted runners.
An uploaded artifact is not the same as a tested installation: check the
Actions run and verify a real Windows installation before relying on it.
