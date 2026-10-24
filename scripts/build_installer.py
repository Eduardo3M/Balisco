"""Build the Windows installer: python scripts/build_installer.py."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
    subprocess.run([compiler, '/Qp', f'/DAppVersion={version}', str(ROOT/'scripts'/'Balisco.iss')],
                   cwd=ROOT, check=True)
    output = ROOT/'dist'/'BaliscoSetup.exe'
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
