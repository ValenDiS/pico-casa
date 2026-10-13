# pico-casa

Automatizaciones de casa con Raspberry Pi Pico W, controladas por Telegram.

- `/pc`: prende la PC por Wake-on-LAN; `/apagar` la apaga en 60 s (`/cancelar` lo frena)
- LED: apagado si Hermes está caído, fijo si está online, titila si además juega Boca
- Telegram avisa cuando Hermes se cae o la PC se prende

## Archivos
- `app.py`: la lógica. Es lo único que vive en este repo; se actualiza en la Pico con `/update`.
- `main.py` y `config.py`: van solo en la Pico. `config.py` tiene las claves y nunca se sube.

Comandos: `/pc` `/apagar` `/cancelar` `/estado` `/update` `/rollback` `/reset` `/ayuda`
