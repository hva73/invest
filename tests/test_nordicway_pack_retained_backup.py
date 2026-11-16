import hashlib, io, json, sys, tarfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_pack_retained_backup as backup


class Verification(unittest.TestCase):
    def fixture(self, corrupt=False, link=False):
        db=b'synthetic database';code=b'synthetic code';key=b'synthetic key'
        digest=lambda b:hashlib.sha256(b).hexdigest()
        manifest=json.dumps({'format':1,'database_sha256':digest(db),'files':{'app.py':digest(code)},'keys':{'token.key':digest(key)}})
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as tar:
            for name,content in [('manifest.json',manifest.encode()),('escape.db',b'changed' if corrupt else db),('code/app.py',code),('token.key',key)]:
                item=tarfile.TarInfo(backup.NAME+'/'+name);item.size=len(content);tar.addfile(item,io.BytesIO(content))
            if link:
                item=tarfile.TarInfo(backup.NAME+'/unsafe');item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';tar.addfile(item)
        return out.getvalue(),manifest,len(db)

    def test_complete_backup_checks_all_manifest_hashes(self):
        data,manifest,size=self.fixture();self.assertEqual(backup.verify_archive(data,manifest,size)['verified_files'],4)

    def test_changed_database_or_link_cannot_authorize_cleanup(self):
        for options in ({'corrupt':True},{'link':True}):
            with self.assertRaises(ValueError):backup.verify_archive(*self.fixture(**options))


if __name__=='__main__':unittest.main()
