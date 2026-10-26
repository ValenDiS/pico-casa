# main.py - arranque mínimo. Se instala UNA vez a mano y no se actualiza nunca.
# Carga nucleo.py, que sí se actualiza con /update.
#
# Si un nucleo.py recién instalado no logra hablar con Telegram en 2 arranques,
# vuelve solo al anterior y lo avisa. Si el núcleo se cae, reinicia la Pico.
#
# Para frenarlo desde Thonny: apretá Stop en los primeros 3 segundos después de
# enchufarla (o mantené apretado BOOTSEL al enchufar y soltalo a los 3 s).

import os, time, machine

PRUEBA = "prueba.txt"
MOTIVO = "reinicio.txt"


def existe(f):
    try:
        os.stat(f)
        return True
    except OSError:
        return False

def anotar(txt):
    try:
        with open(MOTIVO, "w") as f:
            f.write(txt)
    except OSError:
        pass

def volver(motivo):
    if existe("nucleo_old.py"):
        if existe("nucleo_mal.py"):
            os.remove("nucleo_mal.py")
        os.rename("nucleo.py", "nucleo_mal.py")
        os.rename("nucleo_old.py", "nucleo.py")
        anotar("volví al núcleo anterior porque el nuevo falló (%s)" % motivo)
    else:
        anotar("el núcleo nuevo falló (%s) y no había uno anterior" % motivo)
    if existe(PRUEBA):
        os.remove(PRUEBA)
    machine.reset()


time.sleep(3)                       # ventana para que Thonny pueda frenarlo

try:
    import rp2
    if rp2.bootsel_button():        # BOOTSEL apretado: no arranca nada
        raise SystemExit
except (ImportError, AttributeError):
    pass

if existe(PRUEBA):                  # núcleo nuevo todavía sin confirmar
    with open(PRUEBA) as f:
        n = int(f.read() or 0)
    if n >= 2:
        volver("no habló con Telegram en 2 arranques")
    with open(PRUEBA, "w") as f:
        f.write(str(n + 1))

wdt = machine.WDT(timeout=8000)     # el núcleo lo alimenta; si se traba, reinicia

try:
    import nucleo
    nucleo.main(wdt)
except Exception as e:              # Ctrl+C de Thonny no entra acá
    if existe(PRUEBA):
        volver(repr(e))
    anotar("el núcleo se cayó (%r)" % e)
    time.sleep(1)
    machine.reset()
