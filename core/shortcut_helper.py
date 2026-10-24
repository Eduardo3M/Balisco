"""Utilidad de creación de acceso directo compatible con la barra de tareas de Windows."""
import os
import sys
import subprocess
from pathlib import Path

APP_USER_MODEL_ID = 'balisco.library.app.1.0'

def obtener_ruta_escritorio():
    """Obtiene la ruta física real del escritorio del usuario actual."""
    if sys.platform == 'win32':
        try:
            import ctypes.wintypes
            CSIDL_DESKTOP = 0
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOP, None, 0, buf)
            if buf.value and Path(buf.value).is_dir():
                return Path(buf.value)
        except Exception:
            pass
        # Fallbacks conocidos en Windows
        p1 = Path(os.environ.get('USERPROFILE', '')) / 'OneDrive' / 'Desktop'
        if p1.is_dir(): return p1
        p2 = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
        if p2.is_dir(): return p2
    return Path.home() / 'Desktop'

def crear_acceso_directo(destino_lnk=None):
    """Crea un acceso directo .lnk en el Escritorio con AppUserModelID inyectado.
    Esto permite que Windows ancle y agrupe la ventana activa sobre el mismo icono."""
    if sys.platform != 'win32':
        return False
    try:
        is_frozen = getattr(sys, 'frozen', False)
        if is_frozen:
            target_path = Path(sys.executable)
            target_args = ''
            base_dir = target_path.parent
            icon_path = getattr(sys, '_MEIPASS', None)
            icon_path = (Path(icon_path) / 'ui' / 'Logo.ico') if icon_path else (base_dir / 'ui' / 'Logo.ico')
            set_appid_exe = (Path(getattr(sys, '_MEIPASS', base_dir)) / 'core' / 'SetAppId.exe')
        else:
            base_dir = Path(__file__).resolve().parent.parent
            script_pyw = base_dir / 'Balisco.pyw'
            icon_path = base_dir / 'ui' / 'Logo.ico'
            set_appid_exe = base_dir / 'core' / 'SetAppId.exe'

            pythonw_exe = Path(sys.executable).parent / 'pythonw.exe'
            if not pythonw_exe.exists():
                pythonw_exe = Path(sys.executable)
            target_path = pythonw_exe
            target_args = f'"{str(script_pyw)}"'

        lnk = Path(destino_lnk) if destino_lnk else obtener_ruta_escritorio() / 'Balisco.lnk'

        # Script PowerShell para generar el .lnk con TargetPath y Arguments
        ps_code = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{str(lnk)}')
$sc.TargetPath = '{str(target_path)}'
$sc.Arguments = '{target_args}'
$sc.WorkingDirectory = '{str(base_dir)}'
$sc.IconLocation = '{str(icon_path)},0'
$sc.Description = 'Balisco - Biblioteca de Conocimiento'
$sc.Save()
"""
        ps_temp = base_dir / 'core' / '_make_lnk.ps1'
        ps_temp.write_text(ps_code, encoding='utf-8')
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps_temp)],
                creationflags=0x08000000,
                check=True
            )
        finally:
            if ps_temp.exists():
                ps_temp.unlink()

        # Inyectar System.AppUserModel.ID al archivo .lnk con SetAppId.exe
        if set_appid_exe.is_file() and lnk.is_file():
            subprocess.run(
                [str(set_appid_exe), str(lnk), APP_USER_MODEL_ID],
                creationflags=0x08000000,
                check=False
            )
        return True
    except Exception:
        return False

if __name__ == '__main__':
    ok = crear_acceso_directo()
    print("Acceso directo creado:", ok)
