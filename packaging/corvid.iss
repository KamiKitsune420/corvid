; Inno Setup script for Corvid.
;
; Build the app first, then compile this script:
;
;     pyinstaller corvid.spec
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\corvid.iss
;
; The installer is written to dist\CorvidSetup-<version>.exe. It installs
; per-machine (requires elevation) into Program Files\ALS-Software\corvid.

#define MyAppName "Corvid"
#define MyAppVersion "0.2.0"          ; keep in sync with pyproject.toml
#define MyAppPublisher "ALS-Software"
#define MyAppExeName "Corvid.exe"

[Setup]
; A stable, unique identity for this application (do not reuse for other apps).
AppId={{B7B2F3B8-3E1C-4C7A-9D2E-6A1F0C5D9E42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppPublisher}\corvid
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; Per-machine install into Program Files\ALS-Software\corvid; requires elevation.
PrivilegesRequired=admin
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
; If WebView2 was missing and we downloaded the bootstrapper (see [Code]),
; install the runtime silently before finishing.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; \
  Check: NeedInstallWebView2; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ Corvid's message-reading pane uses the Microsoft Edge WebView2 runtime, which
  is what makes email bodies readable by a screen reader. Windows 11 ships it. If
  it's missing, Setup downloads Microsoft's Evergreen Bootstrapper on the wizard's
  download page and installs the runtime silently (see the [Run] entry), so the
  user never has to fetch it by hand. }

const
  { Microsoft's stable "Evergreen Bootstrapper" link (a small ~2 MB downloader
    that pulls the current runtime). }
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2BootstrapperFile = 'MicrosoftEdgeWebview2Setup.exe';

var
  DownloadPage: TDownloadWizardPage;
  WebView2Fetched: Boolean;  { True once the bootstrapper has been downloaded. }

function WebView2Installed(): Boolean;
var
  Pv: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv) or
    RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Pv);
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(
    'Downloading a required component',
    'Setup is fetching the Microsoft Edge WebView2 Runtime that Corvid needs to '
      + 'display and read aloud email messages.',
    nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  WebView2Fetched := False;
  { Only the Ready page triggers the download, and only when the runtime is
    absent. On failure we don't block the install — Corvid still installs and the
    user is told how to add WebView2 by hand. }
  if (CurPageID = wpReady) and (not WebView2Installed()) then
  begin
    DownloadPage.Clear;
    DownloadPage.Add(WebView2BootstrapperUrl, WebView2BootstrapperFile, '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
        WebView2Fetched := True;
      except
        MsgBox('The Microsoft Edge WebView2 Runtime could not be downloaded ('
          + GetExceptionMessage + ').' + #13#10#13#10
          + 'Corvid will still install. If email messages appear blank, install '
          + 'WebView2 for free from:' + #13#10
          + 'https://developer.microsoft.com/microsoft-edge/webview2/',
          mbInformation, MB_OK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

function NeedInstallWebView2(): Boolean;
begin
  Result := WebView2Fetched;
end;
