#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Dungeons & Dragons Game Manager 4"
#define AppExe "DnDGameManager4.exe"

[Setup]
; Never change this AppId: subsequent builds should install over the same application.
AppId={{D1136F70-E912-4AA1-8D0B-C3151977EF67}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Kaotick Jay
DefaultDirName={autopf}\DnDGameManager4
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=DnDGameManager4-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Files]
Source: "..\dist\DnDGameManager4\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; No user data is removed. The SQLite library lives in LOCALAPPDATA, not {app}.
