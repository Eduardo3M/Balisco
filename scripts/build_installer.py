"""Build the Windows installer: python scripts/build_installer.py."""
import argparse
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def clean(path):
    path = Path(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT or path.is_symlink():
        raise ValueError(f'Unsafe cleanup path: {path}')
    if path.exists():
        # Refuse junctions/symlinks inside generated directories too.
        for child in path.rglob('*'):
            if child.is_symlink() or child.is_junction():
                raise ValueError(f'Linked build artifact: {child}')
        shutil.rmtree(path)


def find_iscc(explicit=None):
    candidates = [explicit, os.environ.get('ISCC'), shutil.which('ISCC.exe')]
    for base in [os.environ.get('LOCALAPPDATA', '') + '/Programs',
                 os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')]:
        candidates.extend(str(p) for p in Path(base).glob('Inno Setup*/ISCC.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError('Instala Inno Setup o indica --iscc RUTA/ISCC.exe (https://jrsoftware.org/isdl.php).')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', help='Ruta del compilador Inno Setup')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('El instalador se compila en Windows.')
    compiler = find_iscc(args.iscc)
    if not importlib.util.find_spec('PyInstaller'):
        raise RuntimeError('Instala dependencias con python -m pip install -e ".[build]"')
    version = tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    clean(ROOT/'build')
    clean(ROOT/'dist')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(ROOT/'build'/'app'), '--workpath', str(ROOT/'build'/'pyinstaller'),
                    str(ROOT/'Balisco.spec')], cwd=ROOT, check=True)
    bundle = ROOT/'build'/'app'/'Balisco'
    for name in ('index.html', 'bootstrap.js', 'app.js', 'styles.css'):
        if not (bundle/'_internal'/'ui'/name).is_file():
            raise RuntimeError(f'Falta un archivo de interfaz en el paquete: {name}')
    with tempfile.TemporaryDirectory(prefix='balisco-build-check-') as data_dir:
        smoke_env = os.environ.copy()
        smoke_env['BALISCO_DATA_DIR'] = data_dir
        subprocess.run([str(bundle/'Balisco.exe'), '--buscar', 'balisco-build-check'],
                       env=smoke_env, cwd=bundle, check=True, timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        db_files = list((Path(data_dir)/'perfiles').glob('*/biblioteca.db'))
        if not db_files:
            raise RuntimeError('El paquete no inicializó la base de datos del perfil.')
        with closing(sqlite3.connect(db_files[0])) as database:
            if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('La base del paquete no pasó la comprobación de integridad.')
    subprocess.run([compiler, '/Qp', f'/DAppVersion={version}', str(ROOT/'scripts'/'Balisco.iss')],
                   cwd=ROOT, check=True)
    output = ROOT/'dist'/f'BaliscoSetup-{version}-win-x64.exe'
    if not output.is_file():
        raise RuntimeError('Inno Setup no generó el instalador esperado.')
    clean(ROOT/'build')
    print(f'Instalador listo: {output} ({output.stat().st_size / 1024**2:.1f} MB)')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
