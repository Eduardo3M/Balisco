#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{9E6E7277-1A77-4A99-B09C-E3BE871CB4D2}
AppName=Balisco
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Balisco
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=BaliscoSetup
SetupIconFile=..\ui\Logo.ico
UninstallDisplayIcon={app}\Balisco.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\build\app\Balisco\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Balisco"; Filename: "{app}\Balisco.exe"; WorkingDir: "{app}"; AppUserModelID: "balisco.library.app.1.0"
Name: "{autodesktop}\Balisco"; Filename: "{app}\Balisco.exe"; WorkingDir: "{app}"; AppUserModelID: "balisco.library.app.1.0"

[Run]
Filename: "{app}\Balisco.exe"; Description: "Abrir Balisco"; Flags: nowait postinstall skipifsilent
