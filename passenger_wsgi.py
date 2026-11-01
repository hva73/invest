"""WSGI entry point for a dedicated HTTPS subdomain on cPanel/Passenger.

Use a single process until sessions and login throttling use a shared store.
"""
import io
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('ESCAPE_SECURE_COOKIE', '1')
import app
app.init()

class WSGIHandler(app.Handler):
    def send_response(self, code, message=None):
        from http import HTTPStatus
        self.response_status = f'{code} {HTTPStatus(code).phrase}'
        self.response_headers = []
    def send_header(self, name, value):
        self.response_headers.append((name, str(value)))
    def end_headers(self):
        pass

def application(environ, start_response):
    handler = WSGIHandler.__new__(WSGIHandler)
    handler.path = environ.get('PATH_INFO', '/')
    handler.client_address = (environ.get('REMOTE_ADDR', 'unknown'), 0)
    handler.headers = {key[5:].replace('_', '-').title(): value for key, value in environ.items() if key.startswith('HTTP_')}
    handler.headers['Content-Length'] = environ.get('CONTENT_LENGTH') or '0'
    handler.rfile = environ['wsgi.input']
    handler.wfile = io.BytesIO()
    method = environ.get('REQUEST_METHOD', 'GET')
    if method == 'GET':
        handler.do_GET()
    elif method == 'POST':
        handler.do_POST()
    else:
        handler.send(405, {'error': 'Metoden understøttes ikke'})
    start_response(handler.response_status, handler.response_headers)
    return [handler.wfile.getvalue()]
