"""Ventana sin marco en Windows: arrastre, redimensionado, maximizado y geometría.

Toda la interacción nativa usa el HWND real del formulario de pywebview
(nunca FindWindow por título, que podría capturar otra ventana llamada «Balisco»).
"""
from contextlib import closing
import ctypes
import json
import sys
import sqlite3
import threading
from ctypes import wintypes

IS_WIN = sys.platform == 'win32'

WM_SYSCOMMAND = 0x0112
WM_NCLBUTTONDOWN = 0x00A1
SC_SIZE, SC_MOVE = 0xF000, 0xF010
HTCAPTION = 2
SW_HIDE, SW_SHOWMAXIMIZED, SW_SHOWNORMAL = 0, 3, 1
GWL_STYLE = -16
WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00080000, 0x00020000, 0x00010000
WS_THICKFRAME = 0x00040000
WS_CAPTION = 0x00C00000
WM_NCCALCSIZE = 0x0083
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
AW_HIDE, AW_BLEND = 0x00010000, 0x00080000
MONITOR_DEFAULTTONEAREST = 2
# Códigos WMSZ_* que se suman a SC_SIZE para indicar el borde arrastrado.
EDGES = {'left': 1, 'right': 2, 'top': 3, 'topleft': 4, 'topright': 5,
         'bottom': 6, 'bottomleft': 7, 'bottomright': 8}
MIN_W, MIN_H = 940, 640


class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [('length', wintypes.UINT), ('flags', wintypes.UINT), ('showCmd', wintypes.UINT),
                ('ptMinPosition', wintypes.POINT), ('ptMaxPosition', wintypes.POINT),
                ('rcNormalPosition', RECT)]

class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', RECT),
                ('rcWork', RECT), ('dwFlags', wintypes.DWORD)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [('rgrc', RECT * 3), ('lppos', ctypes.c_void_p)]


if IS_WIN:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    comctl32 = ctypes.WinDLL('comctl32', use_last_error=True)
    SUBCLASSPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.AnimateWindow.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.DWORD]
    user32.AnimateWindow.restype = wintypes.BOOL


def _pack_point(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


class WindowChrome:
    def __init__(self, window, db_path=None):
        self.window = window
        self.db_path = db_path
        self.hwnd = None
        self._monitor = None
        self._maximized = None
        self._lock = threading.Lock()
        self._snap_restore = None
        self._subclass_proc = None

    # ---- infraestructura -------------------------------------------------
    def _native(self):
        return getattr(self.window, 'native', None)

    def resolve(self):
        if not self.hwnd and IS_WIN:
            native = self._native()
            if native is not None:
                try:
                    self.hwnd = int(native.Handle.ToInt64())
                except Exception:
                    self.hwnd = None
        return self.hwnd

    def _ui(self, fn):
        """Ejecuta fn en el hilo de WinForms (síncrono)."""
        native = self._native()
        if native is None:
            return
        if not native.InvokeRequired:
            fn()
            return
        from webview.platforms.winforms import Func, Type
        native.Invoke(Func[Type](fn))

    def _placement(self):
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        if self.resolve() and user32.GetWindowPlacement(self.hwnd, ctypes.byref(wp)):
            return wp
        return None

    def _fit_maximized_bounds(self):
        """Hilo UI. Sin esto, un formulario sin borde maximizado tapa la barra de tareas."""
        native = self._native()
        if native is None:
            return
        from System.Windows.Forms import Screen
        from System.Drawing import Rectangle
        screen = Screen.FromHandle(native.Handle)
        work, bounds = screen.WorkingArea, screen.Bounds
        native.MaximizedBounds = Rectangle(work.X - bounds.X, work.Y - bounds.Y, work.Width, work.Height)

    # ---- ciclo de vida -----------------------------------------------------
    def prepare(self):
        """Llamar desde `before_show` (hilo UI, antes de mostrarse)."""
        if not (IS_WIN and self.resolve()):
            return
        # Windows anima minimizar/restaurar solamente con los estilos de una
        # ventana normal. El callback quita el área no cliente (título y borde)
        # para que el WebView siga ocupando toda la ventana.
        def chrome_proc(hwnd, message, wparam, lparam, subclass_id, ref_data):
            if message == WM_NCCALCSIZE and wparam:
                params = ctypes.cast(lparam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                if user32.IsZoomed(hwnd):
                    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    info = MONITORINFO(); info.cbSize = ctypes.sizeof(info)
                    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                        params.rgrc[0] = info.rcWork
                return 0
            return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

        self._subclass_proc = SUBCLASSPROC(chrome_proc)
        if not comctl32.SetWindowSubclass(self.hwnd, self._subclass_proc, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        style = user32.GetWindowLongW(self.hwnd, GWL_STYLE)
        user32.SetWindowLongW(self.hwnd, GWL_STYLE,
                              style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        user32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
        self._fit_maximized_bounds()
        self._monitor = user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST)

    def track_monitor(self):
        """Si la ventana cambió de monitor, recalcula el área de maximizado."""
        if not (IS_WIN and self.resolve()):
            return
        monitor = user32.MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST)
        if monitor != self._monitor:
            self._monitor = monitor
            try:
                self._ui(self._fit_maximized_bounds)
            except Exception:
                pass

    # ---- estado ------------------------------------------------------------
    def is_maximized(self):
        return bool(IS_WIN and self.resolve() and user32.IsZoomed(self.hwnd))

    def state_changed(self):
        """Devuelve el nuevo estado si cambió desde la última consulta; si no, None."""
        if IS_WIN and self.resolve() and user32.IsIconic(self.hwnd):
            return None
        current = self.is_maximized()
        if current != self._maximized:
            self._maximized = current
            return current
        return None

    # ---- acciones ----------------------------------------------------------
    def minimize(self):
        from System.Windows.Forms import FormWindowState
        self._ui(lambda: setattr(self._native(), 'WindowState', FormWindowState.Minimized))
        return True

    def toggle_maximize(self):
        from System.Windows.Forms import FormWindowState
        target = not self.is_maximized()

        def apply():
            native = self._native()
            if target:
                self._fit_maximized_bounds()
                native.WindowState = FormWindowState.Maximized
            else:
                native.WindowState = FormWindowState.Normal
        self._ui(apply)
        return target

    def drag(self, ratio_x=0.5, offset_y=20):
        """Inicia el bucle nativo de movimiento. Si está maximizada, la restaura bajo el cursor."""
        if not (IS_WIN and self.resolve()):
            return False
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        if user32.IsZoomed(self.hwnd):
            wp = self._placement()
            if wp:
                r = wp.rcNormalPosition
                w, h = r.right - r.left, r.bottom - r.top
                ratio = min(max(float(ratio_x), 0.0), 1.0)
                left = pt.x - int(w * ratio)
                top = pt.y - max(0, int(offset_y))
                wp.rcNormalPosition = RECT(left, top, left + w, top + h)
                wp.showCmd = SW_SHOWNORMAL
                user32.SetWindowPlacement(self.hwnd, ctypes.byref(wp))
        elif self._snap_restore:
            w,h=self._snap_restore
            self._snap_restore=None
            left=pt.x-int(w*min(max(float(ratio_x),0),1))
            top=pt.y-max(0,int(offset_y))
            self._ui(lambda: user32.SetWindowPos(self.hwnd,None,left,top,w,h,0x0014))
        before=RECT()
        user32.GetWindowRect(self.hwnd,ctypes.byref(before))
        # Start the modal Windows move loop on the UI thread while the mouse is
        # still held. Posting WM_SYSCOMMAND after a JS move loses that gesture.
        def begin():
            user32.ReleaseCapture()
            user32.SendMessageW(self.hwnd, WM_NCLBUTTONDOWN, HTCAPTION, _pack_point(pt.x, pt.y))
        self._ui(begin)
        after = RECT()
        if user32.GetWindowRect(self.hwnd, ctypes.byref(after)):
            if not user32.IsZoomed(self.hwnd) and (after.right - after.left == before.right - before.left):
                self._snap_after_drag(before)
        return True

    def _snap_after_drag(self, before):
        pt=wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)): return
        monitor=user32.MonitorFromPoint(pt,MONITOR_DEFAULTTONEAREST)
        info=MONITORINFO();info.cbSize=ctypes.sizeof(info)
        if not monitor or not user32.GetMonitorInfoW(monitor,ctypes.byref(info)): return
        r=info.rcWork;m=info.rcMonitor;margin=24
        left=abs(pt.x-m.left)<=margin; right=abs(pt.x-(m.right-1))<=margin
        top=abs(pt.y-m.top)<=margin; bottom=abs(pt.y-(m.bottom-1))<=margin
        if not (left or right or top or bottom): return
        if top and not (left or right):
            self._ui(lambda: self._maximize_from_snap())
            return
        width=r.right-r.left;height=r.bottom-r.top
        if left or right:
            x=r.left if left else r.left+width//2
            w=width//2 if left else width-width//2
            y=r.top if top or not bottom else r.top+height//2
            h=height//2 if top or bottom else height
            if bottom: h=height-height//2
        else:
            x=r.left;w=width;y=r.top+height//2;h=height-height//2
        self._snap_restore=(before.right-before.left,before.bottom-before.top)
        self._ui(lambda: user32.SetWindowPos(self.hwnd,None,x,y,w,h,0x0014))

    def snap(self):
        if not (IS_WIN and self.resolve()): return False
        before=RECT()
        if not user32.GetWindowRect(self.hwnd,ctypes.byref(before)): return False
        self._snap_after_drag(before)
        return True

    def _maximize_from_snap(self):
        from System.Windows.Forms import FormWindowState
        self._fit_maximized_bounds()
        self._native().WindowState=FormWindowState.Maximized

    def resize(self, edge):
        if not (IS_WIN and self.resolve()) or edge not in EDGES or user32.IsZoomed(self.hwnd):
            return False
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        def begin():
            user32.ReleaseCapture()
            user32.SendMessageW(self.hwnd, WM_SYSCOMMAND, SC_SIZE + EDGES[edge], _pack_point(pt.x, pt.y))
        self._ui(begin)
        return True

    def hide(self):
        if IS_WIN and self.resolve():
            # El guardado ya terminó; una breve salida visual evita el cierre brusco.
            def animate_hide():
                if not user32.AnimateWindow(self.hwnd, 160, AW_HIDE | AW_BLEND):
                    user32.ShowWindow(self.hwnd, SW_HIDE)
            self._ui(animate_hide)

    # ---- persistencia ------------------------------------------------------
    def geometry(self):
        """Tamaño/posición «restaurados» + si está maximizada (sobrevive a maximizar)."""
        w = self.window.width or 1380
        h = self.window.height or 900
        x, y = self.window.x, self.window.y
        maximized = False
        wp = self._placement()
        if wp:
            maximized = wp.showCmd == SW_SHOWMAXIMIZED
            r = wp.rcNormalPosition
            if r.right - r.left >= MIN_W and r.bottom - r.top >= MIN_H:
                w, h, x, y = r.right - r.left, r.bottom - r.top, r.left, r.top
        return {'w': w, 'h': h, 'x': x, 'y': y, 'maximized': maximized}

    def save_geometry(self):
        with self._lock:
            try:
                from .database import configurar
                payload = json.dumps(self.geometry())
                with closing(sqlite3.connect(self.db_path, timeout=0.2)) as db, db:
                    configurar(db, 'window_geometry', payload)
            except Exception:
                pass
