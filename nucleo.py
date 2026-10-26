# nucleo.py - WiFi, Telegram, /update y autorreparación. Se actualiza con /update.
# Lo carga main.py (el arranque mínimo, que no se toca). Si una versión nueva de este
# archivo no logra hablar con Telegram, main.py vuelve sola a la anterior.
#
# Comandos propios: /update  /rollback  /reset  /salud  /ayuda
# El resto de los comandos se los pasa a app.py
#
# Autorreparación: se reinicia si el loop se traba más de 30 s (watchdog), si Telegram
# falla ~2 min seguidos, si el WiFi no vuelve en ~3 intentos, y una vez por día a las 5.
# Al volver avisa el motivo.

import network, time, gc, os, machine, ntptime
import config as C
try:
    import requests
except ImportError:
    import urequests as requests

TG_CADA = 3
TIMEOUT = 6           # seg máximos por pedido HTTP (menos que el watchdog)
TG_FALLOS_MAX = 40    # pedidos a Telegram fallidos seguidos (~2 min) antes de reiniciarse
WIFI_FALLOS_MAX = 3   # intentos de reconexión fallidos (~1,5 min) antes de reiniciarse
WIFI_ARRANQUE_MAX = 10  # intentos de conexión al arrancar antes de reiniciarse
HORA_REINICIO = 5     # reinicio diario preventivo (libera la memoria fragmentada)
TRABA_MS = 30000      # sin señales de vida por este tiempo = trabado: el watchdog reinicia
MOTIVO = "reinicio.txt"
PRUEBA = "prueba.txt"   # existe mientras un nucleo.py nuevo no confirmó que anda
TG = "https://api.telegram.org/bot" + C.TG_TOKEN
wlan = network.WLAN(network.STA_IF)
offset = 0
wdt = None
timer = None
ult_vida = time.ticks_ms()
arranque = time.time()
tg_fallos = 0
wifi_fallos = 0
ult_error = ""


def alimentar():
    # señal de vida: el watchdog de hardware corta a los 8 s, que no alcanzan para
    # algunas conexiones lentas; un timer lo alimenta mientras haya señales de vida
    # en los últimos 30 s, y si el programa se traba de verdad, deja de alimentarlo
    global ult_vida
    ult_vida = time.ticks_ms()
    if wdt:
        wdt.feed()

def _perro(t):                    # corre en interrupción, cada 1 s
    if wdt and time.ticks_diff(time.ticks_ms(), ult_vida) < TRABA_MS:
        wdt.feed()

def arrancar_perro(w):
    global wdt, timer
    wdt = w
    alimentar()
    try:
        timer = machine.Timer(period=1000, mode=machine.Timer.PERIODIC, callback=_perro, hard=True)
    except TypeError:             # firmware sin hard=: igual sirve como soft IRQ
        timer = machine.Timer(period=1000, mode=machine.Timer.PERIODIC, callback=_perro)

def http(metodo, url, **kw):
    alimentar()
    try:
        return requests.request(metodo, url, timeout=TIMEOUT, **kw)
    except TypeError:                     # requests viejo sin timeout
        return requests.request(metodo, url, **kw)

def existe(f):
    try:
        os.stat(f)
        return True
    except OSError:
        return False

def borrar(f):
    try:
        os.remove(f)
    except OSError:
        pass


# ---------- red ----------
def wifi():
    if wlan.isconnected():
        return True
    wlan.active(True)
    try:
        wlan.disconnect()             # limpia un intento anterior trabado
    except Exception:
        pass
    wlan.connect(C.WIFI_SSID, C.WIFI_PASS)
    for _ in range(30):
        alimentar()
        if wlan.isconnected():
            print("WiFi OK:", wlan.ifconfig()[0])
            return True
        time.sleep(1)
    print("WiFi: no conecta")
    return False


# ---------- Telegram ----------
def send(txt):
    try:
        r = http("POST", TG + "/sendMessage",
                 json={"chat_id": C.TG_CHAT_ID, "text": txt})
        r.close()
    except Exception as e:
        print("send:", e)
    gc.collect()

def leer(off):
    r = http("GET", TG + "/getUpdates?timeout=0&offset=%d" % off)
    try:
        return r.json().get("result", [])
    finally:
        r.close()
        gc.collect()

def comandos():
    global offset
    cmds = []
    for u in leer(offset):
        offset = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("chat", {}).get("id") == C.TG_CHAT_ID:
            cmds.append((m.get("text") or "").strip().lower())
    return cmds


# ---------- reinicios ----------
def anotar_motivo(txt):
    # se guarda en la memoria flash para avisarlo después de reiniciar
    try:
        t = time.localtime(time.time() - 3 * 3600)
        with open(MOTIVO, "w") as f:
            f.write("%02d/%02d %02d:%02d %s" % (t[2], t[1], t[3], t[4], txt))
    except Exception:
        pass

def reiniciar(txt, motivo="pedido"):
    anotar_motivo(motivo)
    if txt:
        send(txt)
    try:
        leer(offset)          # marca como leído el comando antes de reiniciar
    except Exception:
        pass
    time.sleep(1)
    machine.reset()

def autorreinicio(motivo):
    # sin avisar antes (seguramente no hay red); avisa al volver
    anotar_motivo(motivo)
    time.sleep(1)
    machine.reset()

def avisar_reinicio():
    try:
        with open(MOTIVO) as f:
            m = f.read()
        os.remove(MOTIVO)
    except OSError:
        m = ""
        if machine.reset_cause() == machine.WDT_RESET:
            m = "el programa se trabó y lo reinició el watchdog"
    if m and "pedido" not in m and "diario" not in m:
        send("Me reinicié: " + m)

def confirmar_nucleo():
    # primera charla con Telegram de un nucleo.py recién instalado: queda confirmado
    if existe(PRUEBA):
        borrar(PRUEBA)
        send("Núcleo nuevo funcionando")

def salud():
    gc.collect()
    seg = time.time() - arranque
    try:
        rssi = "%d dBm" % wlan.status("rssi")
    except Exception:
        rssi = "?"
    return ("Memoria libre: %d KB\nWiFi: %s\nPrendida hace: %dd %dh %dm\n"
            "Fallos seguidos de Telegram: %d\nÚltimo error: %s") % (
        gc.mem_free() // 1024, rssi, seg // 86400, seg % 86400 // 3600, seg % 3600 // 60,
        tg_fallos, ult_error or "ninguno")


# ---------- actualización ----------
def bajar(nombre):
    # devuelve (código, None) o (None, error)
    url = "https://api.github.com/repos/%s/contents/%s?ref=%s" % (C.GH_REPO, nombre, C.GH_BRANCH)
    h = {"User-Agent": "pico", "Accept": "application/vnd.github.raw"}
    if C.GH_TOKEN:
        h["Authorization"] = "Bearer " + C.GH_TOKEN
    r = http("GET", url, headers=h)
    try:
        if r.status_code != 200:
            return None, "%s: GitHub respondió %d" % (nombre, r.status_code)
        src = r.text
    finally:
        r.close()
        gc.collect()
    alimentar()
    try:
        compile(src, nombre, "exec")        # chequea sintaxis antes de instalar
    except NameError:
        pass                                # firmware sin compile(): se saltea
    except SyntaxError as e:
        return None, "%s: error de sintaxis, no lo instalé (%s)" % (nombre, e)
    except Exception as e:
        return None, "%s: no lo instalé (%r)" % (nombre, e)
    gc.collect()
    return src, None

def igual(nombre, src):
    try:
        with open(nombre) as f:
            return f.read() == src
    except OSError:
        return False

def instalar(nombre, src):
    base = nombre[:-3]
    with open(base + "_new.py", "w") as f:
        f.write(src)
    if existe(nombre):
        borrar(base + "_old.py")
        os.rename(nombre, base + "_old.py")
    os.rename(base + "_new.py", nombre)

def update():
    # baja app.py y nucleo.py; instala solo lo que cambió. Devuelve (cambios, errores)
    cambios, errores = [], []
    for nombre in ("app.py", "nucleo.py"):
        src, err = bajar(nombre)
        if err:
            errores.append(err)
        elif not igual(nombre, src):
            instalar(nombre, src)
            cambios.append(nombre)
            if nombre == "nucleo.py":
                with open(PRUEBA, "w") as f:   # main.py lo vigila en los próximos arranques
                    f.write("0")
        src = None
        gc.collect()
    return cambios, errores

def rollback(nombre):
    base = nombre[:-3]
    if not existe(base + "_old.py"):
        return "No hay versión anterior de " + nombre
    os.rename(nombre, base + "_tmp.py")
    os.rename(base + "_old.py", nombre)
    os.rename(base + "_tmp.py", base + "_old.py")
    return None


# ---------- loop ----------
def main(wdt_arranque=None):
    global offset, wdt, tg_fallos, wifi_fallos, ult_error
    if wdt_arranque:                        # el watchdog lo arranca main.py
        arrancar_perro(wdt_arranque)
    intentos = 0
    while not wifi():
        intentos += 1
        if intentos >= WIFI_ARRANQUE_MAX:
            autorreinicio("no se conectaba al WiFi al arrancar")
        for _ in range(5):
            alimentar()
            time.sleep(1)
    for _ in range(5):
        alimentar()
        try:
            ntptime.settime()
            break
        except Exception:
            time.sleep(2)

    try:                                    # descarta mensajes viejos
        res = leer(-1)
        if res:
            offset = res[-1]["update_id"] + 1
    except Exception as e:
        print("tg init:", e)

    avisar_reinicio()
    if wdt is None:                         # main.py viejo, sin watchdog propio
        arrancar_perro(machine.WDT(timeout=8000))

    app = None
    try:
        import app as A
        A.alimentar = alimentar             # app.py lo llama antes de cada pedido largo
        A.setup(send)
        app = A
    except Exception as e:
        send("app.py no arranca: %r\nMandá /update con el arreglo o /rollback" % e)

    t_tg = 0
    fallando = False
    while True:
        alimentar()
        if not wlan.isconnected():
            if wifi():
                wifi_fallos = 0
            else:
                wifi_fallos += 1
                if wifi_fallos >= WIFI_FALLOS_MAX:
                    autorreinicio("el WiFi no volvía")

        t = time.localtime(time.time() - 3 * 3600)
        if t[0] >= 2025 and t[3] == HORA_REINICIO and time.time() - arranque > 3600:
            reiniciar("", "diario")

        if time.time() - t_tg >= TG_CADA:
            t_tg = time.time()
            try:
                cmds = comandos()
                tg_fallos = 0
                confirmar_nucleo()
            except Exception as e:
                print("tg:", e)
                ult_error = repr(e)
                cmds = []
                tg_fallos += 1
                if tg_fallos >= TG_FALLOS_MAX:
                    autorreinicio("Telegram falló %d veces seguidas (%s)" % (tg_fallos, ult_error))
            for c in cmds:
                if c.startswith("/update"):
                    send("Bajando de GitHub...")
                    try:
                        cambios, errores = update()
                    except Exception as e:
                        cambios, errores = [], [repr(e)]
                    txt = "\n".join(errores)
                    if cambios:
                        reiniciar((txt + "\n" if txt else "") +
                                  "Instalado: %s. Reiniciando" % ", ".join(cambios))
                    else:
                        send(txt or "Ya estaba todo actualizado")
                elif c.startswith("/rollback"):
                    nombre = "nucleo.py" if "nucleo" in c else "app.py"
                    err = rollback(nombre)
                    if err:
                        send(err)
                    else:
                        reiniciar("Volví a la versión anterior de %s, reiniciando" % nombre)
                elif c.startswith("/reset"):
                    reiniciar("Reiniciando")
                elif c.startswith("/salud"):
                    send(salud())
                elif c.startswith("/ayuda"):
                    send("/pc  /tv  /estado  /boca  /log  /salud  /update  /rollback  "
                         "/rollback nucleo  /reset")
                elif app:
                    try:
                        resp = app.comando(c)
                        if resp:
                            send(resp)
                    except Exception as e:
                        send("Error en el comando: %r" % e)

        if app:
            try:
                app.tick()
                fallando = False
            except Exception as e:
                if not fallando:            # avisa una vez, no spamea
                    send("Error en app.py: %r" % e)
                    fallando = True
        time.sleep(0.5)
