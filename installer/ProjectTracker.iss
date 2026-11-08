; Installer for Project Tracker (Inno Setup 6).
; Build:  ISCC.exe /DAppVersion=2.40 /DBuildDir=<folder with ProjectTracker.exe> /DOutDir=<output folder> installer\ProjectTracker.iss
;
; Installs for the current user only (no admin rights): the app keeps
; config.json and logs\ next to the exe, so it needs a folder it can write to.
; The PROJECT DATA (project_tracker.db, attachments, backups) lives in the data
; folder the user chooses on first run - the installer never touches it,
; neither on install, update nor uninstall.

#ifndef AppVersion
  #define AppVersion "2.40"
#endif
#ifndef BuildDir
  #define BuildDir "..\dist"
#endif
#ifndef OutDir
  #define OutDir "..\dist\installer"
#endif
#define AppName "Project Tracker"
#define AppExe "ProjectTracker.exe"

[Setup]
AppId={{6C1E9B47-2F3A-4D8E-B5A1-7E0C93D41F62}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Ahmed Ismail
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ProjectTracker
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=ProjectTracker-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
LanguageDetectionMethod=none
CloseApplications=no
InfoBeforeFile=info_ar.txt

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#BuildDir}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\fonts\OFL-Cairo.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "info_ar.txt"; DestDir: "{app}"; DestName: "README-AR.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only what the app itself writes next to the exe. The data folder
; (database, attachments, backups) is somewhere else and is never removed.
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\config.json.corrupt"
Type: filesandordirs; Name: "{app}\logs"

[Code]
// A PyInstaller --onefile app runs as two processes; stop only the copies
// running from THIS install folder before replacing or removing the exe.
procedure StopRunningCopies(Folder: String);
var
  Code: Integer;
begin
  // Setup is 32-bit; the 32-bit PowerShell cannot see 64-bit process paths.
  Exec(ExpandConstant('{sysnative}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process ProjectTracker -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + Folder + '\*'' } | Stop-Process -Force; Start-Sleep -Milliseconds 800"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningCopies(ExpandConstant('{app}'));
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopRunningCopies(ExpandConstant('{app}'));
end;
