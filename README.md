# pico-casa

Automatizaciones de casa con Raspberry Pi Pico W, controladas por Telegram.

- `/pc`: prende la PC por Wake-on-LAN · `/tv`: prende la TV
- LED: apagado si Hermes está caído, fijo si está online, titila si además juega Boca
- Telegram avisa cuando Hermes se cae o la PC se prende

## Archivos
- `main.py`: arranque mínimo. Se instala una sola vez a mano y no se actualiza.
  Carga `nucleo.py` y, si una versión nueva no logra hablar con Telegram en 2 arranques, vuelve sola a la anterior.
- `nucleo.py`: WiFi, Telegram, `/update` y autorreparación (watchdog, reinicio si Telegram o el WiFi fallan, reinicio diario a las 5).
- `app.py`: PC, TV, Hermes, Boca.
- `config.py`: claves. Solo en la Pico, nunca se sube.

`/update` baja `app.py` y `nucleo.py` de este repo e instala lo que cambió.

Comandos: `/pc` `/tv` `/estado` `/boca` `/log` `/salud` `/update` `/rollback` `/rollback nucleo` `/reset` `/ayuda`
