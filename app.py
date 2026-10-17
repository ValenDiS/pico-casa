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
ANUAL_CADA  = 3 * 3600  # seg entre consultas de la tabla anual
# ====================================================

led  = Pin("LED", Pin.OUT)
wlan = network.WLAN(network.STA_IF)
# fixture de Boca en todas las competencias (liga, copas), ordenado por fecha
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/%s/schedule?fixture=true"
ESPN_BYTES = 20000      # alcanza para los 2 primeros partidos (la respuesta entera pesa ~45 KB)
# Tabla anual = Apertura (tipo 1) + Clausura (tipo 6). ESPN no la da armada, se suma.
TABLA = "https://site.api.espn.com/apis/v2/sports/soccer/arg.1/standings?seasontype=%d"
TORNEOS = (1, 6)
EQUIPO = "https://sports.core.api.espn.com/v2/sports/soccer/teams/%s"   # ~5 KB, trae el país
PAISES = {"Argentina": "Argentina", "Brazil": "Brasil", "Uruguay": "Uruguay",
          "Paraguay": "Paraguay", "Chile": "Chile", "Colombia": "Colombia",
          "Ecuador": "Ecuador", "Peru": "Perú", "Bolivia": "Bolivia",
          "Venezuela": "Venezuela", "Mexico": "México", "Spain": "España",
          "United States": "Estados Unidos"}
TRADUC = (("Argentine Liga Profesional de Fútbol", "Liga Profesional"),
          ("CONMEBOL ", "Copa "), ("Round of 32", "16avos de final"),
          ("Round of 16", "Octavos de final"), ("Quarterfinals", "Cuartos de final"),
          ("Semifinals", "Semifinal"), ("Group Stage", "Fase de grupos"),
          ("Torneo ", ""), ("1st Leg", "ida"), ("2nd Leg", "vuelta"))

hermes_on = None        # desconocido hasta el primer chequeo
pc_on     = None
pc_fallos = 0
boca = {"ko": None, "rival": "", "copa": "", "local": True, "ult": 0,
        "etapa": "", "estadio": "", "escudo": "", "rival_id": "", "pais": "", "zona": "", "record": "",
        "anual": None, "ult_anual": -ANUAL_CADA, "err_anual": "cargando"}
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

def _val(s, clave, desde, hasta=None):
    # valor de texto de "clave":"..." a partir de desde (y antes de hasta)
    k = s.find(b'"' + clave.encode() + b'":"', desde)
    if k < 0 or (hasta is not None and k > hasta):
        return None, -1
    k += len(clave) + 4
    f = s.find(b'"', k)
    return s[k:f].decode(), f

def traducir(t):
    for a, b in TRADUC:
        t = t.replace(a, b)
    return t

def _get(url):
    try:
        return requests.get(url, timeout=HERMES_TIMEOUT)
    except TypeError:
        return requests.get(url)

def _leer(url, n):
    # lee solo los primeros n bytes de la respuesta, sin parsear el JSON entero
    r = _get(url)
    buf = b""
    try:
        while len(buf) < n:
            alimentar()
            c = r.raw.read(n - len(buf))
            if not c:
                break
            buf += c
    finally:
        r.close()
        gc.collect()
    return buf

def proximo_partido():
    s = _leer(ESPN % BOCA_ID, ESPN_BYTES)   # la respuesta entera pesa ~45 KB
    i = s.find(b'"events":[')
    if i < 0:
        return                                    # respuesta rara: se deja lo que había
    # del equipo (va antes de los partidos): puesto en la zona y récord G-E-P
    zona, _ = _val(s, "standingSummary", 0, i)
    rec, _ = _val(s, "recordSummary", 0, i)
    if zona:
        n = ""
        for ch in zona:
            if not ch.isdigit():
                break
            n += ch
        boca["zona"] = n
    if rec and rec.count("-") == 2:
        boca["record"] = "%sG %sE %sP" % tuple(rec.split("-"))
    if s[i + 10:i + 11] == b"]":
        boca.update(ko=None)                      # no hay partidos programados
        return
    p = i
    while True:
        p = s.find(b'"season":{', p)              # uno por partido
        if p < 0:
            return                                # se cortó la lectura: se reintenta después
        q = s.find(b'"competitors":', p)
        if q < 0:
            return
        copa, _ = _val(s, "displayName", p, q)
        etapa, _ = _val(s, "name", s.find(b'"seasonType":', p), q)
        fecha, _ = _val(s, "date", p, q)          # en UTC
        llave, _ = _val(s, "displayValue", s.find(b'"leg":', p), q) if s.find(b'"leg":', p, q) > 0 else (None, 0)
        estadio, _ = _val(s, "fullName", p, q)
        ciudad, _ = _val(s, "city", p, q)
        eq = []
        for _n in range(2):
            ha, q = _val(s, "homeAway", q)
            tid, q = _val(s, "id", q)
            nom, q = _val(s, "displayName", q)
            logo, q = _val(s, "href", q)
            if logo is None:
                return
            eq.append((tid, ha, nom, logo))
        ko = a_segundos(fecha)
        if ko + PARTIDO_MIN * 60 > time.time():   # saltea uno que ya terminó
            break
        p = q
    yo, otro = (eq[0], eq[1]) if eq[0][0] == BOCA_ID else (eq[1], eq[0])
    if copa and copa[:4].isdigit():
        copa = copa[5:]                           # "2026 Copa Argentina" -> "Copa Argentina"
    etapa = traducir(etapa or "")
    if llave:
        etapa += " " + traducir(llave)
    if estadio and ciudad and ciudad not in estadio:
        estadio += ", " + ciudad
    boca.update(ko=ko, local=yo[1] == "home", rival=otro[2], copa=traducir(copa or ""),
                etapa=etapa, estadio=estadio or "", escudo=otro[3])
    if otro[0] != boca["rival_id"]:               # el país se busca una vez por rival
        pais, _ = _val(_leer(EQUIPO % otro[0], 6000), "country", 0)
        boca.update(rival_id=otro[0], pais=PAISES.get(pais, pais or ""))

class _Flujo:
    # lee una respuesta grande de a pedazos, sin guardarla entera
    def __init__(s, r):
        s.r, s.b = r, b""
    def _mas(s):
        alimentar()
        c = s.r.raw.read(1024)
        if not c:
            return False
        s.b += c
        return True
    def saltar(s, pat):                           # avanza hasta después de pat
        while True:
            k = s.b.find(pat)
            if k >= 0:
                s.b = s.b[k + len(pat):]
                return True
            s.b = s.b[-len(pat):]
            if not s._mas():
                return False
    def hasta(s, fin):                            # devuelve lo que hay hasta fin
        while True:
            k = s.b.find(fin)
            if k >= 0:
                v = s.b[:k]
                s.b = s.b[k + 1:]
                return v
            if not s._mas():
                return None

def tabla_anual():
    tot = {}                                      # id -> [puntos, dif. de gol, jugados]
    for t in TORNEOS:
        r = _get(TABLA % t)
        try:
            f = _Flujo(r)
            while f.saltar(b'"team":{"id":"'):
                tid = f.hasta(b'"')
                v = []
                for st in (b'gamesPlayed', b'pointDifferential', b'points'):
                    if not (f.saltar(b'"name":"' + st + b'"') and f.saltar(b'"value":')):
                        raise ValueError("respuesta cortada")
                    v.append(float(f.hasta(b',').decode()))
                a = tot.setdefault(tid, [0, 0, 0])
                a[0] += v[2]; a[1] += v[1]; a[2] += v[0]
        finally:
            r.close()
            gc.collect()
    yo = tot.get(BOCA_ID.encode())
    if not yo:
        raise ValueError("Boca no está en la tabla (%d equipos)" % len(tot))
    pos = 1 + sum(1 for x in tot.values() if (x[0], x[1]) > (yo[0], yo[1]))
    boca["anual"] = (pos, int(yo[0]), int(yo[2]))
    boca["err_anual"] = None

def texto_anual():
    a = boca["anual"]
    if a:
        return "%d° · %d pts (%d PJ)" % a
    return "sin datos (%s)" % boca["err_anual"]

def cuando():
    t = time.localtime(boca["ko"] + TZ)
    hoy = time.localtime(time.time() + TZ)
    manana = time.localtime(time.time() + TZ + 86400)
    if t[:3] == hoy[:3]:
        dia = "Hoy"
    elif t[:3] == manana[:3]:
        dia = "Mañana"
    else:
        dia = "%s %02d/%02d" % (DIAS[t[6]], t[2], t[1])
    return "%s %02d:%02d" % (dia, t[3], t[4])

def competencia():
    return boca["copa"] + (" · " + boca["etapa"] if boca["etapa"] else "")

def texto_boca():
    if not boca["ko"] or (boca["ko"] <= time.time() and not jugando()):
        return "Sin próximo partido cargado"
    linea = "vs %s (%s)" % (boca["rival"], "Local" if boca["local"] else "Visitante")
    if jugando():
        return "Jugando ahora %s\n%s" % (linea, competencia())
    return "%s\n%s · %s" % (linea, competencia(), cuando())

def detalle_boca():
    if not boca["ko"] or (boca["ko"] <= time.time() and not jugando()):
        cab = "Sin próximo partido cargado"
    else:
        cab = "%s\nvs %s%s · %s\n%s\n%s" % (
            "JUGANDO AHORA" if jugando() else "Próximo partido",
            boca["rival"], " (%s)" % boca["pais"] if boca["pais"] not in ("", "Argentina") else "",
            "Local" if boca["local"] else "Visitante", competencia(), cuando())
        if boca["estadio"]:
            cab += "\n" + boca["estadio"]
    zona = "Clausura: %s° en la zona" % boca["zona"] if boca["zona"] else "Clausura"
    if boca["record"]:
        zona += " · " + boca["record"]
    return "%s\n\n%s\nTabla anual: %s" % (cab, zona, texto_anual())

def foto(url, texto):
    url_tg = "https://api.telegram.org/bot%s/sendPhoto" % C.TG_TOKEN
    datos = {"chat_id": C.TG_CHAT_ID, "photo": url, "caption": texto}
    alimentar()
    try:
        r = requests.post(url_tg, json=datos, timeout=HERMES_TIMEOUT)
    except TypeError:
        r = requests.post(url_tg, json=datos)
    try:
        return r.status_code == 200
    finally:
        r.close()
        gc.collect()

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
    elif now - boca["ult_anual"] >= ANUAL_CADA:
        boca["ult_anual"] = now
        try:
            tabla_anual()
        except Exception as e:
            boca["err_anual"] = repr(e)
            gc.collect()


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
        return "PC: %s\nHermes: %s" % (
            "Prendida ✅" if pc_on else "Apagada",
            "Online ✅" if hermes_on else "Caído ❌")
    if cmd.startswith("/boca"):
        txt = detalle_boca()
        if boca["escudo"] and boca["ko"]:
            try:
                if foto(boca["escudo"], txt):
                    return None
            except Exception:
                pass
        return txt
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
