# DisManager

[![PyPI](https://img.shields.io/pypi/v/dismanager.svg)](https://pypi.org/project/dismanager/)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/mjpr-3435/DisManager.svg)](https://github.com/mjpr-3435/DisManager/blob/main/LICENSE)
[![Español](https://img.shields.io/badge/README-Español-brightgreen)](https://github.com/mjpr-3435/DisManager/blob/main/README.md)
[![English](https://img.shields.io/badge/README-English-blue)](https://github.com/mjpr-3435/DisManager/blob/main/docs/README.en.md)
[![Guía](https://img.shields.io/badge/Guía-Español-brightgreen)](https://github.com/mjpr-3435/DisManager/blob/main/docs/GUIDE.md)
[![Guide](https://img.shields.io/badge/Guide-English-blue)](https://github.com/mjpr-3435/DisManager/blob/main/docs/GUIDE.en.md)

**DisManager** es una aplicación en Python para administrar múltiples procesos y retransmitir sus consolas en tiempo real a través de un bot de Discord. Es una evolución de **McDis-RCON** (desarrollado a mano originalmente con las contribuciones de Mauricio y Elí Maciel); gran parte de su adaptación a esta nueva versión se realizó con **Gemini 4 Hydrogen**, combinada con partes escritas a mano y una revisión de la lógica principal adaptada por el modelo.

## Características

- **Soporte para inglés y español:** interfaz y mensajes configurables desde `config.yml`.
- **Panel interactivo en Discord:** vista general de CPU, RAM, almacenamiento y estado de cada proceso.
- **Control de procesos:** inicia, detiene, reinicia o fuerza el cierre (`start`, `stop`, `restart`, `kill` y variantes `-all`) desde el canal del panel, los hilos de consola o la consola local.
- **Retransmisión de consola y filtros:** envía la salida `stdout`/`stderr` al hilo `Console <proceso>` con soporte de `blacklist` por proceso y archivo de log descargable (`logs`).
- **Configuración desde Discord (`Config`):** crea, edita y elimina procesos directamente desde el panel (persistidos en `.dismanager/processes.json`, hasta 15 procesos).
- **Sistema de copias de seguridad (`Backups`):** crea y restaura backups rotativos por proceso con indicador de progreso.
- **Explorador de archivos (`Files`):** navega dentro del directorio de ejecución (`DisManager/...`), previsualiza texto, imágenes y contenido de archivos `.zip`/`.tar`, sube archivos, edita archivos de texto, renombra, elimina y comprime/descomprime `.zip`.
- **Plugins y Addons:** extiende cada proceso (`.plugins/`) o todo el bot (`.addons/`) con hooks de ciclo de vida (`on_process_start`, `on_process_stop`, `on_process_crash`, `on_plugins_load`, `on_plugins_unload`, `on_addons_load`, `on_addons_unload`) y recarga en caliente (`plreload`, `adreload`).
- **Registro y reporte de errores:** log de sesión de DisManager en `.dismanager/logs/` y notificaciones automáticas en el hilo `Error Reports` (descargable con `<prefijo>log`).
- **No intrusivo:** ejecuta cualquier programa o servidor mediante `subprocess.Popen` sin modificar sus archivos.

## Instalación

Requisitos: **Python 3.13 o superior**.

```sh
pip install dismanager
```

## Primeros pasos

En la carpeta donde quieras alojar los directorios de tus procesos, inicializa la configuración:

```sh
dismanager init
```

Esto creará `config.yml`, donde debes configurar:
- `Bot Token`: token de tu bot de Discord.
- `Bot Prefix`: prefijo para comandos de texto (por ejemplo `!!`).
- `Panel ID`: ID del canal de texto donde DisManager publicará el panel.
- `Language`: `en` o `es`.
- `Backups`: cantidad máxima de copias rotativas por proceso.

Después, inicia DisManager con:

```sh
dismanager run
```

Una vez conectado, usa el botón **Config** del panel en Discord para registrar tus procesos.

Para instrucciones paso a paso (incluyendo instalación desde cero, comandos, gestor de archivos, backups y addons/plugins), consulta la [Guía de uso](https://github.com/mjpr-3435/DisManager/blob/main/docs/GUIDE.md).
