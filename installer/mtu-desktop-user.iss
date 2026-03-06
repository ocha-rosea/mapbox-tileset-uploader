#define MyAppName "ROSEA MTU"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-local"
#endif
#define MyAppPublisher "ROSEA"
#define MyAppExeName "mtu-desktop.exe"

[Setup]
AppId={{2A46A6AE-6D43-4FE6-BD27-2A3D23B2A9A6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=ROSEA-MTU-v{#MyAppVersion}-setup-user
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SignTool=envsigntool
SignedUninstaller=yes

[SignTools]
; Uses scripts/inno_sign_file.ps1 which reads WINDOWS_CERT_BASE64 and WINDOWS_CERT_PASSWORD.
; If env vars are missing, signing is skipped and compile continues.
Name: "envsigntool"; Command: "powershell -NoProfile -ExecutionPolicy Bypass -File \"{#SourcePath}..\\scripts\\inno_sign_file.ps1\" \"$f\""

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\mtu-desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
