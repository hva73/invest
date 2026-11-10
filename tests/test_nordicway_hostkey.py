import base64,hashlib,importlib.util,os,struct,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('nordicway_hostkey',Path(__file__).resolve().parents[1]/'tools/nordicway_hostkey.py')
key=importlib.util.module_from_spec(spec);spec.loader.exec_module(key)

class HostKey(unittest.TestCase):
 def setUp(self):
  body=b'ssh-ed25519';raw=struct.pack('>I',len(body))+body+struct.pack('>I',32)+os.urandom(32)
  self.entry=key.HOST+' ssh-ed25519 '+base64.b64encode(raw).decode()
  self.fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')
 def test_requires_exact_host_and_verified_fingerprint(self):
  self.assertEqual(key.verify(self.entry,self.fingerprint),self.entry+'\n')
  for entry,fingerprint in [(self.entry,'SHA256:incorrect'),(self.entry.replace(':33',':22'),self.fingerprint),(self.entry+'\n'+self.entry,self.fingerprint),('@cert-authority '+self.entry,self.fingerprint),(self.entry.replace('ssh-ed25519','ssh-rsa',1),self.fingerprint)]:
   with self.subTest(entry=entry[:20]),self.assertRaises(ValueError):key.verify(entry,fingerprint)
 def test_rejects_invalid_or_non_ed25519_wire_key(self):
  for value in ['!!!!',base64.b64encode(b'invalid').decode(),base64.b64encode(struct.pack('>I',11)+b'ssh-ed25519'+struct.pack('>I',31)+b'x'*31).decode()]:
   with self.assertRaises(ValueError):key.verify(key.HOST+' ssh-ed25519 '+value,self.fingerprint)
if __name__=='__main__':unittest.main()
