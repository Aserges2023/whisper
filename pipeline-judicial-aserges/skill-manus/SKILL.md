---
name: pipeline-judicial-diario
description: Ejecuta el pipeline judicial diario de ASERGES cada 12h (L-V 8:00 y 20:00). Descarga correos IMAP de procuradores, clasifica PDFs, los copia a Notificaciones y Usu2, analiza con IA, envía informe por Gmail con propuestas de agendación, y tras respuesta del usuario agenda en Google Calendar. Usar cuando se solicite procesar notificaciones judiciales, clasificar PDFs de procuradores, o ejecutar el pipeline judicial.
---

# Pipeline Judicial Diario - ASERGES

## Flujo completo (7 pasos)

### Paso 1: Descargar PDFs de procuradores

Ejecutar el script de descarga IMAP. Buscar correos de las **últimas 12 horas** (o rango indicado por el usuario).

```bash
cd /home/ubuntu && python3.11 pipeline-judicial-aserges/scripts/pipeline_judicial.py
```

Rango personalizado: `--desde 2026-03-16 --hasta 2026-03-21`

Credenciales IMAP en `scripts/config/config.json`:
- Host: `imap.ionos.es:993`, User: `santiago@aserges.es`
- Procuradores: `solasortega.com`, `procuradoracarmencarrasco@gmail.com`, `belengoni.com`, `pazmontero.com`

El script descarga PDFs, clasifica (tipo resolución, procedimiento, partes), renombra como `HHhMM - PARTE - PROC - TIPO.pdf`, y copia a:
- `Notificaciones/{fecha}/` en sandbox y en PC (`/mnt/desktop/DOCS-MNPROGRAM_1631/Notificaciones/`)
- Subcarpeta del cliente en `Usu2/` usando `mapeos/mapeo_expedientes.json`

Copia al PC: usar `open(dst,"wb").write(open(src,"rb").read())` en Python (no shutil, FUSE es lento).

### Paso 2: Análisis IA de cada PDF

```bash
python3.11 /home/ubuntu/pipeline-judicial-aserges/scripts/analisis_ia_calendar.py --dir /home/ubuntu/Notificaciones/{fecha} --no-agendar
```

Usa GPT-4.1-mini. Devuelve por cada PDF: resumen (1-2 líneas), prioridad (ALTA/MEDIA/BAJA), plazos relevantes.

Criterios de plazo relevante (solo estos):
- Recursos frente a **Autos, Decretos o Sentencias** (reposición, apelación, casación)
- **Requerimientos** con plazo concreto
- Fechas de **vista, comparecencia o juicio**
- NO incluir plazos ordinarios de mero trámite

Cómputo plazos LEC (arts. 130-131 LEC, 182-183 LOPJ): días hábiles excluyendo sáb/dom, festivos nacionales, La Rioja (9 junio), Semana Santa (Jueves/Viernes Santo), agosto completo inhábil.

Genera: `analisis_ia_resultados/analisis_ia_{fecha}.json` y `.md`

### Paso 3: Generar PDF del informe

```bash
manus-md-to-pdf /home/ubuntu/analisis_ia_resultados/analisis_ia_{fecha}.md /home/ubuntu/analisis_ia_resultados/analisis_ia_{fecha}.pdf
```

### Paso 4: Enviar correo con informe y propuestas de agendación

Usar Gmail MCP. Construir el cuerpo del correo con:
1. Resumen: total documentos, prioridad ALTA/MEDIA/BAJA
2. Lista numerada de propuestas de agendación (solo plazos relevantes futuros)
3. Cada propuesta: `[FECHA] Tipo plazo - Proc. NNN/YYYY\n   Descripción\n   Acción requerida`
4. Pedir al usuario que responda con los números a agendar
5. Adjuntar PDF del informe

```bash
manus-mcp-cli tool call gmail_send_messages --server gmail --input '{"messages":[{"subject":"ASERGES - Informe Judicial {fecha} + Propuestas Agendación","to":["santi.palacios.pinillos@gmail.com"],"content":"...","attachments":["/ruta/al/informe.pdf"]}]}'
```

Autor: **Asesores y Abogados ASerges SL** (nunca mencionar Manus IA).

Si no hay documentos nuevos, enviar: "Sin notificaciones judiciales nuevas en este periodo."

### Paso 5: Esperar y leer respuesta del usuario

Buscar respuesta en Gmail al correo enviado. Esperar razonablemente (no bloquear).

```bash
manus-mcp-cli tool call gmail_search_messages --server gmail --input '{"q":"subject:ASERGES Informe Judicial {fecha} Propuestas","max_results":5}'
```

Luego leer el thread:

```bash
manus-mcp-cli tool call gmail_read_threads --server gmail --input '{"thread_ids":["THREAD_ID"],"include_full_messages":true}'
```

Parsear la respuesta: buscar números (ej. "Agendar 1, 3, 10" o "Agendar todas" o "Ninguna").

### Paso 6: Agendar en Google Calendar

Para cada evento confirmado, crear uno a uno:

```bash
manus-mcp-cli tool call google_calendar_create_events --server google-calendar --input '{"events":[{"summary":"JUDICIAL: Vto. {tipo_plazo} - {PARTE} {PROC}","description":"Documento: {archivo}\nResumen: {resumen}\nAcción: {accion}","start_time":"{YYYY-MM-DD}T08:00:00+01:00","end_time":"{YYYY-MM-DD}T08:30:00+01:00","reminders":[1440,120]}]}'
```

Reglas: hora 08:00, recordatorios 24h y 2h antes.

### Paso 7: Confirmar agendación

Enviar correo de confirmación al usuario indicando qué eventos se han agendado.

## Gestión de archivos sin mapeo

Si hay PDFs sin carpeta Usu2, incluirlos en el informe como "Pendientes de asignación". El usuario puede actualizar `mapeos/mapeo_expedientes.json` añadiendo:

```json
{"por_procedimiento": {"999/2026": "Nombre Cliente"}}
```

## Estructura de archivos

```
pipeline-judicial-aserges/
├── scripts/
│   ├── pipeline_judicial.py        # IMAP + clasificación + Notificaciones + Usu2
│   └── analisis_ia_calendar.py     # Análisis IA + cómputo plazos LEC
├── config/config.json              # Credenciales IMAP, rutas Windows
├── mapeos/mapeo_expedientes.json   # Mapeo procedimiento -> carpeta cliente
├── ejecutar_pipeline.bat           # Lanzador Windows
└── instalar.bat                    # Instalador dependencias Windows
```

## Autenticación Google Calendar: Modo ADC (Opción A)

El pipeline soporta dos modos de autenticación para agendar en Google Calendar:

| Modo | Cuándo usar | Requisito |
|:---|:---|:---|
| `mcp` (por defecto) | Desde Manus Cowork | Cowork activo |
| `adc` | Desde Windows Task Scheduler o sin Cowork | `configurar_adc_windows.bat` ejecutado una vez |

### Configurar modo ADC (una sola vez por equipo)

1. Instalar Google Cloud CLI: https://cloud.google.com/sdk/docs/install
2. Pedir al admin de GCP que asigne `roles/iam.serviceAccountTokenCreator` sobre la SA `pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com` a la cuenta `santiago@aserges.es`.
3. Ejecutar en el PC Windows:
   ```
   configurar_adc_windows.bat
   ```
4. Establecer variable de entorno permanente:
   ```
   setx PIPELINE_AUTH_MODE adc
   ```

### Usar modo ADC en análisis IA

```bash
python3.11 /home/ubuntu/pipeline-judicial-aserges/scripts/analisis_ia_calendar.py \
  --dir /home/ubuntu/Notificaciones/{fecha} \
  --modo-auth adc
```

O con variable de entorno:
```bash
PIPELINE_AUTH_MODE=adc python3.11 .../analisis_ia_calendar.py --dir ...
```

### Verificar ADC

```bash
python scripts\auth_adc.py
```

Salida esperada:
```
✓ Archivo ADC encontrado en disco
✓ Google Calendar API: OK (N calendarios accesibles)
✓ Gmail API: OK (cuenta: santiago@aserges.es)
```

## Solución de problemas

- **Error IMAP**: Verificar credenciales en config.json
- **Copia FUSE lenta**: Usar `open/write` byte a byte, no shutil
- **MCP Calendar/Gmail**: Invocar directamente desde shell, NO desde subprocess Python
- **PDF sin mapeo**: Añadir en mapeo_expedientes.json
- **Sin correos nuevos**: Enviar correo indicando "Sin notificaciones"
- **ADC no configurado**: Ejecutar `configurar_adc_windows.bat` y verificar con `python scripts\auth_adc.py`
- **Error `invalid_grant` OAuth**: Indica que los tokens OAuth de usuario han caducado (modo Testing, 7 días). Migrar a modo ADC con `configurar_adc_windows.bat`.
