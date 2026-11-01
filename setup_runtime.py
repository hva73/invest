"""Run from cPanel after installing requirements.txt. Never prints keys."""
import app,oauth
app.init();oauth.setup_key()
print('Privat tokenkryptering er klargjort. Ingen Pluto-login eller handel er udført.')
