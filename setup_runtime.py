"""Run from cPanel after installing requirements.txt. Never prints keys."""
import app,oauth,web_push
app.init();oauth.setup_key();web_push.setup_key()
print('Privat tokenkryptering og notifikationsnøgle er klargjort. Ingen Pluto-login eller handel er udført.')
