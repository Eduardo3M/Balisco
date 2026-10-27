"""Keep older UI smoke fixtures focused on their isolated catalog behavior."""
from core.desktop_api import DesktopAPI as RealDesktopAPI


class DesktopAPI(RealDesktopAPI):
    def _dispatch(self, db, action, payload):
        if action=='drive_status':return {'state':'ready','profile':'fixture'}
        if action=='sync':return {'indexados':0,'omitidos_proto':0,'perfil':'fixture','revinculados':0}
        if action=='cover_batch_check':return {'imported':0}
        return super()._dispatch(db,action,payload)
