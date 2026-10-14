# pico-casa

Automatizaciones de casa con Raspberry Pi Pico W, controladas por Telegram.

- `/pc`: prende la PC por Wake-on-LAN
- LED: apagado si Hermes está caído, fijo si está online, titila si además juega Boca
- Telegram avisa cuando Hermes se cae o la PC se prende

## Archivos
- `app.py`: la lógica. Es lo único que vive en este repo; se actualiza en la Pico con `/update`.
- `main.py` y `config.py`: van solo en la Pico. `config.py` tiene las claves y nunca se sube.

Comandos: `/pc` `/estado` `/log` `/update` `/rollback` `/reset` `/ayuda`
