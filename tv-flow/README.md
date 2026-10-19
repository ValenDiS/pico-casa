# tv-flow

Programa aparte para la **Pico 2 W** (no la Pico W de `app.py`): abre el Launcher (o Flow si el Launcher no abre) en la TV Samsung (UN65AU7000G, Tizen 6.0) cada vez que se prende, usando la API REST de la TV en el puerto 8001.

- `GET /api/v2/` → `device.PowerState` (`"on"` = prendida)
- `POST /api/v2/applications/<APP_ID>` → abre la app (responde `true`)

## Cargarlo
1. Firmware: si no tiene MicroPython, BOOTSEL + USB y copiar el `.uf2` de [RPI_PICO2_W](https://micropython.org/download/RPI_PICO2_W/).
2. Copiar `main.py` y `config.example.py` como `config.py` a la raíz de la Pico, y completar el WiFi.
   Con mpremote: `mpremote cp main.py :main.py` y `mpremote cp config.py :config.py`.
3. Ctrl+D en Thonny y mirar la consola.

## Prueba
- TV prendida → `PowerState: 'on'`.
- Al apagarla → otro valor (`'standby'`) o `Sin respuesta`; a los ~9 s sale `TV apagada`.
  Si sigue diciendo `'on'`, `tv_state()` necesita otro criterio.
- Al prenderla → `TV encendida` y ~6 s después `App abierta`.
- Cuando ande, `DEBUG = False` en `config.py`.

## Comportamiento
- Si la Pico arranca con la TV ya prendida, no abre Flow.
- Hacen falta `OFF_CONFIRM` lecturas seguidas de "apagada" para darla por apagada: un timeout suelto no relanza Flow.
- Si se cae el WiFi no cambia el estado; ante un error inesperado reinicia la Pico.
- LED: prendido = TV prendida; titila mientras conecta el WiFi.

Pendiente de verificar: qué devuelve la TV en standby.
