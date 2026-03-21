# Guía de Configuración: Pipeline Judicial en Claude Desktop

Esta guía explica paso a paso cómo configurar Claude Desktop para ejecutar el pipeline judicial de ASERGES de forma autónoma.

## Requisitos previos

Antes de comenzar, asegurarse de tener instalado en el PC:

| Software | Cómo verificar | Cómo instalar |
|:---|:---|:---|
| Python 3.10+ | `python --version` en CMD | https://www.python.org/downloads/ |
| Claude Desktop | Abrir la aplicación | https://claude.ai/download |
| Plan Claude Pro/Team | Necesario para Projects | https://claude.ai/settings |

Instalar las dependencias Python ejecutando en CMD:

```cmd
pip install pdfplumber openai
```

Configurar la variable de entorno `OPENAI_API_KEY` en Windows:

```cmd
setx OPENAI_API_KEY "sk-tu-clave-aqui"
```

## Paso 1: Crear el Proyecto en Claude Desktop

1. Abrir **Claude Desktop**.
2. En el panel lateral izquierdo, hacer clic en **"Projects"** (icono de carpeta).
3. Hacer clic en **"New Project"**.
4. Nombre del proyecto: **Pipeline Judicial ASERGES**.
5. Hacer clic en **"Create"**.

## Paso 2: Configurar las instrucciones del proyecto

1. Dentro del proyecto recién creado, hacer clic en **"Set project instructions"** (icono de engranaje o lápiz en la parte superior).
2. Copiar y pegar **todo el contenido** del archivo `INSTRUCCIONES_PROYECTO.md` que se encuentra en esta misma carpeta.
3. Hacer clic en **"Save"**.

Estas instrucciones actúan como el "cerebro" del pipeline: le dicen a Claude qué hacer, cómo clasificar, qué plazos calcular y cómo nombrar los archivos.

## Paso 3: Subir archivos a la Knowledge Base

Dentro del proyecto, hacer clic en **"Add content"** (o el icono "+") y subir los siguientes archivos:

| Archivo | Ubicación en su PC | Función |
|:---|:---|:---|
| `pipeline_judicial.py` | `...\pipeline-judicial-aserges\scripts\` | Script principal de descarga y clasificación |
| `analisis_ia_calendar.py` | `...\pipeline-judicial-aserges\scripts\` | Script de análisis IA (referencia) |
| `config.json` | `...\pipeline-judicial-aserges\config\` | Credenciales IMAP y rutas |
| `mapeo_expedientes.json` | `...\pipeline-judicial-aserges\mapeos\` | Mapeo procedimiento a carpeta cliente |

Claude leerá estos archivos como contexto cada vez que inicie una conversación en este proyecto.

## Paso 4: Configurar MCP Filesystem Server (acceso a archivos del PC)

Para que Claude pueda leer y escribir archivos en su PC, se necesita el MCP Filesystem Server.

### Opción A: Instalar desde el directorio de extensiones (recomendado)

1. En Claude Desktop, ir a **Settings > Extensions**.
2. Hacer clic en **"Browse extensions"**.
3. Buscar **"Filesystem"** e instalar la extensión oficial.
4. Configurar las rutas permitidas:
   ```
   C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631
   ```

### Opción B: Configuración manual (si la extensión no está disponible)

1. Instalar el servidor MCP de filesystem:
   ```cmd
   npm install -g @anthropic/mcp-filesystem
   ```

2. Abrir el archivo de configuración de Claude Desktop:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

3. Añadir la siguiente configuración:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@anthropic/mcp-filesystem",
        "C:\\Users\\santi\\OneDrive - Aserges\\DOCS-MNPROGRAM_1631"
      ]
    }
  }
}
```

4. Reiniciar Claude Desktop.

## Paso 5: Configurar Google Calendar (opcional)

Para que Claude pueda agendar plazos directamente en Google Calendar:

1. En **Settings > Extensions**, buscar e instalar la extensión de **Google Calendar**.
2. Autorizar el acceso a su cuenta de Google cuando se le solicite.

Alternativamente, Claude le mostrará los plazos a agendar y usted puede crearlos manualmente.

## Cómo usar el pipeline

Una vez configurado, abrir una nueva conversación dentro del proyecto **"Pipeline Judicial ASERGES"** y escribir:

> "Ejecuta el pipeline judicial de hoy"

O para un rango de fechas:

> "Ejecuta el pipeline judicial desde el 16 de marzo hasta hoy"

Claude ejecutará automáticamente todos los pasos: descarga, clasificación, análisis, informe y propuestas de agendación.

## Automatización diaria

Claude Desktop no permite programar tareas automáticas, pero puede combinarse con el **Programador de Tareas de Windows** para la parte de descarga y clasificación:

1. Ejecutar como Administrador el archivo `configurar_tarea_programada.bat` que está en la carpeta del pipeline.
2. Esto crea dos tareas que ejecutan `pipeline_judicial.py` a las 8:00 y 20:00 de lunes a viernes.
3. Después, abrir Claude Desktop y pedirle que analice los documentos descargados.

Para automatización completa sin intervención, usar la tarea programada de **Manus** (ya configurada, se ejecuta cada 12h y envía correo con informe).

## Solución de problemas

| Problema | Solución |
|:---|:---|
| Claude no ve los archivos del PC | Verificar que el MCP Filesystem está configurado y las rutas son correctas |
| Error "pdfplumber not found" | Ejecutar `pip install pdfplumber` en CMD |
| Error de conexión IMAP | Verificar credenciales en config.json y que el firewall no bloquee el puerto 993 |
| Claude no agenda en Calendar | Verificar que la extensión Google Calendar está instalada y autorizada |
| Los PDFs no se clasifican | Verificar que `mapeo_expedientes.json` contiene el procedimiento. Añadir nuevas entradas si es necesario |
