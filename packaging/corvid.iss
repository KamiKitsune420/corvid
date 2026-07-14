; Inno Setup script for Corvid.
;
; Build the app first, then compile this script:
;
;     pyinstaller corvid.spec
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\corvid.iss
;
; The installer is written to dist\CorvidSetup-<version>.exe. It installs
; per-user (no administrator prompt) into %LOCALAPPDATA%\Programs\Corvid.

#define MyAppName "Corvid"
#define MyAppVersion "0.1.0"          ; keep in sync with pyproject.toml
#define MyAppPublisher "Corvid contributors"
#define MyAppExeName "Corvid.exe"

[Setup]
; A stable, unique identity for this application (do not reuse for other apps).
AppId={{B7B2F3B8-3E1C-4C7A-9D2E-6A1F0C5D9E42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; Per-user install so no UAC / admin rights are required.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CorvidSetup-{#MyAppVersion}
SetupIconFile=..\src\corvid\ui\assets\corvid.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire PyInstaller one-folder output.
Source: "..\dist\Corvid\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Corvid's message-reading pane uses the Microsoft Edge WebView2 runtime, which
  is what makes email bodies readable by a screen reader. Windows 11 ships it,
  but warn (non-fatally) if it's somehow missing so the user knows to install it. }
function WebView2Installed(): Boolean;
var
  Pv: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    MsgBox('The Microsoft Edge WebView2 Runtime was not detected. Corvid needs it '
      + 'to display (and read aloud) email messages. If message bodies appear blank, '
      + 'install it free from:' + #13#10#13#10
      + 'https://developer.microsoft.com/microsoft-edge/webview2/',
      mbInformation, MB_OK);
end;
