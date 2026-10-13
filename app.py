# app.py - tu lógica. Este es el archivo que editás en GitHub y actualizás con /update.
# NO pongas claves acá: se leen de config.py, que queda solo en la Pico.
#
# - /pc: Wake-on-LAN a la PC
# - LED: apagado si Hermes está caído, fijo si está online,
#        titila si Hermes está online y juega Boca
# - Telegram avisa solo cuando Hermes se cae o la PC se prende

import network, socket, time, gc
from machine import Pin
import config as C
try:
    import requests
except ImportError:
    import urequests as requests

# ===== ajustes (se pueden cambiar desde GitHub) =====
HERMES_URL  = "https://mihermes.duckdns.org"
PC_PUERTO   = 445       # puerto que Windows tenga abierto (445 o 3389)
BOCA_ID     = 135156    # Boca Juniors en TheSportsDB (verificado)
PARTIDO_MIN = 120       # minutos que titila desde el arranque del partido
TZ          = -3 * 3600

HERMES_CADA = 60        # seg entre chequeos de Hermes
PC_CADA     = 15        # seg entre chequeos de la PC
BOCA_CADA   = 3600      # seg entre consultas del próximo partido
# ====================================================

led  = Pin("LED", Pin.OUT)
wlan = network.WLAN(network.STA_IF)
SPORTSDB = "https://www.thesportsdb.com/api/v1/json/123/eventsnext.php?id=%d"

hermes_on = None        # desconocido hasta el primer chequeo
pc_on     = None
boca = {"ko": None, "rival": "", "copa": "", "local": True, "ult": 0}
DIAS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
t_h = t_pc = t_b = 0
blink = 0
_send = print


# ---------- utilidades ----------
def get_json(url, headers=None):
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
    global pc_on
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(socket.getaddrinfo(C.PC_IP, PC_PUERTO)[0][-1])
        ok = True
    except OSError as e:
        ok = bool(e.args) and e.args[0] == 111    # ECONNREFUSED: respondió
    finally:
        s.close()
    if ok and pc_on is False:                     # solo avisa cuando se prende
        _send("PC prendida 🖥️✅")
    pc_on = ok


# ---------- Hermes ----------
def chequear_hermes():
    global hermes_on
    try:
        r = requests.head(HERMES_URL)
        ok = r.status_code < 500
        r.close()
    except NotImplementedError:   # redirección: el server respondió
        ok = True
    except Exception:
        ok = False
    gc.collect()
    if not ok and hermes_on is not False:         # solo avisa cuando se cae
        _send("Hermes se cayó ❌")
    hermes_on = ok


# ---------- Boca ----------
def a_segundos(s):
    # "2026-10-14T00:30:00" (UTC) -> segundos en el reloj de la Pico (que está en UTC)
    return time.mktime((int(s[0:4]), int(s[5:7]), int(s[8:10]),
                        int(s[11:13]), int(s[14:16]), 0, 0, 0))

def proximo_partido():
    ev = get_json(SPORTSDB % BOCA_ID).get("events") or []
    if ev:
        e = ev[0]
        ts = e.get("strTimestamp") or (e["dateEvent"] + "T" + e["strTime"])
        local = str(e.get("idHomeTeam")) == str(BOCA_ID)
        boca.update(ko=a_segundos(ts), local=local,
                    rival=e.get("strAwayTeam" if local else "strHomeTeam") or "?",
                    copa=e.get("strLeague") or "")

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
