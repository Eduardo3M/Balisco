"""Keep each Drive account's catalog and local assets in its own directory."""
from contextlib import closing
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3

from .database import conectar, configurar


PROFILE_NAME = re.compile(r'[A-Za-z0-9_-]{1,200}\Z')
SCOPED_KEYS = ('biblioteca_root_id:', 'unidad_drive:', 'migration_pending:')


class ProfileStorage:
    def __init__(self, base):
        self.base=Path(base)
        self.base.mkdir(parents=True,exist_ok=True)
        self.profiles=self.base/'perfiles'
        self.profiles.mkdir(exist_ok=True)
        self.marker=self.profiles/'perfil_activo.json'
        if not self.marker.exists():self._adopt_legacy()
        self.active=self._read_active()
        if not self.active:
            from .drive_sync import detectar_perfiles_drive
            available=[p['id'] for p in detectar_perfiles_drive() if not p.get('error')]
            if len(available)==1:self.activate(available[0])
        self.prepare(self.active)

    @staticmethod
    def _valid(profile):
        if profile and not PROFILE_NAME.fullmatch(profile):raise ValueError('Perfil de Drive inválido')
        return profile or '_sin_cuenta'

    def directory(self, profile=None):
        return self.profiles/self._valid(self.active if profile is None else profile)

    def database(self, profile=None):
        return self.directory(profile)/'biblioteca.db'

    def _read_active(self):
        try:
            value=json.loads(self.marker.read_text(encoding='utf-8')).get('perfil','')
            self._valid(value)
            return value
        except (OSError,ValueError,TypeError,AttributeError):return ''

    def _write_active(self, profile):
        temp=self.marker.with_suffix('.tmp')
        temp.write_text(json.dumps({'perfil':profile}),encoding='utf-8')
        os.replace(temp,self.marker)

    def prepare(self, profile):
        folder=self.directory(profile)
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'biblioteca.db'
        from .migrations import migrate_author,migrate_interested,migrate_legacy_course_items,migrate_item_file_types
        for migration in (migrate_author,migrate_interested,migrate_legacy_course_items,migrate_item_file_types):
            migration(path)
        with closing(conectar(path)) as db,db:
            configurar(db,'id_perfil_drive',profile)
        return folder

    def activate(self, profile):
        self._valid(profile)
        folder=self.prepare(profile)
        self._write_active(profile)
        self.active=profile
        return folder

    def _adopt_legacy(self):
        source=self.base/'biblioteca.db'
        if not source.is_file():
            self._write_active('')
            return
        with closing(sqlite3.connect(source)) as old:
            tables={row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            active_row=old.execute("SELECT valor FROM configuracion WHERE clave='id_perfil_drive'").fetchone() if 'configuracion' in tables else None
            active=active_row[0] if active_row else ''
            names=set()
            for table in ('items','container_entries','pending_container_moves'):
                if table in tables:
                    names.update(row[0] for row in old.execute('SELECT DISTINCT perfil_drive FROM '+table+" WHERE perfil_drive!=''"))
            if 'configuracion' in tables:
                names.update(key.split(':',1)[1] for (key,) in old.execute(
                    "SELECT clave FROM configuracion WHERE clave LIKE 'biblioteca_root_id:%' OR clave LIKE 'unidad_drive:%' OR clave LIKE 'migration_pending:%'"))
            if active:names.add(active)
            names={name for name in names if PROFILE_NAME.fullmatch(name)}
            if not names:names={''}
            for profile in sorted(names):
                folder=self.directory(profile)
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/'biblioteca.db'
                temporary=folder/'biblioteca.migrando.db'
                temporary.unlink(missing_ok=True)
                with closing(sqlite3.connect(temporary)) as copy:
                    old.backup(copy)
                with closing(conectar(temporary)) as copy:
                    copy.execute('PRAGMA foreign_keys=OFF')
                    with copy:
                        for table in ('container_entries','pending_container_moves','items'):
                            copy.execute('DELETE FROM '+table+' WHERE perfil_drive!=?',(profile,))
                        for key, in copy.execute('SELECT clave FROM configuracion'):
                            if any(key.startswith(prefix) and key!=prefix+profile for prefix in SCOPED_KEYS):
                                copy.execute('DELETE FROM configuracion WHERE clave=?',(key,))
                        configurar(copy,'id_perfil_drive',profile)
                os.replace(temporary,target)
                self._copy_assets(source,profile,folder)
        self._write_active(active if active in names else next(iter(sorted(names))))

    def _copy_assets(self, source, profile, folder):
        from .thumbnailer import thumbnail_name
        with closing(sqlite3.connect(folder/'biblioteca.db')) as db:
            items=db.execute('SELECT drive_id,ruta_relativa FROM items WHERE perfil_drive=?',(profile,)).fetchall()
        ids={ident for ident,_ in items}
        covers=self.base/'portadas'
        if covers.is_dir():
            destination=folder/'portadas'
            for cover in covers.glob('*.jpg'):
                if cover.stem in ids and cover.is_file() and not cover.is_symlink():
                    destination.mkdir(exist_ok=True)
                    shutil.copy2(cover,destination/cover.name)
        auto=self.base/'portadas_auto'
        if auto.is_dir():
            names={path.name:path for path in auto.glob('*.jpg') if path.is_file() and not path.is_symlink()}
            destination=folder/'portadas_auto'
            for _,relative in items:
                filename=thumbnail_name(profile,relative)
                if filename in names:
                    destination.mkdir(exist_ok=True)
                    shutil.copy2(names[filename],destination/filename)
        wallpapers=self.base/'wallpapers'
        if wallpapers.is_dir():shutil.copytree(wallpapers,folder/'wallpapers',dirs_exist_ok=True)
