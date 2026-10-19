# Copiar como config.py en la Pico 2 W y completar el WiFi. config.py nunca se sube.
WIFI_SSID = "TU_RED"
WIFI_PASSWORD = "TU_CLAVE"
TV_IP = "192.168.0.5"        # conviene reservarla por DHCP en el router
# Apps a abrir en orden: Launcher y, si no abre, Flow.
APP_IDS = ["VLaunchr01.Launcher", "3202002020098"]
POLL_SECONDS = 3
LAUNCH_DELAY_SECONDS = 6
OFF_CONFIRM = 3              # lecturas seguidas de "apagada" (~9 s) para darla por apagada
DEBUG = True                 # imprime el PowerState de cada consulta; False cuando ande
