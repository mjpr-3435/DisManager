# Guía de DisManager

Esta guía explica desde cero cómo instalar, configurar y utilizar **DisManager**, sin dar por sentado conocimientos previos de Python.

---

## 0. Instalación desde cero (si nunca usaste Python)

Si no tienes experiencia instalando paquetes de Python, sigue estos pasos en orden:

### Paso 1: Instalar Python 3.13 o superior
- **Windows:** descarga Python desde [python.org/downloads](https://www.python.org/downloads/). Durante el instalador, marca la casilla **"Add python.exe to PATH"** antes de pulsar *Install*.
- **Linux (Ubuntu/Debian):** asegúrate de tener Python 3.13+ y el módulo `venv` instalados (por ejemplo `python3 --version`).

Para comprobar que quedó bien instalado, abre una terminal (PowerShell/CMD en Windows o Terminal en Linux) y ejecuta:

```sh
python --version
```
*(En Linux puede llamarse `python3 --version`).* Debe mostrar `3.13` o superior.

### Paso 2: Crear una carpeta para DisManager
Crea una carpeta vacía donde quieras guardar la configuración y los directorios de tus procesos, y entra en ella desde la terminal:

```sh
mkdir DisManager
cd DisManager
```

### Paso 3: Crear y activar un entorno virtual (`venv`)
Un entorno virtual aísla las librerías de DisManager del resto del sistema para evitar conflictos:

- **En Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- **En Linux / macOS:**
  ```sh
  python3 -m venv .venv
  source .venv/bin/activate
  ```

Cuando esté activo, verás `(.venv)` al principio de la línea en tu terminal. *(Cada vez que abras una terminal nueva para ejecutar DisManager, recuerda volver a activar `.venv`).*

### Paso 4: Instalar DisManager

```sh
pip install dismanager
```

---

## 1. Crear el bot de Discord

Para usar DisManager necesitas el token de un bot de Discord. Si todavía no tienes uno, puedes seguir la guía oficial de `discord.py`: [Crear una cuenta de bot](https://discordpy.readthedocs.io/en/stable/discord.html).

Puntos importantes:
1. Activa los **Privileged Gateway Intents** que necesites (en particular **Message Content Intent**, necesario para leer comandos de texto en el panel y en los hilos de consola).
2. Invita el bot a tu servidor. Se recomienda otorgarle permisos de administrador (o permisos para gestionar mensajes, canales e hilos en el canal del panel) para evitar errores al crear el panel y los hilos `Console <proceso>`.

---

## 2. Inicialización y comandos de consola local

### Inicializar (`dismanager init`)
Dentro de la carpeta donde ejecutarás DisManager (con el `.venv` activo):

```sh
dismanager init
```

Esto genera el archivo `config.yml` con las opciones básicas:
- `Bot Token`: token secreto de tu bot de Discord.
- `Bot Prefix`: prefijo para comandos en Discord (por ejemplo `!!`).
- `Panel ID`: ID del canal de texto de Discord donde DisManager publicará el panel.
- `Language`: idioma de la interfaz (`en` o `es`).
- `Backups`: cantidad máxima de copias de seguridad rotativas que se conservan por proceso.

Ejemplo de `config.yml`:

```yaml
Bot Token: "TU_TOKEN_AQUI"
Bot Prefix: "!!"
Panel ID: 123456789012345678
Language: es
Backups: 3
```

### Ejecutar (`dismanager run`)
Una vez editado `config.yml`, inicia DisManager:

```sh
dismanager run
```

Ejemplo de salida al iniciar:

```text
Initializing DisManager v1.0.0...
Your configuration has been loaded successfully.
Logged in as MiBot#1234!

Commands: start, stop, restart, kill, plreload, adreload, status, exit
>>
```

### Comandos en la consola local
Mientras DisManager está corriendo puedes escribir en el prompt `>> `:
- `start <proceso>` / `start-all`
- `stop <proceso>` / `stop-all`
- `restart <proceso>` / `restart-all`
- `kill <proceso>` / `kill-all`
- `plreload <proceso>` / `plreload-all`
- `adreload`
- `status`: muestra el estado (`En línea`/`Desconectado`) y uso de RAM de cada proceso.
- `exit`: apaga todos los procesos (espera hasta 60 segundos tras enviar `stop_command` y fuerza el cierre si no responden) y cierra DisManager.

Al pulsar `Ctrl + C`, DisManager también intenta detener los procesos de forma ordenada antes de salir.

---

## 3. Estructura de archivos

Dentro de la carpeta de ejecución (que en la interfaz llamamos `DisManager`):

- `DisManager/config.yml`: configuración general del bot.
- `DisManager/.dismanager/processes.json`: definiciones de los procesos registrados (nombre, comando de inicio, comando de apagado y blacklist).
- `DisManager/.dismanager/logs/`: logs principales de sesión de DisManager (hasta 20 sesiones recientes, 25 MB máx. por archivo) y logs de cada proceso en `.dismanager/logs/processes/<proceso>/`.
- `DisManager/.addons/`: addons globales de DisManager.
- `DisManager/.backups/<proceso>/`: copias de seguridad rotativas de cada proceso.
- `DisManager/<proceso>/`: carpeta de trabajo del proceso `<proceso>`.
- `DisManager/<proceso>/.plugins/`: plugins específicos para ese proceso.

---

## 4. Configurar los procesos

Una vez conectado el bot, el primer paso es registrar al menos un proceso pulsando el botón **Config** del panel en Discord (puedes tener hasta 15 procesos). Toda la configuración se guarda automáticamente en `.dismanager/processes.json` y se aplica al instante.

Al crear o editar un proceso se configuran cuatro campos:

- **`Name` (obligatorio):** nombre del proceso. Define cómo aparece en el panel, el nombre de su hilo (`Console <Name>`), su carpeta de trabajo (`DisManager/<Name>/`) y sus carpetas de logs/backups. Al crearlo, DisManager crea automáticamente `DisManager/<Name>/` si no existe.
- **`Start command` (obligatorio):** comando exacto que se ejecutará para iniciar el proceso (por ejemplo `python3 bot.py`, `node index.js` o `./start.sh`).
  - Por dentro, DisManager separa el comando en argumentos respetando comillas y lo lanza directamente teniendo como carpeta de trabajo (`cwd`) `DisManager/<Name>/`, sin pasar por una shell intermedia, conectando su consola para poder enviarle comandos y leer toda su salida.
  - **Recomendación (`.sh` / `.bat`):** si tu comando usa sintaxis de shell (`&&`, `|`, variables de entorno) o es muy largo, colócalo en un script dentro de `DisManager/<Name>/` y ejecuta el script:
    - En **Linux:** usa `./start.sh` (con `chmod +x start.sh`) o `bash start.sh`. Se recomienda usar `exec` en la última línea del `.sh` (por ejemplo `exec python3 main.py`) para que el proceso principal reciba directamente las señales de `kill` y no queden procesos huérfanos.
    - En **Windows:** usa `start.bat` (o `cmd /c start.bat`).
- **`Stop command` (opcional):** comando que se enviará al proceso cuando pidas detenerlo de forma ordenada (`stop`, `restart` o al apagar DisManager).
  - Si lo rellenas (por ejemplo `stop` o `exit` si tu programa lee comandos por consola), `stop` escribe ese texto en la consola del proceso para que cierre guardando datos; al apagar DisManager (`exit` / `Restart`), espera hasta 60 segundos a que termine antes de forzar el cierre.
  - Si lo dejas **vacío**, no hay apagado ordenado: ejecutar `stop` hará directamente un `kill` (cierre forzado del proceso y sus subprocesos).
- **`Blacklist` (opcional):** lista de textos de filtro, **uno por línea**, para evitar spam en Discord.
  - Funcionamiento exacto: para cada línea que imprime el proceso, DisManager comprueba si **contiene** alguno de esos textos como subcadena (**sensible a mayúsculas y minúsculas**). Por ejemplo, si pones `[DEBUG]` o `Heartbeat`, cualquier línea que incluya ese fragmento en cualquier parte se omitirá en Discord.
  - Importante: la `blacklist` **solo oculta la línea en el hilo de Discord**; la línea se sigue guardando en el log de sesión en disco (`.dismanager/logs/processes/<Name>/`) y en el archivo que devuelve el comando `logs`.
  - Si la dejas **vacía**, toda la salida del proceso (salvo líneas en blanco) se enviará al hilo de Discord.

**Ejemplo de configuración de un proceso:**
- **Name:** `mi-bot` (usará la carpeta `DisManager/mi-bot/`)
- **Start command:** `python3 main.py`
- **Stop command:** `exit` *(o vacío si el programa no acepta comandos de apagado)*
- **Blacklist:**
  ```text
  [DEBUG]
  Heartbeat OK
  ```

---

## 5. Panel de Discord

En el canal configurado en `Panel ID`, DisManager mantiene un único mensaje principal con:
- Métricas del host (CPU, RAM, almacenamiento y RAM de DisManager).
- Lista de procesos configurados con su estado (`Running`/`Closed`), consumo de RAM y mención a su hilo `Console <proceso>`.

### Hilos de consola (`Console <proceso>`)
Cada proceso tiene su propio hilo bajo el canal del panel. Todo lo que el proceso imprime en consola se guarda en su historial y se retransmite a este hilo (omitiendo solo en Discord las líneas que contengan alguno de los términos de su `blacklist`). Cualquier mensaje normal que escribas en el hilo se enviará directamente al proceso, como si lo escribieras en su consola.

Además, el hilo reconoce estos comandos directos (sin prefijo):
- `start`: inicia el proceso.
- `stop`: ejecuta el comando de apagado configurado (o fuerza el cierre si no tiene comando de apagado).
- `kill`: termina el proceso y sus subprocesos de forma inmediata.
- `restart`: detiene el proceso y vuelve a iniciarlo.
- `plreload`: recarga los plugins de `.plugins/` de ese proceso.
- `logs`: sube un archivo `.log` con el historial reciente en memoria (hasta 8 MB).

El relay empaqueta varias líneas por mensaje de Discord para respetar los límites de la API. Si un proceso genera salida más rápido de lo que Discord permite enviar y la cola alcanza 1000 líneas, DisManager conserva las líneas nuevas, descarta las más antiguas y publica un aviso con el total omitido en cuanto la cola vuelve a estabilizarse.

### Comandos de texto en el canal del panel
En el canal del panel puedes usar el prefijo configurado (por ejemplo `!!`):
- `!!start <proceso>` / `!!start-all`
- `!!stop <proceso>` / `!!stop-all`
- `!!kill <proceso>` / `!!kill-all`
- `!!restart <proceso>` / `!!restart-all`
- `!!plreload <proceso>` / `!!plreload-all`
- `!!adreload`: recarga todos los addons globales de `.addons/`.

---

## 6. Botones del panel

Debajo del embed principal aparecen cinco botones:

### Config
Abre el gestor para crear, editar o eliminar procesos desde Discord (ver detalle de cada campo en la sección **4. Configurar los procesos**). Al eliminar un proceso, pide doble confirmación si marcas la opción de borrar también la carpeta `DisManager/<Name>/`.

### Backups
Permite gestionar las copias de seguridad rotativas del proceso seleccionado (el proceso debe estar detenido para crear o restaurar un backup):
- **`[Crear copia]`:** copia los archivos del proceso a `.backups/<proceso>/<proceso> 1` rotando las copias anteriores hasta el límite de `Backups` en `config.yml`, mostrando el progreso en vivo.
- **Seleccionar una copia:** restaura esa copia reemplazando el contenido actual de la carpeta del proceso (previa confirmación).

### Files
Explorador interactivo confinado dentro de `DisManager`:
- En carpetas: permite navegar por desplegable o por índice (`Abrir por índice`), ir a una ruta (`📌` con formato `DisManager/...`), calcular el tamaño de la carpeta, crear subcarpetas, subir hasta 10 archivos, comprimir la carpeta a `.zip`, renombrar, borrar por índice o eliminar la carpeta.
- En archivos: muestra vista previa inline (imágenes hasta 8 MB, fragmentos de texto UTF-8 o árbol de contenido para `.zip`/`.tar`), botones `<` / `>` para pasar entre archivos hermanos, descarga directa (respetando el límite de subida del servidor), renombrado, edición en modal (archivos UTF-8 de hasta 4000 caracteres), extracción de `.zip` y eliminación.

### Guide
Muestra la guía de uso de DisManager directamente dentro de Discord.

### Restart
Solicita confirmación para reiniciar DisManager de forma ordenada (apagando procesos activos antes de relanzar).

---

## 7. Sistema de Addons y Plugins

DisManager permite extender su comportamiento mediante Python:
- **Addons (`.addons/`):** viven mientras DisManager esté conectado. Se recargan con `!!adreload` o `adreload`.
- **Plugins (`<proceso>/.plugins/`):** viven mientras el proceso dueño esté en ejecución. Se recargan con `plreload`.

Los módulos pueden ser archivos `.py` o carpetas con `__init__.py` dentro de `.addons/` o `.plugins/`.

### Hooks de ciclo de vida
Los métodos son opcionales (normalmente `async def`; `unload` puede ser síncrono o `async`). Puedes heredar opcionalmente de `BaseAddon` o `BasePlugin` desde `dismanager.classes` para tener tipado completo:

| Hook | En `BaseAddon` | En `BasePlugin` | Cuándo se ejecuta |
| --- | --- | --- | --- |
| `unload` | `unload(self)` | `unload(self)` | Al descargar o recargar |
| `on_addons_load` | `on_addons_load(self)` | — | Tras cargar/recargar addons |
| `on_addons_unload` | `on_addons_unload(self)` | — | Antes de descargar addons |
| `on_plugins_load` | `on_plugins_load(self, process)` | `on_plugins_load(self)` | Tras cargar/recargar plugins de un proceso |
| `on_plugins_unload` | `on_plugins_unload(self, process)` | `on_plugins_unload(self)` | Antes de descargar plugins de un proceso |
| `on_process_start` | `on_process_start(self, process)` | `on_process_start(self)` | Al iniciar el proceso |
| `on_process_stop` | `on_process_stop(self, process)` | `on_process_stop(self)` | Al solicitar `stop` o `kill` |
| `on_process_crash` | `on_process_crash(self, process)` | `on_process_crash(self)` | Cuando el proceso termina con código distinto de `0` sin haberse pedido parada |
| `on_process_log` | `on_process_log(self, process, log)` | `on_process_log(self, log)` | Por cada línea de consola que pasa la `blacklist` |

### Ejemplo de Addon (`DisManager/.addons/monitor.py`)
La clase principal debe llamarse `addon` y recibe `client: DisManagerClient`:

```python
from dismanager.classes import BaseAddon, DisManagerClient, ManagedProcess


class addon(BaseAddon):
    def __init__(self, client: DisManagerClient) -> None:
        self.client = client

    async def on_process_start(self, process: ManagedProcess) -> None:
        print(f'Proceso iniciado: {process.name}')

    async def on_process_crash(self, process: ManagedProcess) -> None:
        ultimas = process.last_logs(limit=20)
        print(f'{process.name} falló. Últimas líneas:\n' + '\n'.join(ultimas))
```

### Ejemplo de Plugin (`DisManager/<proceso>/.plugins/alertas.py`)
La clase principal debe llamarse `plugin` y recibe `process: ManagedProcess`:

```python
from dismanager.classes import BasePlugin, ManagedProcess


class plugin(BasePlugin):
    def __init__(self, process: ManagedProcess) -> None:
        self.process = process

    async def on_process_log(self, log: str) -> None:
        if 'ERROR' in log:
            await self.process.send_to_console(f'Detectado error en {self.process.name}: `{log}`')
```

---

## 8. Errores y registros

Si ocurre un error interno (en el panel, en un addon o en un plugin), DisManager:
1. Guarda el traceback completo en el log de sesión actual dentro de `DisManager/.dismanager/logs/`.
2. Envía un aviso al hilo **`Error Reports`** bajo el canal del panel (con cooldown para evitar spam).

Dentro del hilo `Error Reports` puedes usar `<prefijo>log` (por ejemplo `!!log`) para que DisManager adjunte el archivo `.log` de la sesión actual (hasta los últimos 8 MB en memoria).
