# main.py - Pico 2 W: abre Flow en la TV Samsung cada vez que la TV se prende.
# Va en la raíz de la Pico 2 W junto con config.py (ver config.example.py).

import time
import network
import urequests
import machine
import rp2
import config

TV_IP = config.TV_IP
# Apps a abrir, en orden: si la primera falla se prueba la siguiente.
APP_IDS = getattr(config, "APP_IDS", None) or [config.APP_ID]
POLL_SECONDS = getattr(config, "POLL_SECONDS", 3)
LAUNCH_DELAY_SECONDS = getattr(config, "LAUNCH_DELAY_SECONDS", 6)
OFF_CONFIRM = getattr(config, "OFF_CONFIRM", 3)   # lecturas seguidas de "apagada" para darla por apagada
DEBUG = getattr(config, "DEBUG", True)            # imprime el PowerState en cada consulta

BASE = "http://%s:8001/api/v2/" % TV_IP
led = machine.Pin("LED", machine.Pin.OUT)
wlan = network.WLAN(network.STA_IF)


def log(*a):
    if DEBUG:
        print(*a)


def connect_wifi():
    rp2.country("AR")
    wlan.active(True)
    wlan.config(pm=0xa11140)          # sin ahorro de energía: evita cortes en loops largos
    if wlan.isconnected():
        return
    wlan.disconnect()
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(30):
        if wlan.isconnected():
            print("WiFi OK", wlan.ifconfig()[0])
            return
        led.toggle()
        time.sleep(1)
    print("WiFi no conecta, reintento")


def tv_state():
    """True = prendida, False = standby/apagada, None = no se sabe (no tocar el estado)."""
    r = None
    try:
        r = urequests.get(BASE, timeout=2)
        state = r.json().get("device", {}).get("PowerState")
        log("PowerState:", repr(state))
        if state is None:
            return None               # respuesta sin PowerState: no decidir
        return state == "on"          # "standby" u otro valor -> no prendida
    except OSError as e:
        log("Sin respuesta:", e)      # apagada del todo, o red caída
        return False if wlan.isconnected() else None
    except Exception as e:
        log("Respuesta rara:", e)
        return None
    finally:
        if r:
            r.close()


def open_app(app_id):
    r = None
    try:
        r = urequests.post(BASE + "applications/" + app_id,
                           headers={"Content-Length": "0"}, timeout=5)
        text = r.text.strip()
        if text == "true":
            print("App abierta:", app_id)
            return True
        print("Respuesta al abrir", app_id, ":", text)
    except Exception as e:
        print("Fallo al abrir", app_id, ":", e)
    finally:
        if r:
            r.close()
    return False


def launch_app():
    for _ in range(3):                # la TV recién prendida a veces no responde
        for app_id in APP_IDS:
            if open_app(app_id):
                return True
        time.sleep(3)
    return False


def main():
    was_on = None      # None = todavía no se sabe (al arrancar no abre Flow si la TV ya estaba prendida)
    off_count = 0
    while True:
        if not wlan.isconnected():
            connect_wifi()
            continue
        on = tv_state()
        if on is None:
            time.sleep(POLL_SECONDS)
            continue
        if on:
            off_count = 0
            if was_on is False:
                print("TV encendida")
                time.sleep(LAUNCH_DELAY_SECONDS)
                launch_app()
            was_on = True
        else:
            # Un timeout suelto con la TV prendida no la marca como apagada;
            # si no, al volver a contestar se relanzaría Flow.
            off_count += 1
            if off_count >= OFF_CONFIRM and was_on is not False:
                if was_on:
                    print("TV apagada")
                was_on = False
        led.value(1 if was_on else 0)
        time.sleep(POLL_SECONDS)


try:
    main()
except KeyboardInterrupt:
    raise                             # Ctrl+C desde Thonny para parar
except Exception as e:
    print("Error, reinicio:", e)
    time.sleep(5)
    machine.reset()
