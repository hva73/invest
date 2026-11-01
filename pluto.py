"""Read-only OAuth resource metadata discovery. No credentials or trading calls."""
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit

MCP_URL = 'https://mcp.prod.pluto.markets/mcp'
METADATA_URLS = (
    'https://mcp.prod.pluto.markets/.well-known/oauth-protected-resource/mcp',
    'https://mcp.prod.pluto.markets/.well-known/oauth-protected-resource',
)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def discover(opener=None):
    opener=opener or urllib.request.build_opener(NoRedirect())
    attempts=[]
    for url in METADATA_URLS:
        try:
            request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'ESCAPE/0.3'})
            with opener.open(request,timeout=5) as response:
                raw=response.read(65537)
                if len(raw)>65536:raise ValueError('metadata too large')
                data=json.loads(raw)
                if not isinstance(data,dict) or data.get('resource')!=MCP_URL:
                    raise ValueError('unexpected resource')
                issuers=data.get('authorization_servers')
                if not isinstance(issuers,list) or not 1<=len(issuers)<=8:raise ValueError('missing authorization server')
                hosts=[]
                for issuer in issuers:
                    if not isinstance(issuer,str):raise ValueError('invalid issuer')
                    parsed=urlsplit(issuer)
                    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                        raise ValueError('invalid issuer')
                    # Report only the hostname. Never fetch issuer URLs supplied by metadata.
                    hosts.append(parsed.hostname)
                return {'reachable':True,'discovery_valid':True,'connected':False,'authorization_hosts':hosts,'attempts':attempts+[{'endpoint':url,'http_status':response.status}],'message':'Plutos OAuth-oplysninger er fundet. ESCAPE er endnu ikke registreret som OAuth-klient; derfor er login og porteføljer ikke tilsluttet.'}
        except urllib.error.HTTPError as error:
            attempts.append({'endpoint':url,'http_status':error.code})
        except (OSError,ValueError,TypeError):
            attempts.append({'endpoint':url,'error':'Kunne ikke hente og verificere OAuth-metadata'})
    return {'reachable':any('http_status' in a for a in attempts),'discovery_valid':False,'connected':False,'attempts':attempts,'message':'Kunne ikke verificere Plutos OAuth-oplysninger. HTTP 401/403 kan betyde adgangskrav eller en netværksafvisning. Ingen konto er forbundet.'}
