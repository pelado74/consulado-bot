"""
Bot de Monitoreo - Consulado de España en Buenos Aires
Con Dashboard Web incluido
"""

import requests
import time
import os
import smtplib
import threading
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytz

# ============== CONFIGURACIÓN ==============
URL_TURNOS = "https://www.cgeonline.com.ar/tramites/citas/varios/cita-varios.html?t=4"
TZ_ARGENTINA = pytz.timezone('America/Argentina/Buenos_Aires')

# Emails a notificar
EMAILS_DESTINO = ["daniel@aldeavfx.com", "sabrinalugo@gmail.com"]

# Variables de entorno (se configuran en Railway)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# Intervalos
INTERVALO_NORMAL = 5
INTERVALO_PICO = 2
COOLDOWN_NOTIFICACION = 300

# Estado global para el dashboard
estado = {
    "inicio": None,
    "verificaciones": 0,
    "ultima_verificacion": None,
    "ultimo_estado": "Iniciando...",
    "turnos_detectados": 0,
    "notificaciones_enviadas": 0,
    "errores": 0,
    "historial": []
}
ultima_notificacion = 0
# ===========================================


def hora_argentina():
    return datetime.now(TZ_ARGENTINA)


def log(mensaje, tipo="info"):
    hora = hora_argentina().strftime("%H:%M:%S")
    print(f"[{hora}] {mensaje}", flush=True)
    
    # Guardar en historial (últimos 50)
    estado["historial"].append({
        "hora": hora,
        "mensaje": mensaje,
        "tipo": tipo
    })
    if len(estado["historial"]) > 50:
        estado["historial"] = estado["historial"][-50:]


def es_horario_pico():
    ahora = hora_argentina()
    h, m = ahora.hour, ahora.minute
    return (h == 10 and m >= 55) or (h == 11 and m <= 10)


def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except:
        return False


def enviar_email(asunto, mensaje):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['Subject'] = asunto
        html = f"""
        <div style="font-family:Arial;padding:20px;text-align:center;">
            <h1 style="color:#c41e3a;">🇪🇸 ¡TURNOS DISPONIBLES!</h1>
            <p style="font-size:18px;">{mensaje}</p>
            <a href="{URL_TURNOS}" style="display:inline-block;padding:20px 40px;background:#c41e3a;color:white;text-decoration:none;font-size:24px;border-radius:10px;margin:20px;">
                👉 RESERVAR AHORA 👈
            </a>
        </div>
        """
        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        for email in EMAILS_DESTINO:
            msg['To'] = email
            server.send_message(msg)
            del msg['To']
        server.quit()
        return True
    except Exception as e:
        log(f"Error email: {e}", "error")
        return False


def notificar_todos():
    global ultima_notificacion
    ahora = time.time()
    if ahora - ultima_notificacion < COOLDOWN_NOTIFICACION:
        return
    ultima_notificacion = ahora
    estado["notificaciones_enviadas"] += 1
    
    # Telegram
    msg_tg = f"""🚨🚨🚨 <b>¡TURNOS DISPONIBLES!</b> 🚨🚨🚨

Matrícula Consular - Consulado España BA

👉 <a href="{URL_TURNOS}">CLICK AQUÍ PARA RESERVAR</a>

⚡ ¡CORRÉ! Se agotan en segundos"""
    
    if enviar_telegram(msg_tg):
        log("✅ Telegram enviado", "success")
    
    # Email
    if enviar_email("🚨 ¡TURNOS DISPONIBLES! - Consulado España", "¡Hay turnos! Entrá YA al link."):
        log("✅ Emails enviados", "success")


def verificar_turnos():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9",
        }
        r = requests.get(URL_TURNOS, headers=headers, timeout=15)
        texto = r.text.lower()
        status = r.status_code
        
        # Guardar info de debug
        estado["ultimo_status_code"] = status
        estado["ultimo_tamaño_pagina"] = len(r.text)
        
        # Detectar 404 real (en el contenido)
        if "error 404" in texto or "página no encontrada" in texto:
            return False, f"⚠️ ERROR 404 (código: {status}, tamaño: {len(r.text)})"
        
        # Detectar página correcta con mensaje de no disponibilidad
        if "en este momento no hay citas disponibles" in texto:
            return False, f"No hay citas (HTTP {status}, {len(r.text)} bytes)"
        
        # Detectar si hay turnos disponibles
        if "alta en matrícula" in texto and "no hay citas" not in texto:
            # Verificar si hay elementos de selección
            tiene_seleccion = any(x in texto for x in ["seleccione", "elegir fecha", "calendario", "horario disponible"])
            if tiene_seleccion:
                return True, "¡TURNOS DETECTADOS! - Hay opciones de selección"
            return True, "¡POSIBLES TURNOS! - Página cambió"
        
        # Estado desconocido - loguear para debug
        return False, f"Estado desconocido (HTTP {status}, {len(r.text)} bytes)"
        
    except requests.exceptions.Timeout:
        return None, "Timeout - servidor lento"
    except Exception as e:
        return None, f"Error: {str(e)[:40]}"


# ============== DASHBOARD WEB ==============
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silenciar logs HTTP
    
    def do_GET(self):
        if self.path == "/api/estado":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(estado).encode())
        elif self.path == "/api/test":
            resultado = enviar_test()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resultado).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())


def enviar_test():
    """Envía mensaje de prueba a todos los canales"""
    resultado = {"telegram": False, "email": False, "errores": []}
    hora = hora_argentina().strftime("%H:%M:%S")
    
    # Test Telegram
    msg_tg = f"""✅ <b>TEST - Bot Funcionando</b>

🕐 Hora: {hora}
📊 Verificaciones: {estado['verificaciones']}

Este es un mensaje de prueba. Cuando haya turnos, recibirás una alerta similar pero con el link para reservar."""
    
    if enviar_telegram(msg_tg):
        resultado["telegram"] = True
        log("✅ Test Telegram enviado", "success")
    else:
        resultado["errores"].append("Telegram: Token o Chat ID no configurado")
        log("❌ Test Telegram falló", "error")
    
    # Test Email
    if SMTP_EMAIL and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg['From'] = SMTP_EMAIL
            msg['Subject'] = "✅ TEST - Bot Consulado España Funcionando"
            html = f"""
            <div style="font-family:Arial;padding:20px;text-align:center;">
                <h1 style="color:#00aa55;">✅ Test Exitoso</h1>
                <p>El bot está funcionando correctamente.</p>
                <p>Hora del test: {hora}</p>
                <p>Verificaciones realizadas: {estado['verificaciones']}</p>
                <hr>
                <p style="color:#666;">Cuando haya turnos disponibles, recibirás un email con el link para reservar.</p>
            </div>
            """
            msg.attach(MIMEText(html, 'html'))
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            for email in EMAILS_DESTINO:
                msg['To'] = email
                server.send_message(msg)
                del msg['To']
            server.quit()
            resultado["email"] = True
            log("✅ Test Email enviado", "success")
        except Exception as e:
            resultado["errores"].append(f"Email: {str(e)[:50]}")
            log(f"❌ Test Email falló: {e}", "error")
    else:
        resultado["errores"].append("Email: SMTP no configurado")
    
    return resultado


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🇪🇸 Bot Consulado España</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        h1 {
            text-align: center;
            font-size: 2em;
            margin-bottom: 30px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .flag { font-size: 1.2em; }
        .status-card {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .status-indicator {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
            font-size: 1.5em;
            margin-bottom: 20px;
        }
        .pulse {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #00ff88;
            animation: pulse 2s infinite;
        }
        .pulse.error { background: #ff4757; }
        .pulse.warning { background: #ffa502; }
        .pulse.success { background: #00ff88; animation: none; }
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.2); }
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat {
            background: rgba(0,0,0,0.2);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
        }
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            color: #00ff88;
        }
        .stat-label {
            font-size: 0.85em;
            color: rgba(255,255,255,0.7);
            margin-top: 5px;
        }
        .historial {
            background: rgba(0,0,0,0.3);
            border-radius: 15px;
            padding: 20px;
            max-height: 300px;
            overflow-y: auto;
        }
        .historial h3 { margin-bottom: 15px; }
        .log-entry {
            padding: 8px 12px;
            margin: 5px 0;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.9em;
            background: rgba(255,255,255,0.05);
        }
        .log-entry.success { border-left: 3px solid #00ff88; }
        .log-entry.error { border-left: 3px solid #ff4757; }
        .log-entry .time { color: #888; margin-right: 10px; }
        .alert-banner {
            background: linear-gradient(90deg, #ff4757, #c41e3a);
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            font-size: 1.3em;
            animation: shake 0.5s infinite;
            display: none;
        }
        .alert-banner.show { display: block; }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-5px); }
            75% { transform: translateX(5px); }
        }
        .btn-reservar {
            display: inline-block;
            background: #fff;
            color: #c41e3a;
            padding: 15px 40px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: bold;
            margin-top: 15px;
            transition: transform 0.2s;
        }
        .btn-reservar:hover { transform: scale(1.05); }
        .ultima-verif { text-align: center; color: rgba(255,255,255,0.5); margin-top: 10px; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <h1><span class="flag">🇪🇸</span> Bot Consulado España</h1>
        
        <div class="alert-banner" id="alertBanner">
            🚨 ¡TURNOS DISPONIBLES! 🚨
            <br>
            <a href="https://www.cgeonline.com.ar/tramites/citas/varios/cita-varios.html?t=4" class="btn-reservar" target="_blank">
                RESERVAR AHORA
            </a>
        </div>
        
        <div class="status-card">
            <div class="status-indicator">
                <div class="pulse" id="statusPulse"></div>
                <span id="statusText">Conectando...</span>
            </div>
            
            <div class="stats">
                <div class="stat">
                    <div class="stat-value" id="verificaciones">0</div>
                    <div class="stat-label">Verificaciones</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="notificaciones">0</div>
                    <div class="stat-label">Notificaciones</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="errores">0</div>
                    <div class="stat-label">Errores</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="uptime">0h</div>
                    <div class="stat-label">Tiempo activo</div>
                </div>
            </div>
            
            <div class="stats" style="margin-top: 15px;">
                <div class="stat">
                    <div class="stat-value" id="httpCode" style="color: #ffa502;">-</div>
                    <div class="stat-label">HTTP Status</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="pageSize" style="color: #ffa502;">-</div>
                    <div class="stat-label">Tamaño página</div>
                </div>
            </div>
            
            <div class="ultima-verif">
                Última verificación: <span id="ultimaVerif">-</span>
            </div>
            
            <div style="text-align: center; margin-top: 25px;">
                <a href="https://www.cgeonline.com.ar/tramites/citas/varios/cita-varios.html?t=4" target="_blank" style="
                    display: inline-block;
                    background: linear-gradient(135deg, #ff4757 0%, #c41e3a 100%);
                    color: white;
                    text-decoration: none;
                    padding: 20px 50px;
                    border-radius: 30px;
                    font-size: 1.3em;
                    font-weight: bold;
                    cursor: pointer;
                    transition: transform 0.2s, box-shadow 0.2s;
                    box-shadow: 0 6px 20px rgba(196, 30, 58, 0.5);
                    margin-bottom: 15px;
                " onmouseover="this.style.transform='scale(1.05)'" onmouseout="this.style.transform='scale(1)'">
                    🇪🇸 SOLICITAR CITA AHORA
                </a>
            </div>
            
            <div style="text-align: center; margin-top: 15px;">
                <button id="btnTest" onclick="enviarTest()" style="
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 15px 30px;
                    border-radius: 25px;
                    font-size: 1em;
                    cursor: pointer;
                    transition: transform 0.2s, box-shadow 0.2s;
                    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
                ">
                    📨 Enviar Notificación de Prueba
                </button>
                <div id="testResult" style="margin-top: 15px; font-size: 0.9em;"></div>
            </div>
        </div>
        
        <div class="status-card historial">
            <h3>📋 Historial</h3>
            <div id="historialLogs"></div>
        </div>
    </div>
    
    <script>
        async function actualizar() {
            try {
                const r = await fetch('/api/estado');
                const data = await r.json();
                
                document.getElementById('verificaciones').textContent = data.verificaciones.toLocaleString();
                document.getElementById('notificaciones').textContent = data.notificaciones_enviadas;
                document.getElementById('errores').textContent = data.errores;
                document.getElementById('statusText').textContent = data.ultimo_estado;
                document.getElementById('ultimaVerif').textContent = data.ultima_verificacion || '-';
                
                // Calcular uptime
                if (data.inicio) {
                    const inicio = new Date(data.inicio);
                    const ahora = new Date();
                    const horas = Math.floor((ahora - inicio) / 3600000);
                    const mins = Math.floor(((ahora - inicio) % 3600000) / 60000);
                    document.getElementById('uptime').textContent = `${horas}h ${mins}m`;
                }
                
                // HTTP status y tamaño
                const httpCode = document.getElementById('httpCode');
                const pageSize = document.getElementById('pageSize');
                
                if (data.ultimo_status_code) {
                    httpCode.textContent = data.ultimo_status_code;
                    httpCode.style.color = data.ultimo_status_code === 200 ? '#00ff88' : '#ff4757';
                }
                if (data.ultimo_tamaño_pagina) {
                    const kb = (data.ultimo_tamaño_pagina / 1024).toFixed(1);
                    pageSize.textContent = kb + ' KB';
                    pageSize.style.color = data.ultimo_tamaño_pagina > 5000 ? '#00ff88' : '#ff4757';
                }
                
                // Estado del indicador
                const pulse = document.getElementById('statusPulse');
                pulse.className = 'pulse';
                if (data.ultimo_estado.includes('TURNOS') || data.turnos_detectados > 0) {
                    pulse.classList.add('success');
                    document.getElementById('alertBanner').classList.add('show');
                } else if (data.errores > 10) {
                    pulse.classList.add('error');
                }
                
                // Historial
                const historial = document.getElementById('historialLogs');
                historial.innerHTML = data.historial.slice().reverse().map(log => 
                    `<div class="log-entry ${log.tipo}"><span class="time">${log.hora}</span>${log.mensaje}</div>`
                ).join('');
                
            } catch (e) {
                document.getElementById('statusText').textContent = 'Error de conexión';
                document.getElementById('statusPulse').className = 'pulse error';
            }
        }
        
        actualizar();
        setInterval(actualizar, 2000);
        
        async function enviarTest() {
            const btn = document.getElementById('btnTest');
            const result = document.getElementById('testResult');
            
            btn.disabled = true;
            btn.innerHTML = '⏳ Enviando...';
            result.innerHTML = '';
            
            try {
                const r = await fetch('/api/test');
                const data = await r.json();
                
                let html = '';
                if (data.telegram) {
                    html += '<span style="color: #00ff88;">✅ Telegram enviado</span><br>';
                } else {
                    html += '<span style="color: #ff4757;">❌ Telegram falló</span><br>';
                }
                if (data.email) {
                    html += '<span style="color: #00ff88;">✅ Email enviado</span><br>';
                } else {
                    html += '<span style="color: #ff4757;">❌ Email no configurado</span><br>';
                }
                if (data.errores && data.errores.length > 0) {
                    html += '<br><span style="color: #ffa502; font-size: 0.85em;">' + data.errores.join('<br>') + '</span>';
                }
                result.innerHTML = html;
                
            } catch (e) {
                result.innerHTML = '<span style="color: #ff4757;">Error de conexión</span>';
            }
            
            btn.disabled = false;
            btn.innerHTML = '📨 Enviar Notificación de Prueba';
        }
    </script>
</body>
</html>
"""


def iniciar_servidor_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    log(f"🌐 Dashboard en puerto {port}")
    server.serve_forever()


# ============== LOOP PRINCIPAL ==============
def monitorear():
    log("🚀 Iniciando monitoreo...")
    estado["inicio"] = hora_argentina().isoformat()
    
    while True:
        estado["verificaciones"] += 1
        estado["ultima_verificacion"] = hora_argentina().strftime("%H:%M:%S")
        
        intervalo = INTERVALO_PICO if es_horario_pico() else INTERVALO_NORMAL
        hay_turnos, detalle = verificar_turnos()
        
        if hay_turnos is True:
            estado["turnos_detectados"] += 1
            estado["ultimo_estado"] = f"🎉 ¡TURNOS DETECTADOS!"
            log(f"🎉 ¡TURNOS DETECTADOS! - {detalle}", "success")
            notificar_todos()
        elif hay_turnos is False:
            estado["ultimo_estado"] = detalle
            if estado["verificaciones"] % 50 == 0:
                log(f"Check #{estado['verificaciones']}: {detalle}")
        else:
            estado["errores"] += 1
            estado["ultimo_estado"] = f"⚠️ {detalle}"
            log(detalle, "error")
        
        time.sleep(intervalo)


def main():
    print("=" * 50)
    print("🇪🇸 BOT CONSULADO ESPAÑA - CON DASHBOARD")
    print("=" * 50)
    
    # Iniciar servidor web en thread separado
    thread_web = threading.Thread(target=iniciar_servidor_web, daemon=True)
    thread_web.start()
    
    # Iniciar monitoreo
    monitorear()


if __name__ == "__main__":
    main()
