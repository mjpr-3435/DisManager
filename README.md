# DisManager

[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/mjpr-3435/DisManager.svg)](https://github.com/mjpr-3435/DisManager/blob/main/LICENSE)

**DisManager** es una aplicación en Python para administrar múltiples procesos y retransmitir sus consolas en tiempo real a través de un bot de Discord. Es una evolución de **McDis-RCON**, construida sobre la base del proyecto anterior y las contribuciones aportadas en él (Mauricio y Elí Maciel).

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

> **Nota:** El proyecto aún está en fase de pruebas y todavía no está publicado en PyPI. Próximamente podrá instalarse directamente con:

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
- `Panel Id`: ID del canal de texto donde DisManager publicará el panel.
- `Language`: `en` o `es`.
- `Backups`: cantidad máxima de copias rotativas por proceso.

Después, inicia DisManager con:

```sh
dismanager run
```

Una vez conectado, usa el botón **Config** del panel en Discord para registrar tus procesos.
