"""Read-only OAuth resource metadata discovery. No credentials or trading calls."""
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit, urlunsplit

MCP_URL = 'https://mcp.prod.pluto.markets/mcp'
METADATA_URLS = (
    'https://mcp.prod.pluto.markets/.well-known/oauth-protected-resource/mcp',
    'https://mcp.prod.pluto.markets/.well-known/oauth-protected-resource',
)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def authorization_metadata(issuer,opener):
    parsed=urlsplit(issuer)
    if parsed.scheme!='https' or parsed.hostname!='mcp.prod.pluto.markets' or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return {'verified':False,'reason':'Autorisationsserver kræver særskilt verificering'}
    path=parsed.path.rstrip('/')
    metadata_url=urlunsplit(('https',parsed.netloc,'/.well-known/oauth-authorization-server'+path,'',''))
    try:
        with opener.open(urllib.request.Request(metadata_url,headers={'Accept':'application/json'}),timeout=5) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('too large')
            data=json.loads(raw)
        if data.get('issuer')!=issuer:raise ValueError('issuer mismatch')
        safe={'verified':True,'issuer':issuer}
        for key in ['authorization_endpoint','token_endpoint','registration_endpoint','revocation_endpoint']:
            value=data.get(key)
            if value:
                u=urlsplit(value)
                if u.scheme!='https' or u.hostname!=parsed.hostname or u.port not in (None,443) or u.username or u.password or u.query or u.fragment:raise ValueError('untrusted endpoint')
                safe[key]=value
        for key in ['scopes_supported','code_challenge_methods_supported','grant_types_supported','token_endpoint_auth_methods_supported','response_types_supported']:
            values=data.get(key,[])
            if not isinstance(values,list) or not all(isinstance(v,str) and len(v)<200 for v in values):raise ValueError('invalid metadata')
            safe[key]=values[:100]
        return safe
    except (OSError,ValueError,TypeError,AttributeError):
        return {'verified':False,'reason':'Autorisationsserverens metadata kunne ikke verificeres'}

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
                oauth=authorization_metadata(issuers[0],opener)
                return {'oauth':oauth,'reachable':True,'discovery_valid':True,'connected':False,'authorization_hosts':hosts,'attempts':attempts+[{'endpoint':url,'http_status':response.status}],'message':'Plutos resource-oplysninger er fundet. Autorisationsmetadata og mulighed for klientregistrering vises nedenfor. Ingen login er gennemført.'}
        except urllib.error.HTTPError as error:
            attempts.append({'endpoint':url,'http_status':error.code})
        except (OSError,ValueError,TypeError):
            attempts.append({'endpoint':url,'error':'Kunne ikke hente og verificere OAuth-metadata'})
    return {'reachable':any('http_status' in a for a in attempts),'discovery_valid':False,'connected':False,'attempts':attempts,'message':'Kunne ikke verificere Plutos OAuth-oplysninger. HTTP 401/403 kan betyde adgangskrav eller en netværksafvisning. Ingen konto er forbundet.'}
