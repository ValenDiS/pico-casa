# app.py - tu lógica. Este es el archivo que editás en GitHub y actualizás con /update.
# NO pongas claves acá: se leen de config.py, que queda solo en la Pico.
#
# - /pc: Wake-on-LAN a la PC
# - LED: apagado si Hermes está caído, fijo si está online,
#        titila si Hermes está online y juega Boca (fixture de ESPN)
# - Telegram avisa solo cuando Hermes se cae o la PC se prende

import network, socket, time, gc
from machine import Pin
import config as C
try:
    import requests
except ImportError:
    import urequests as requests

# ===== ajustes (se pueden cambiar desde GitHub) =====
HERMES_URL  = "https://mihermes.duckdns.org/api/yo"   # sin sesión responde {"usuario":null} al instante
HERMES_TIMEOUT = 6      # seg de espera antes de darlo por caído (menos que el watchdog de 8 s)
PC_PUERTO   = 445       # puerto que Windows tenga abierto (445 o 3389)
BOCA_ID     = "5"       # Boca Juniors en ESPN (verificado)
PARTIDO_MIN = 120       # minutos que titila desde el arranque del partido
TZ          = -3 * 3600

HERMES_CADA = 60        # seg entre chequeos de Hermes
PC_CADA     = 15        # seg entre chequeos de la PC
PC_FALLOS   = 4         # chequeos seguidos sin respuesta para darla por apagada (~1 min)
BOCA_CADA   = 3600      # seg entre consultas del próximo partido
# ====================================================

led  = Pin("LED", Pin.OUT)
wlan = network.WLAN(network.STA_IF)
# fixture de Boca en todas las competencias (liga, copas), ordenado por fecha
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/%s/schedule?fixture=true"
ESPN_BYTES = 20000      # alcanza para los 2 primeros partidos (la respuesta entera pesa ~45 KB)
COPAS = (("Argentine Liga Profesional de Fútbol", "Liga Profesional"),
         ("CONMEBOL ", "Copa "))

hermes_on = None        # desconocido hasta el primer chequeo
pc_on     = None
pc_fallos = 0
boca = {"ko": None, "rival": "", "copa": "", "local": True, "ult": 0}
DIAS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
t_h = t_pc = t_b = 0
blink = 0
_send = print

def alimentar():          # main.py lo reemplaza por el feed del watchdog
    pass


# ---------- utilidades ----------
def get_json(url, headers=None):
    alimentar()
    try:
        r = requests.get(url, headers=headers or {}, timeout=HERMES_TIMEOUT)
    except TypeError:
        r = requests.get(url, headers=headers or {})
    try:
        return r.json()
    finally:
        r.close()
        gc.collect()

def local():
    return time.localtime(time.time() + TZ)

def hoy():
    return "%04d-%02d-%02d" % local()[:3]

def minutos():
    t = local()
    return t[3] * 60 + t[4]

def seguro(fn):
    try:
        fn()
    except Exception as e:
        print(fn.__name__, "error:", e)
        gc.collect()


# ---------- PC ----------
def broadcast():
    ip, mask = wlan.ifconfig()[:2]
    ip = [int(x) for x in ip.split(".")]
    mask = [int(x) for x in mask.split(".")]
    return ".".join(str(i | (255 - m)) for i, m in zip(ip, mask))

def wol():
    mac = bytes(int(b, 16) for b in C.PC_MAC.replace("-", ":").split(":"))
    pkt = b"\xff" * 6 + mac * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, 0x20, 1)   # SO_BROADCAST en lwIP
    except Exception:
        pass
    for _ in range(3):
        s.sendto(pkt, (broadcast(), 9))
    s.close()

def chequear_pc():
    # prendida si su IP contesta en el puerto (aunque sea rechazando)
    global pc_on, pc_fallos
    alimentar()
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(socket.getaddrinfo(C.PC_IP, PC_PUERTO)[0][-1])
        ok = True
    except OSError as e:
        ok = bool(e.args) and e.args[0] == 111    # ECONNREFUSED: respondió
    finally:
        s.close()
    if ok:
        if pc_on is False:                        # solo avisa cuando se prende
            _send("PC prendida 🖥️✅")
        pc_on, pc_fallos = True, 0
    else:
        # un chequeo fallido suelto no alcanza: así no avisa de nuevo
        # cada vez que la PC tarda en contestar
        pc_fallos += 1
        if pc_fallos >= PC_FALLOS or pc_on is None:
            pc_on = False


# ---------- Hermes ----------
registro = []           # últimos eventos de Hermes, solo en RAM (se pierde al reiniciar)

def anotar(txt):
    t = time.localtime(time.time() + TZ)
    registro.append("%02d/%02d %02d:%02d:%02d %s" % (t[2], t[1], t[3], t[4], t[5], txt))
    if len(registro) > 20:
        registro.pop(0)

def chequear_hermes():
    # ok solo si /api/yo responde 200 con JSON que tenga "usuario":
    # un 502 de Caddy con el backend caído cuenta como caída
    global hermes_on
    detalle = ""
    try:
        alimentar()
        try:
            r = requests.get(HERMES_URL, timeout=HERMES_TIMEOUT)
        except TypeError:                         # requests sin timeout
            r = requests.get(HERMES_URL)
        try:
            ok = r.status_code == 200 and "usuario" in r.json()
            if not ok:
                detalle = "HTTP %d" % r.status_code
        except Exception:
            ok, detalle = False, "HTTP %d, no es JSON" % r.status_code
        finally:
            r.close()
    except Exception as e:
        ok, detalle = False, repr(e)
    gc.collect()
    if not ok and hermes_on is not False:         # solo avisa cuando se cae
        anotar("caído (%s)" % detalle)
        _send("Hermes se cayó ❌")
    elif ok and hermes_on is False:
        anotar("volvió")
    hermes_on = ok


# ---------- Boca ----------
def a_segundos(s):
    # "2026-10-21T00:30Z" (UTC) -> segundos en el reloj de la Pico (que está en UTC)
    return time.mktime((int(s[0:4]), int(s[5:7]), int(s[8:10]),
                        int(s[11:13]), int(s[14:16]), 0, 0, 0))

def _val(s, clave, desde):
    # valor de texto de "clave":"..." a partir de la posición desde
    k = s.find(b'"' + clave.encode() + b'":"', desde)
    if k < 0:
        return None, -1
    k += len(clave) + 4
    f = s.find(b'"', k)
    return s[k:f].decode(), f

def _leer_fixture():
    # La respuesta pesa ~45 KB: se leen solo los primeros bytes, sin parsear el JSON entero
    try:
        r = requests.get(ESPN % BOCA_ID, timeout=HERMES_TIMEOUT)
    except TypeError:
        r = requests.get(ESPN % BOCA_ID)
    buf = b""
    try:
        while len(buf) < ESPN_BYTES:
            alimentar()
            c = r.raw.read(ESPN_BYTES - len(buf))
            if not c:
                break
            buf += c
    finally:
        r.close()
        gc.collect()
    return buf

def proximo_partido():
    s = _leer_fixture()
    i = s.find(b'"events":[')
    if i < 0:
        return                                    # respuesta rara: se deja lo que había
    if s[i + 10:i + 11] == b"]":
        boca.update(ko=None)                      # no hay partidos programados
        return
    p = i
    while True:
        p = s.find(b'"season":{', p)              # uno por partido
        if p < 0:
            return                                # se cortó la lectura: se reintenta después
        copa, _ = _val(s, "displayName", p)
        fecha, _ = _val(s, "date", p)             # fecha de la competición, en UTC
        q = s.find(b'"competitors":', p)
        eq = []
        for _n in range(2):
            ha, q = _val(s, "homeAway", q)
            tid, q = _val(s, "id", q)
            nom, q = _val(s, "displayName", q)
            if nom is None:
                return
            eq.append((tid, ha, nom))
        ko = a_segundos(fecha)
        if ko + PARTIDO_MIN * 60 > time.time():   # saltea uno que ya terminó
            break
        p = q
    yo, otro = (eq[0], eq[1]) if eq[0][0] == BOCA_ID else (eq[1], eq[0])
    if copa[:4].isdigit():
        copa = copa[5:]                           # "2026 Copa Argentina" -> "Copa Argentina"
    for a, b in COPAS:
        copa = copa.replace(a, b)
    boca.update(ko=ko, local=yo[1] == "home", rival=otro[2], copa=copa)

def texto_boca():
    if not boca["ko"]:
        return "Sin próximo partido cargado"
    linea = "vs %s (%s)" % (boca["rival"], "Local" if boca["local"] else "Visitante")
    if jugando():
        return "Jugando ahora %s\n%s" % (linea, boca["copa"])
    if boca["ko"] <= time.time():
        return "Sin próximo partido cargado"
    t = time.localtime(boca["ko"] + TZ)
    hoy = time.localtime(time.time() + TZ)
    manana = time.localtime(time.time() + TZ + 86400)
    if t[:3] == hoy[:3]:
        dia = "Hoy"
    elif t[:3] == manana[:3]:
        dia = "Mañana"
    else:
        dia = "%s %02d/%02d" % (DIAS[t[6]], t[2], t[1])
    return "%s\n%s · %s %02d:%02d" % (linea, boca["copa"], dia, t[3], t[4])

def jugando():
    ko = boca["ko"]
    return ko is not None and ko <= time.time() < ko + PARTIDO_MIN * 60

def tick_boca():
    if jugando():                 # durante el partido no se toca nada
        return
    now = time.time()
    pasado = boca["ko"] is None or now >= boca["ko"] + PARTIDO_MIN * 60
    espera = 600 if pasado else BOCA_CADA
    if now - boca["ult"] >= espera:
        boca["ult"] = now
        proximo_partido()


# ---------- interfaz con main.py ----------
def setup(send):
    global _send
    _send = send

def comando(cmd):
    if cmd.startswith("/pc"):
        wol()
        return "Magic packet enviado 🖥️"
    if cmd.startswith("/log"):
        return "Caídas de Hermes:\n" + ("\n".join(registro) or "Ninguna desde el último reinicio")
    if cmd.startswith("/estado"):
        b = texto_boca()
        return "PC: %s\nHermes: %s\nBoca: %s" % (
            "Prendida ✅" if pc_on else "Apagada",
            "Online ✅" if hermes_on else "Caído ❌", b)
    return None

def tick():                       # main.py lo llama cada ~0,5 s
    global t_h, t_pc, t_b, blink
    now = time.time()
    if now - t_h >= HERMES_CADA:
        t_h = now
        seguro(chequear_hermes)
    if now - t_pc >= PC_CADA:
        t_pc = now
        seguro(chequear_pc)
    if now - t_b >= 60:
        t_b = now
        seguro(tick_boca)

    if not hermes_on:             # Hermes caído: siempre apagado
        led.value(0)
    elif jugando():               # Hermes online + Boca: titila
        blink ^= 1
        led.value(blink)
    else:                         # Hermes online: fijo
        led.value(1)
