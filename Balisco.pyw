"""Entrada de diagnóstico e inicialización del backend (Fase 1)."""
import time
STARTED = time.perf_counter()
import sys
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('balisco.library.app.1.0')
    except Exception:
        pass

import argparse
import json
from core.database import conectar, DATA_DIR
from core.drive_sync import detectar_perfiles_drive, DriveSync
from core.search_parser import agregar_filtro, limpiar_todos_filtros, buscar

def main():
    parser=argparse.ArgumentParser(description='Balisco — núcleo local')
    parser.add_argument('--debug',action='store_true')
    parser.add_argument('--perfiles',action='store_true')
    parser.add_argument('--sincronizar',action='store_true')
    parser.add_argument('--perfil')
    parser.add_argument('--buscar',nargs='*')
    args=parser.parse_args()
    if args.perfiles:
        print(json.dumps(detectar_perfiles_drive(),ensure_ascii=False,indent=2)); return
    if not args.sincronizar and args.buscar is None:
        desktop(debug=args.debug); return
    db=conectar()
    try:
        if args.sincronizar:
            sync=DriveSync(db)
            print(json.dumps(sync.sincronizar_biblioteca(perfil=args.perfil),ensure_ascii=False))
            sync.exportar_libros(DATA_DIR/'export_libros.json')
        if args.buscar is not None:
            filters=limpiar_todos_filtros()
            for token in args.buscar: filters=agregar_filtro(token,filters)
            print(json.dumps(buscar(db,filters,perfil=args.perfil),ensure_ascii=False,indent=2))
    finally: db.close()

def desktop(debug=False):
    import os, sys
    from pathlib import Path
    import webview
    from core.desktop_api import DesktopAPI

    base_path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    icon_path = base_path / 'ui' / 'Logo.ico'

    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('balisco.library.app.1.0')
        except Exception:
            pass
        if not debug:
            try:
                import ctypes
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)
            except Exception:
                pass

    api = DesktopAPI(started=STARTED)
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
    webview.settings['ALLOW_DOWNLOADS'] = False
    # Cargar geometría previa persistida
    default_w, default_h = 1380, 900
    win_w, win_h = default_w, default_h
    win_x, win_y = None, None
    is_maximized = False
    try:
        from core.database import conectar, preferencia
        with conectar() as db:
            geom_str = preferencia(db, 'window_geometry')
            if geom_str:
                geom = json.loads(geom_str)
                win_w = max(940, int(geom.get('w', default_w)))
                win_h = max(640, int(geom.get('h', default_h)))
                gx = geom.get('x')
                gy = geom.get('y')
                is_maximized = bool(geom.get('maximized', False))
                # Validar que x, y estén dentro de la pantalla visible actual
                if gx is not None and gy is not None:
                    try:
                        import ctypes
                        u = ctypes.windll.user32
                        v_left = u.GetSystemMetrics(76)
                        v_top = u.GetSystemMetrics(77)
                        v_width = u.GetSystemMetrics(78)
                        v_height = u.GetSystemMetrics(79)
                        if v_left <= gx < (v_left + v_width - 100) and v_top <= gy < (v_top + v_height - 100):
                            win_x, win_y = int(gx), int(gy)
                    except Exception:
                        win_x, win_y = int(gx), int(gy)
    except Exception:
        pass

    ui_dir = base_path / 'ui'
    ui_version = max((ui_dir / name).stat().st_mtime_ns for name in ('index.html', 'styles.css', 'app.js'))
    ui_url = f"{ui_dir / 'index.html'}?v={ui_version}"
    window = webview.create_window(
        'Balisco',
        ui_url,
        js_api=api,
        width=win_w,
        height=win_h,
        x=win_x,
        y=win_y,
        maximized=is_maximized,
        min_size=(940, 640),
        frameless=True,
        easy_drag=False,
        background_color='#0a0b0e',
        text_select=True
    )
    configure_close(window, api)
    configure_container_drop(window, api)

    icon_arg = str(icon_path) if icon_path.is_file() else None

    start_options = dict(gui='edgechromium', debug=debug, private_mode=False,
                         storage_path=str(DATA_DIR/'webview'), icon=icon_arg)
    if debug:
        import threading
        stop_watching = threading.Event()
        window.events.closed += stop_watching.set
        webview.start(watch_ui_changes, (window, base_path / 'ui', stop_watching), **start_options)
    else:
        webview.start(**start_options)

def watch_ui_changes(window, ui_dir, stop_event):
    """Recarga la ventana de desarrollo al guardar HTML, CSS o JavaScript."""
    def snapshot():
        return {str(path): path.stat().st_mtime_ns for path in ui_dir.rglob('*')
                if path.is_file() and path.suffix.lower() in {'.html', '.css', '.js'}}

    previous = snapshot()
    while not stop_event.wait(0.4):
        current = snapshot()
        if current == previous:
            continue
        previous = current
        # Esperar a que el editor termine de escribir antes de recargar.
        if stop_event.wait(0.3):
            break
        previous = snapshot()
        try:
            window.evaluate_js('window.location.reload()')
        except Exception:
            if not stop_event.is_set():
                raise

def configure_container_drop(window, api):
    """Receive real Windows folder paths from WebView2 without reading file contents."""
    from pathlib import Path
    import threading
    import time
    import json

    def dropped(event):
        files=event.get('dataTransfer',{}).get('files',[])
        for file in files:
            path=file.get('pywebviewFullPath')
            if not path: continue
            source=Path(path)
            if not source.is_dir() and not source.is_file():continue
            folder=source.is_dir()
            result=api.call('start_import',{'path':path})
            if not result.get('ok'):
                try:window.evaluate_js('window.balisco?.importRejected('+json.dumps(result.get('error','No se pudo iniciar la importación'),ensure_ascii=False)+')')
                except Exception:pass
                break
            job=result['data']
            try:window.evaluate_js('window.balisco?.importStarted('+json.dumps(job['name'],ensure_ascii=False)+','+json.dumps(job['kind'])+','+json.dumps(job['id'])+')')
            except Exception:pass
            def monitor(job_id=job['id'],item_name=job['name'],is_folder=folder):
                while True:
                    result=api.call('import_status',{'id':job_id})
                    status=result.get('data',{}) if result.get('ok') else {'state':'error','error':result.get('error','No se pudo consultar el estado')}
                    if status.get('state') in ('done','error','cancelled','unknown'):
                        payload={'ok':status.get('state')=='done','cancelled':status.get('state')=='cancelled','id':job_id,'data':status.get('data',{}),'error':status.get('error')}
                        try:window.evaluate_js('window.balisco?.importFinished('+json.dumps(payload,ensure_ascii=False)+')')
                        except Exception:pass
                        break
                    time.sleep(.35)
            threading.Thread(target=monitor,daemon=True).start()

    def loaded():
        try:
            body=window.dom.get_element('body')
            if body:
                body.on('drop',dropped)
                window.evaluate_js('if(window.balisco)window.balisco.nativeDrop=true')
        except Exception:
            pass

    window.events.loaded += loaded

def configure_close(window, api):
    """Connect native chrome and flush pending edits on every close path."""
    import threading
    from core.window_chrome import WindowChrome
    chrome = WindowChrome(window, api._dbpath)
    api._window, api._chrome = window, chrome
    api._allow_close = False
    close_lock = threading.Lock()

    def finish_close():
        if not close_lock.acquire(blocking=False):
            return
        try:
            chrome.save_geometry()
            chrome.hide()
            window.destroy()
        finally:
            close_lock.release()
    api._finish_close = finish_close

    def closing():
        if api._allow_close:
            return True
        # Closing runs on the UI thread: request the asynchronous JS flush
        # from a worker, then cancel this first native close event.
        def request():
            if window.events.loaded.is_set():
                window.evaluate_js('window.balisco.close()')
            else:
                api._allow_close = True
                finish_close()
        threading.Thread(target=request, daemon=True).start()
        return False

    def publish_state(*args):
        if not window.events.loaded.is_set() or api._allow_close:
            return
        state = chrome.is_maximized()
        try:
            window.evaluate_js('window.balisco?.windowState(' + json.dumps(state) + ')')
        except Exception:
            pass

    def moved(*args):
        chrome.track_monitor()

    window.events.before_show += chrome.prepare
    window.events.loaded += publish_state
    window.events.maximized += publish_state
    window.events.restored += publish_state
    window.events.moved += moved
    window.events.closing += closing

if __name__=='__main__': main()
