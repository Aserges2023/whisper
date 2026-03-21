---
name: pipeline-judicial-aserges
description: Pipeline judicial diario autónomo para LLM de escritorio. Descarga correos IMAP de procuradores, clasifica PDFs judiciales, copia a Notificaciones y Usu2, analiza con IA (resumen, prioridad, plazos), genera informe y envía por correo. Ejecutar cuando el usuario solicite procesar notificaciones judiciales o ejecutar el pipeline judicial diario.
---

# Pipeline Judicial Diario - ASERGES (LLM Escritorio)

Automatización completa de notificaciones judiciales para el despacho Asesores y Abogados ASerges SL. Este skill permite a cualquier LLM de escritorio (Claude Desktop, Copilot, ChatGPT Desktop, etc.) ejecutar el pipeline completo de forma autónoma en un PC Windows.

## Requisitos previos

1. **Python 3.11+** instalado y en PATH
2. **Dependencias**: `pip install pdfplumber openai`
3. **Variable de entorno**: `OPENAI_API_KEY` configurada con clave válida
4. **Carpeta del pipeline**: `C:\pipeline-judicial-aserges\` con los archivos de este paquete
5. **Acceso IMAP**: Credenciales en `config\config.json`

Primera instalación: ejecutar `instalar.bat` o manualmente:
```cmd
pip install pdfplumber openai
```

## Estructura de archivos

```
C:\pipeline-judicial-aserges\
├── scripts\
│   ├── pipeline_judicial.py          # Descarga IMAP + clasificación + Notificaciones + Usu2
│   └── analisis_ia_calendar.py       # Análisis IA + cómputo plazos LEC + informe
├── config\config.json                # Credenciales IMAP, rutas, procuradores
├── mapeos\mapeo_expedientes.json     # Mapeo procedimiento -> carpeta cliente Usu2
├── ejecutar_pipeline.bat             # Lanzador rápido (doble clic)
├── instalar.bat                      # Instalador de dependencias
└── skill-llm-escritorio\
    └── SKILL.md                      # Este archivo
```

## Flujo de ejecución (5 pasos)

### Paso 1: Ejecutar descarga y clasificación

```cmd
cd C:\pipeline-judicial-aserges
python scripts\pipeline_judicial.py
```

Opciones:
- Sin argumentos: procesa correos de hoy
- `--desde 2026-03-20`: desde fecha específica
- `--desde 2026-03-16 --hasta 2026-03-21`: rango de fechas

Resultado:
- PDFs descargados y renombrados como `HHhMM - PARTE - PROCEDIMIENTO - TIPO.pdf`
- Copiados a `Notificaciones\{fecha}\`
- Clasificados en subcarpetas de `Usu2\{cliente}\`
- Informe en `judicial_diario\{fecha}\informe_clasificacion.md`

### Paso 2: Ejecutar análisis IA

```cmd
python scripts\analisis_ia_calendar.py --dir Notificaciones\{fecha} --no-agendar
```

Requiere `OPENAI_API_KEY` configurada. Usa GPT-4.1-mini para analizar cada PDF:

| Campo | Descripción |
|:---|:---|
| `resumen` | 1-2 líneas del contenido esencial |
| `prioridad` | ALTA / MEDIA / BAJA |
| `tipo_plazo` | recurso_reposicion, vista, requerimiento, etc. |
| `dias_plazo` | Días hábiles (cómputo LEC) |
| `fecha_concreta` | Fecha de vista/comparecencia si existe |
| `accion_requerida` | Qué debe hacer el abogado |

Criterios de plazo relevante (solo estos se reportan):
- Recursos frente a **Autos, Decretos o Sentencias**
- **Requerimientos** con plazo concreto
- Fechas de **vista, comparecencia o juicio**

Cómputo LEC: días hábiles excluyendo sáb/dom, festivos nacionales, La Rioja (9 junio), Semana Santa, agosto completo inhábil.

Resultado:
- `analisis_ia_resultados\analisis_ia_{fecha}.md` (informe legible)
- `analisis_ia_resultados\analisis_ia_{fecha}.json` (datos estructurados)

### Paso 3: Revisar informe y propuestas

Leer el informe generado. Presentar al usuario:
1. Resumen de documentos por prioridad
2. Lista de plazos relevantes detectados con fecha de vencimiento
3. Documentos sin mapeo (pendientes de asignación a carpeta Usu2)

### Paso 4: Agendar en calendario (manual o con API)

Si el LLM tiene acceso a Google Calendar API, agendar los plazos confirmados por el usuario:
- Hora: 08:00 del día de vencimiento
- Recordatorios: 24h y 2h antes
- Título: `JUDICIAL: Vto. {tipo_plazo} - {PARTE} {PROC}`

Si no tiene acceso a Calendar, presentar los eventos para que el usuario los agende manualmente.

### Paso 5: Gestionar archivos sin mapeo

Si hay PDFs sin carpeta Usu2 asignada:
1. Mostrar al usuario la lista de archivos pendientes
2. Preguntar a qué cliente corresponden
3. Actualizar `mapeos\mapeo_expedientes.json`:

```json
{
  "por_procedimiento": {
    "999/2026": "Nombre Cliente, Apellido"
  }
}
```

## Configuración

### config\config.json

```json
{
  "imap": {
    "host": "imap.ionos.es",
    "port": 993,
    "user": "santiago@aserges.es",
    "password": "CONTRASEÑA"
  },
  "procuradores_autorizados": [
    "solasortega.com",
    "procuradoracarmencarrasco@gmail.com",
    "belengoni.com",
    "pazmontero.com"
  ],
  "rutas_windows": {
    "base": "C:\\Users\\santi\\OneDrive - Aserges\\DOCS-MNPROGRAM_1631",
    "notificaciones": "C:\\Users\\santi\\OneDrive - Aserges\\DOCS-MNPROGRAM_1631\\Notificaciones",
    "usu2": "C:\\Users\\santi\\OneDrive - Aserges\\DOCS-MNPROGRAM_1631\\Usu2",
    "trabajo": "C:\\Users\\santi\\OneDrive - Aserges\\DOCS-MNPROGRAM_1631\\judicial_diario"
  }
}
```

### Nomenclatura de archivos

Formato: `HHhMM - PARTE - PROCEDIMIENTO - TIPO.pdf`

Tipos detectados: Auto tasacion costas, Auto admision, Auto ejecucion, Dil ordenacion, Dil requerimiento, Senalamiento vista, Sentencia definitiva, NOTIFICACION, Requerimiento, Emplazamiento.

### Procuradores autorizados

| Procurador | Identificador |
|:---|:---|
| Sola Sortega | solasortega.com |
| Carmen Carrasco | procuradoracarmencarrasco@gmail.com |
| Belén Goñi | belengoni.com |
| Paz Montero | pazmontero.com |

## Automatización diaria

Para ejecutar automáticamente cada día en Windows, crear una tarea programada:

```cmd
schtasks /create /tn "Pipeline Judicial ASERGES" /tr "C:\pipeline-judicial-aserges\ejecutar_pipeline.bat" /sc daily /st 08:00 /f
```

O usar el Programador de tareas de Windows para ejecutar a las 8:00 y 20:00 de lunes a viernes.

## Solución de problemas

| Error | Solución |
|:---|:---|
| Error IMAP | Verificar credenciales en config.json |
| pdfplumber no instalado | `pip install pdfplumber` |
| openai no instalado | `pip install openai` |
| OPENAI_API_KEY no configurada | `set OPENAI_API_KEY=sk-...` |
| Carpeta Usu2 no encontrada | Verificar ruta en config.json |
| PDF sin mapeo | Añadir en mapeo_expedientes.json |
| Plazo incorrecto | Revisar festivos en analisis_ia_calendar.py |

## Notas importantes

- **Autor de informes**: Siempre "Asesores y Abogados ASerges SL"
- **Correo de resultados**: Enviar a santi.palacios.pinillos@gmail.com
- **Plazos procesales**: Conforme a LEC (arts. 130-131) y LOPJ (arts. 182-183)
- **Agosto inhábil**: Todo el mes de agosto es inhábil (art. 183.1 LOPJ)
