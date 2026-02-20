import requests
import time
import threading
import os
from datetime import datetime
from flask import Flask, jsonify
import pytz

app = Flask(__name__)

# --- Config ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
URL_CONSULADO = "https://www.cgeonline.com.ar/tramites/citas/varios/cita-varios.html?t=4"
URL_LINK = "https://www.cgeonline.com.ar/tramites/citas/varios/cita-varios.html?t=4"
ZONA = pytz.timezone("America/Argentina/Buenos_Aires")

# --- State ---
estado = {
    "activo": True,
    "check_count": 0,
    "ultimo_check": "Nunca",
    "ultimo_status": "Iniciando...",
    "http_status": None,
    "page_size": None,
    "hay_turnos": False,
    "historial": []
}

def log(msg):
    ahora = datetime.now(ZONA).strftime("%H:%M:%S")
    entrada = f"{ahora} {msg}"
    estado["historial"].insert(0, entrada)
    if len(estado["historial"]) > 50:
        estado["historial"].pop()
    print(entrada)

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        log(f"Error Telegram: {e}")
        return False

def check_turnos():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(URL_CONSULADO, headers=headers, timeout=15)
        estado["http_status"] = r.status_code
        estado["page_size"] = len(r.content)
        texto = r.text.lower()

        if r.status_code == 200 and "no hay citas disponibles" not in texto and len(r.content) > 3000:
            return True
        return False
    except Exception as e:
        log(f"Error al verificar: {e}")
        return False

def bot_loop():
    while True:
        if not estado["activo"]:
            time.sleep(5)
            continue

        ahora = datetime.now(ZONA)
        # Check every 2 seconds between 10:55 and 11:10, otherwise every 5 seconds
        if ahora.hour == 10 and ahora.minute >= 55:
            intervalo = 2
        elif ahora.hour == 11 and ahora.minute <= 10:
            intervalo = 2
        else:
            intervalo = 5

        hay_turnos = check_turnos()
        estado["check_count"] += 1
        estado["ultimo_check"] = datetime.now(ZONA).strftime("%H:%M:%S")

        if hay_turnos:
            estado["hay_turnos"] = True
            msg = (
                "TURNOS DISPONIBLES en el Consulado!\n\n"
                "Entra YA (copia y pega en Safari/Chrome):\n"
                + URL_LINK +
                "\n\n(Mantene presionado el link y abri en Safari/Chrome)"
            )
            send_telegram(msg)
            log("TURNOS DISPONIBLES - Notificacion enviada!")
            estado["ultimo_status"] = "TURNOS DISPONIBLES!"
        else:
            estado["hay_turnos"] = False
            size_kb = round(estado["page_size"] / 1024, 1) if estado["page_size"] else 0
            estado["ultimo_status"] = f"No hay citas (HTTP {estado['http_status']}, {size_kb} KB)"
            log(f"Check #{estado['check_count']}: {estado['ultimo_status']}")

        time.sleep(intervalo)

# --- Dashboard HTML ---
HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bot Consulado</title>
<style>
  body { font-family: monospace; background: #0d0d0d; color: #00ff88; margin: 0; padding: 20px; }
  h1 { font-size: 1.4em; margin-bottom: 5px; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
  .pulse { display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #00ff88; animation: pulse 1.5s infinite; margin-right: 8px; }
  .pulse.off { background: #ff4444; animation: none; }
  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.3)} }
  .btn { padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 1em; margin: 5px; font-family: monospace; }
  .btn-toggle { background: #f0a500; color: #000; }
  .btn-toggle.off { background: #00cc66; color: #000; }
  .btn-test { background: #6600cc; color: #fff; }
  .btn-cita { background: #cc0000; color: #fff; font-size: 1.2em; padding: 15px 30px; width: 100%; margin: 0; }
  .banner { background: #cc0000; color: #fff; text-align: center; padding: 20px; border-radius: 8px; font-size: 1.4em; font-weight: bold; animation: blink 0.5s infinite; margin-bottom: 15px; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.5} }
  .historial { max-height: 300px; overflow-y: auto; font-size: 0.85em; }
  .historial div { border-bottom: 1px solid #222; padding: 4px 0; }
  .stat { display: flex; justify-content: space-between; margin: 5px 0; }
  .ok { color: #00ff88; } .warn { color: #f0a500; } .err { color: #ff4444; }
  #result { margin-top: 10px; font-size: 0.9em; min-height: 20px; }
</style>
</head>
<body>
<h1>Bot Consulado España</h1>
<div id="banner" style="display:none" class="banner">TURNOS DISPONIBLES - ENTRA YA!</div>

<div class="card">
  <button class="btn btn-cita" onclick="window.open('""" + URL_LINK + """','_blank')">SOLICITAR CITA AHORA</button>
</div>

<div class="card">
  <div class="stat"><span><span class="pulse" id="pulso"></span><span id="estado-txt">Cargando...</span></span></div>
  <div class="stat"><span>Verificaciones:</span><span id="checks">0</span></div>
  <div class="stat"><span>Ultimo check:</span><span id="ultimo">-</span></div>
  <div class="stat"><span>HTTP Status:</span><span id="http">-</span></div>
  <div class="stat"><span>Tamano pagina:</span><span id="size">-</span></div>
</div>

<div class="card">
  <button class="btn btn-toggle" id="btn-toggle" onclick="toggleBot()">Pausar</button>
  <button class="btn btn-test" onclick="testNotif()">Enviar Notificacion de Prueba</button>
  <div id="result"></div>
</div>

<div class="card">
  <strong>Historial</strong>
  <div class="historial" id="historial"></div>
</div>

<script>
function update() {
  fetch('/api/estado').then(r=>r.json()).then(d=>{
    document.getElementById('estado-txt').textContent = d.ultimo_status;
    document.getElementById('checks').textContent = d.check_count;
    document.getElementById('ultimo').textContent = d.ultimo_check;
    document.getElementById('http').textContent = d.http_status || '-';
    document.getElementById('size').textContent = d.page_size ? Math.round(d.page_size/1024*10)/10 + ' KB' : '-';
    document.getElementById('banner').style.display = d.hay_turnos ? 'block' : 'none';
    var pulso = document.getElementById('pulso');
    pulso.className = d.activo ? 'pulse' : 'pulse off';
    var btn = document.getElementById('btn-toggle');
    btn.textContent = d.activo ? 'Pausar' : 'Activar';
    btn.className = d.activo ? 'btn btn-toggle' : 'btn btn-toggle off';
    var h = document.getElementById('historial');
    h.innerHTML = d.historial.map(function(x){return '<div>'+x+'</div>';}).join('');
  });
}
function toggleBot() {
  fetch('/api/toggle',{method:'POST'}).then(()=>update());
}
function testNotif() {
  document.getElementById('result').textContent = 'Enviando...';
  fetch('/api/test',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('result').textContent = d.telegram ? 'Telegram OK' : 'Telegram FALLO';
  });
}
update();
setInterval(update, 3000);
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return HTML

@app.route("/api/estado")
def api_estado():
    return jsonify(estado)

@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    estado["activo"] = not estado["activo"]
    log("Bot " + ("activado" if estado["activo"] else "pausado"))
    return jsonify({"activo": estado["activo"]})

@app.route("/api/test", methods=["POST"])
def api_test():
    ok = send_telegram(
        "Test de notificacion del Bot Consulado\n\nSi recibes este mensaje, Telegram funciona correctamente!\n\nLink consulado:\n" + URL_LINK
    )
    log("Test enviado - Telegram: " + ("OK" if ok else "FALLO"))
    return jsonify({"telegram": ok})

if __name__ == "__main__":
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
