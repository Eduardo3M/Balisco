"""Sequential Drive Desktop and library-root setup."""
from pathlib import Path, PureWindowsPath
from contextlib import closing
import os
import shutil
import subprocess
import webbrowser

from .database import configurar, preferencia
from .drive_sync import Metadata, conectar_db_drive_ro, detectar_perfiles_drive, extraer_ids_proto, SeleccionRequerida
from .library_layout import mounted_drive, root_id, root_parts


def drive_executable():
    command=shutil.which('GoogleDriveFS.exe')
    if command:return Path(command)
    roots=[Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Google'/'Drive File Stream',
           Path(os.environ.get('LOCALAPPDATA',''))/'Google'/'DriveFS']
    if os.name=='nt':
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Google Drive') as key:
                        roots.append(Path(winreg.QueryValueEx(key,'InstallLocation')[0]))
                except OSError:pass
        except ImportError:pass
    for root in roots:
        direct=root/'GoogleDriveFS.exe'
        if direct.is_file(): return direct
        if root.is_dir():
            for path in sorted(root.glob('*/GoogleDriveFS.exe'),reverse=True):return path
    return None


def drive_running():
    if os.name!='nt': return False
    try:
        result=subprocess.run(['tasklist','/FI','IMAGENAME eq GoogleDriveFS.exe','/NH'],
                              capture_output=True,text=True,timeout=5,check=False)
        return 'GoogleDriveFS.exe' in result.stdout
    except (OSError,subprocess.TimeoutExpired): return False


def status(db, profile=None):
    if not drive_executable(): return {'state':'not_installed'}
    if not drive_running(): return {'state':'not_running'}
    profiles=[p for p in detectar_perfiles_drive() if not p.get('error')]
    if not profiles:return {'state':'not_running'}
    selected=profile or preferencia(db,'id_perfil_drive')
    if not selected and len(profiles)==1:selected=profiles[0]['id']
    if not selected or selected not in {p['id'] for p in profiles}:
        return {'state':'needs_profile','profiles':[p['id'] for p in profiles]}
    if preferencia(db,'id_perfil_drive')!=selected:
        with db: configurar(db,'id_perfil_drive',selected)
    try: drive=mounted_drive(db,selected)
    except ValueError:return {'state':'needs_location','profile':selected}
    except FileNotFoundError:return {'state':'not_running','profile':selected}
    ident=root_id(db,selected)
    if not ident: return {'state':'needs_location','profile':selected,'drive':str(drive)}
    source=next(p['ruta_db'] for p in profiles if p['id']==selected)
    with closing(conectar_db_drive_ro(source)) as conn:
        _,parts=root_parts(Metadata(conn),ident)
    if not parts:
        with db:
            db.execute('DELETE FROM configuracion WHERE clave=?',('biblioteca_root_id:'+selected,))
            db.execute('UPDATE items SET disponible=0 WHERE perfil_drive=?',(selected,))
        return {'state':'needs_location','profile':selected,'drive':str(drive),'removed':True}
    path=drive.joinpath(*parts)
    if not path.is_dir():return {'state':'not_running','profile':selected}
    if preferencia(db,'migration_pending:'+selected)=='1':
        return {'state':'needs_migration','profile':selected,'path':str(path)}
    return {'state':'ready','profile':selected,'path':str(path),'root_id':ident}


def link_folder(db, profile, folder):
    from .container_ops import drive_id_for_path
    folder=Path(folder).resolve()
    configured=preferencia(db,'unidad_drive:'+profile)
    drive=Path(configured).resolve() if configured else Path(folder.anchor)
    if not folder.is_dir() or not folder.is_relative_to(drive):
        raise ValueError('Selecciona una carpeta existente de Google Drive')
    parts=folder.relative_to(drive).parts
    if len(parts)<2 or parts[0] not in ('Mi unidad','My Drive'):
        raise ValueError('La biblioteca debe estar dentro de Mi unidad')
    if any(part.startswith('.') for part in parts[1:]):
        raise ValueError('La biblioteca no puede estar dentro de una carpeta oculta')
    ident=drive_id_for_path(profile,str(PureWindowsPath(*parts)),is_folder=True)
    with db:
        configurar(db,'unidad_drive:'+profile,str(drive))
        configurar(db,'biblioteca_root_id:'+profile,ident)
        configurar(db,'id_perfil_drive',profile)
        if any((folder/name).exists() for name in ('Storage','Containers')) or any(child.is_file() and child.name.casefold()!='desktop.ini' for child in folder.iterdir()):
            configurar(db,'migration_pending:'+profile,'1')
        else:db.execute('DELETE FROM configuracion WHERE clave=?',('migration_pending:'+profile,))
    return status(db,profile)


def launch_drive():
    executable=drive_executable()
    if not executable: raise FileNotFoundError('Google Drive para escritorio no está instalado')
    subprocess.Popen([str(executable)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return True


def open_install_page():
    return webbrowser.open('https://www.google.com/drive/download/')
