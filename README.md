# pico-casa

Automatizaciones de casa con Raspberry Pi Pico W, controladas por Telegram.

- `/pc`: prende la PC por Wake-on-LAN
- LED: apagado si Hermes está caído, fijo si está online, titila si además juega Boca
- Telegram avisa cuando Hermes se cae o la PC se prende
- TV Samsung: al prenderse abre el Launcher (o Flow si no abre). `/tv` la prende por Wake-on-LAN (o abre el Launcher si ya está prendida)

## Archivos
- `app.py`: la lógica. Es lo único que vive en este repo; se actualiza en la Pico con `/update`.
- `main.py` y `config.py`: van solo en la Pico. `config.py` tiene las claves y nunca se sube.

- `tv-flow/`: versión standalone de lo de la TV para otra Pico. No hace falta si se usa `app.py`.

Comandos: `/pc` `/tv` `/estado` `/log` `/update` `/rollback` `/reset` `/ayuda`
