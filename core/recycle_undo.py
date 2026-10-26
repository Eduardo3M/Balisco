"""Restore an item moved to the Windows Recycle Bin by this app."""
import base64
import os
from pathlib import Path
import subprocess
import time


_RESTORE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$original = [IO.Path]::GetFullPath($env:BALISCO_UNDO_PATH).TrimEnd('\')
$shell = New-Object -ComObject Shell.Application
$bin = $shell.Namespace(10)
if ($null -eq $bin) { throw 'No se pudo abrir la papelera de Windows' }
$matches = @($bin.Items() | Where-Object {
    $parent = $_.ExtendedProperty('System.Recycle.DeletedFrom')
    $parent -and [string]::Equals(
        [IO.Path]::Combine([string]$parent, [string]$_.Name).TrimEnd('\'),
        $original, [StringComparison]::OrdinalIgnoreCase)
} | Sort-Object { $_.ExtendedProperty('System.Recycle.DateDeleted') } -Descending)
if ($matches.Count -eq 0) { throw 'El elemento ya no está en la papelera de Windows' }
$verb = @($matches[0].Verbs())[0]
if ($null -eq $verb) { throw 'Windows no ofreció la acción de restaurar' }
$verb.DoIt()
"""


def restore_from_recycle_bin(path):
    path = Path(path)
    if os.name != 'nt':
        raise OSError('Deshacer eliminaciones requiere la papelera de Windows')
    if path.exists():
        raise FileExistsError('Ya existe un archivo o carpeta en la ubicación original')
    env = os.environ.copy()
    env['BALISCO_UNDO_PATH'] = str(path)
    encoded = base64.b64encode(_RESTORE_SCRIPT.encode('utf-16le')).decode('ascii')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        env=env, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or 'No se pudo restaurar desde la papelera')
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if not path.exists():
        raise RuntimeError('Windows no restauró el elemento en su ubicación original')
