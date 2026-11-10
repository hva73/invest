"""Verify a pre-confirmed Nordicway host key; never trust keyscan output alone."""
import base64,binascii,hashlib,hmac,os,re,struct

HOST='[cp14.nordicway.dk]:33'

def verify(known_host,expected_fingerprint):
 if not isinstance(known_host,str) or not isinstance(expected_fingerprint,str) or len(known_host)>2048:raise ValueError('invalid_host_key')
 if not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',expected_fingerprint.strip()):raise ValueError('invalid_fingerprint')
 lines=known_host.splitlines()
 if len(lines)!=1:raise ValueError('invalid_host_key')
 parts=lines[0].split()
 if len(parts)!=3 or parts[0]!=HOST or parts[1]!='ssh-ed25519':raise ValueError('invalid_host_key')
 try:
  raw=base64.b64decode(parts[2],validate=True)
  if len(raw)<8:raise ValueError('invalid_host_key')
  length=struct.unpack('>I',raw[:4])[0];offset=4+length
  if raw[4:offset]!=b'ssh-ed25519' or len(raw)<offset+4:raise ValueError('invalid_host_key')
  key_length=struct.unpack('>I',raw[offset:offset+4])[0]
  if key_length!=32 or len(raw)!=offset+4+key_length:raise ValueError('invalid_host_key')
 except (binascii.Error,struct.error,ValueError):raise ValueError('invalid_host_key') from None
 digest='SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode('ascii').rstrip('=')
 if not hmac.compare_digest(digest,expected_fingerprint.strip()):raise ValueError('host_key_mismatch')
 return HOST+' ssh-ed25519 '+parts[2]+'\n'

def main():
 try:verify(os.environ.get('NORDICWAY_KNOWN_HOST',''),os.environ.get('NORDICWAY_VERIFIED_FINGERPRINT',''))
 except ValueError:raise SystemExit('Host key unavailable or does not match the independently verified fingerprint.') from None
 print('Verified host key matches the configured fingerprint.')

if __name__=='__main__':main()
