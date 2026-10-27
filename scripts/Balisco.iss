#ifndef AppVersion
  #define AppVersion "0.1.9"
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
OutputBaseFilename=BaliscoSetup-{#AppVersion}-win-x64
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

[Code]
// Detectar versión previa y solicitar desinstalación antes de continuar
function InitializeSetup(): Boolean;
var
  UninstPath: String;
  ResultCode: Integer;
begin
  Result := True;
  // Buscar en el registro de desinstalación de Windows para el usuario actual
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{9E6E7277-1A77-4A99-B09C-E3BE871CB4D2}_is1', 'UninstallString', UninstPath) then
  begin
    // Quitar comillas si las tiene
    UninstPath := RemoveQuotes(UninstPath);
    if FileExists(UninstPath) then
    begin
      if WizardSilent() or (MsgBox('Se ha detectado una versión anterior de Balisco instalada en su equipo.' + #13#10 + #13#10 +
                '¿Desea desinstalarla automáticamente ahora para continuar con una instalación limpia?',
                mbConfirmation, MB_YESNO) = IDYES) then
      begin
        // Ejecutar desinstalador silencioso
        if Exec(UninstPath, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          // Desinstalación completada con éxito
          Result := True;
        end
        else
        begin
          MsgBox('No se pudo completar la desinstalación de la versión anterior.' + #13#10 +
                 'La instalación se cancelará para evitar conflictos.', mbError, MB_OK);
          Result := False;
        end;
      end
      else
      begin
        // El usuario eligió no desinstalar la versión previa
        Result := False;
      end;
    end;
  end;
end;
