---
name: pipeline-judicial-aserges
version: 2.0
description: >
  Pipeline judicial diario autónomo para LLM de escritorio.
  Descarga correos IMAP de procuradores, clasifica PDFs judiciales,
  copia a Notificaciones y Usu2, analiza con IA (resumen, prioridad, plazos LEC),
  genera informe, y propone agendaciones en Google Calendar.
  Ejecutar cuando el usuario solicite procesar notificaciones judiciales
  o ejecutar el pipeline judicial diario.
author: Asesores y Abogados ASerges SL
---

# Pipeline Judicial Diario - ASERGES

## Descripcion general

Este skill permite a cualquier LLM de escritorio (Claude Desktop, Copilot, ChatGPT Desktop, etc.) ejecutar de forma autonoma el pipeline completo de gestion de notificaciones judiciales del despacho **Asesores y Abogados ASerges SL**.

El pipeline realiza las siguientes operaciones en secuencia:

1. Conecta al buzon IMAP del despacho y descarga PDFs adjuntos de correos de procuradores autorizados.
2. Clasifica cada PDF extrayendo metadatos (tipo de resolucion, numero de procedimiento, partes, plazos).
3. Renombra cada PDF con formato descriptivo y lo copia a la carpeta `Notificaciones`.
4. Clasifica y copia cada PDF a la subcarpeta del cliente correspondiente en `Usu2`.
5. Analiza cada PDF con IA (GPT-4.1-mini) para obtener resumen, prioridad y plazos relevantes.
6. Genera un informe completo en Markdown y JSON.
7. Presenta al usuario las propuestas de agendacion en Google Calendar.

---

## Requisitos previos

### Software necesario

| Requisito | Comando de verificacion |
|:---|:---|
| Python 3.11+ | `python --version` |
| pdfplumber | `pip install pdfplumber` |
| openai | `pip install openai` |

### Variables de entorno

```cmd
set OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXX
```

Para hacerla permanente en Windows:
```cmd
setx OPENAI_API_KEY "sk-XXXXXXXXXXXXXXXXXXXXXXXX"
```

### Primera instalacion

Ejecutar `instalar.bat` (doble clic) o manualmente:
```cmd
pip install pdfplumber openai
```

---

## Estructura de archivos en el PC

```
C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631\pipeline-judicial-aserges\
|
+-- scripts\
|   +-- pipeline_judicial.py            # Descarga IMAP + clasificacion + Notificaciones + Usu2
|   +-- analisis_ia_calendar.py         # Analisis IA + computo plazos LEC + informe
|
+-- config\
|   +-- config.json                     # Credenciales IMAP, rutas Windows, procuradores
|
+-- mapeos\
|   +-- mapeo_expedientes.json          # Mapeo procedimiento -> carpeta cliente Usu2
|
+-- ejecutar_pipeline.bat               # Lanzador rapido (doble clic, procesa hoy)
+-- instalar.bat                        # Instalador de dependencias
+-- README.md                           # Documentacion de uso
|
+-- skill-llm-escritorio\
    +-- SKILL.md                        # Este archivo
```

### Carpetas de destino en el PC

| Carpeta | Ruta |
|:---|:---|
| Base | `C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631` |
| Notificaciones | `...\DOCS-MNPROGRAM_1631\Notificaciones\{fecha}\` |
| Usu2 (clientes) | `...\DOCS-MNPROGRAM_1631\Usu2\{nombre_cliente}\` |
| Trabajo (logs) | `...\judicial_diario\{fecha}\` |

---

## Credenciales y configuracion

### Servidor IMAP

| Parametro | Valor |
|:---|:---|
| Host | imap.ionos.es |
| Puerto | 993 (SSL) |
| Usuario | santiago@aserges.es |
| Contrasena | (en config.json) |

### Procuradores autorizados

Solo se descargan PDFs de correos procedentes de estos remitentes:

| Procurador | Identificador en correo |
|:---|:---|
| Sola Sortega | solasortega.com |
| Carmen Carrasco | procuradoracarmencarrasco@gmail.com |
| Belen Goni | belengoni.com |
| Paz Montero | pazmontero.com |

### Modelo IA

| Parametro | Valor |
|:---|:---|
| Proveedor | OpenAI |
| Modelo | gpt-4.1-mini |
| Variable | OPENAI_API_KEY |

---

## Flujo de ejecucion paso a paso

### Paso 1: Descargar y clasificar PDFs

Ejecutar desde la carpeta del pipeline:

```cmd
cd "C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631\pipeline-judicial-aserges"
python scripts\pipeline_judicial.py
```

**Opciones de fecha:**

| Modo | Comando |
|:---|:---|
| Hoy (por defecto) | `python scripts\pipeline_judicial.py` |
| Desde una fecha | `python scripts\pipeline_judicial.py --desde 2026-03-20` |
| Rango de fechas | `python scripts\pipeline_judicial.py --desde 2026-03-16 --hasta 2026-03-21` |

**Que hace este paso:**

1. Conecta al buzon IMAP y busca correos en el rango de fechas indicado.
2. Filtra solo correos de procuradores autorizados con PDFs adjuntos.
3. Descarga cada PDF a una carpeta temporal de trabajo.
4. Extrae texto del PDF con pdfplumber.
5. Identifica: numero de procedimiento, NIG, tipo de resolucion, partes, plazos.
6. Renombra el PDF con formato: `HHhMM - PARTE - PROCEDIMIENTO - TIPO.pdf`
7. Copia a `Notificaciones\{fecha}\`.
8. Busca la carpeta del cliente en `Usu2\` usando el mapeo de expedientes y copia alli.

**Tipos de resolucion detectados:**

Auto tasacion costas, Auto admision, Auto ejecucion, Auto archivo, Dil ordenacion, Dil requerimiento, Dil requerimiento datos, Dil negatoria prueba, Senalamiento vista, Sentencia definitiva, Providencia senalamiento, NOTIFICACION, Requerimiento, Emplazamiento.

**Resultado:**
- PDFs organizados en `Notificaciones\{fecha}\` y en `Usu2\{cliente}\`
- Informe de clasificacion en `judicial_diario\{fecha}\informe_clasificacion.md`
- Estadisticas en `judicial_diario\{fecha}\estadisticas.json`

---

### Paso 2: Analizar con IA

```cmd
python scripts\analisis_ia_calendar.py --dir "Notificaciones\{fecha}" --no-agendar
```

Sustituir `{fecha}` por la carpeta generada en el paso 1 (ej: `2026-03-21`).

**Que hace este paso:**

Para cada PDF, envia el texto extraido a GPT-4.1-mini con un prompt especializado en derecho procesal espanol. Obtiene:

| Campo | Descripcion |
|:---|:---|
| `resumen` | 1-2 lineas del contenido esencial del documento |
| `prioridad` | **ALTA**: Sentencias, Autos finales, Decretos archivo, requerimientos perentorios, senalamiento vista/juicio. **MEDIA**: Autos interlocutorios, Diligencias con tramite relevante, emplazamientos. **BAJA**: Notificaciones de mero tramite, acuses de recibo. |
| `tiene_plazo_relevante` | true/false. Solo true cuando hay: recurso frente a Auto/Decreto/Sentencia, requerimiento con plazo concreto, o fecha de vista/comparecencia/juicio. NO para plazos ordinarios de tramite. |
| `tipo_plazo` | recurso_reposicion, recurso_apelacion, recurso_casacion, requerimiento, vista, comparecencia, juicio, otro, ninguno |
| `dias_plazo` | Numero de dias habiles para actuar (si aplica) |
| `fecha_concreta` | Fecha YYYY-MM-DD de vista/comparecencia/juicio (si existe) |
| `accion_requerida` | Que debe hacer el abogado |

**Computo de plazos procesales conforme a la LEC:**

Los plazos se calculan en **dias habiles** conforme a los arts. 130-131 LEC y 182-183 LOPJ:

| Regla | Detalle |
|:---|:---|
| Sabados y domingos | Inhabiles |
| Agosto completo | Inhabil (art. 183.1 LOPJ) |
| Festivos nacionales | 1 ene, 6 ene, 1 may, 12 oct, 1 nov, 6 dic, 8 dic, 25 dic |
| Festivos La Rioja | 9 junio (Dia de La Rioja) |
| Semana Santa | Jueves Santo y Viernes Santo (calculo automatico de Pascua) |

**Resultado:**
- `analisis_ia_resultados\analisis_ia_{fecha}.md` (informe legible)
- `analisis_ia_resultados\analisis_ia_{fecha}.json` (datos estructurados)

---

### Paso 3: Revisar informe y presentar al usuario

Leer el informe `.md` generado. Presentar al usuario de forma clara:

1. **Resumen general**: total documentos, cuantos ALTA/MEDIA/BAJA.
2. **Documentos de prioridad ALTA**: mostrar resumen completo de cada uno con plazo y accion requerida.
3. **Propuestas de agendacion**: lista numerada de plazos relevantes con fecha de vencimiento calculada.
4. **Documentos sin mapeo**: si hay PDFs sin carpeta Usu2 asignada, listarlos y preguntar al usuario a que cliente corresponden.

Ejemplo de presentacion de propuestas:

```
PROPUESTAS DE AGENDACION:

1. [03/04/2026] Requerimiento alegaciones - THE LAST ONE COMPANY SL (Proc. 1497/2025)
   Plazo: 10 dias habiles desde notificacion
   Accion: Presentar escrito de alegaciones frente a acumulacion

2. [27/03/2026] Recurso reposicion - Jimenez Vitoria, Alicia (Proc. 953/2025)
   Plazo: 5 dias habiles
   Accion: Valorar recurso de reposicion frente a diligencia de ordenacion

Indique los numeros que desea agendar (ej: "1, 2" o "todas" o "ninguna"):
```

---

### Paso 4: Agendar en Google Calendar

Tras la confirmacion del usuario, agendar los eventos seleccionados.

**Si el LLM tiene acceso a Google Calendar API:**

Crear un evento por cada plazo confirmado con estos parametros:

| Parametro | Valor |
|:---|:---|
| Titulo | `JUDICIAL: Vto. {tipo_plazo} - {PARTE} {PROC}` |
| Fecha | Dia de vencimiento del plazo |
| Hora | 08:00 |
| Duracion | 30 minutos |
| Recordatorios | 24 horas antes y 2 horas antes |
| Descripcion | Documento, resumen, tipo resolucion, accion requerida |

**Si el LLM NO tiene acceso a Calendar:**

Presentar los eventos en formato copiable para que el usuario los agende manualmente:

```
EVENTOS PARA AGENDAR MANUALMENTE:

Fecha: 03/04/2026 a las 08:00
Titulo: JUDICIAL: Vto. Requerimiento alegaciones - THE LAST ONE COMPANY SL 1497/2025
Descripcion: Presentar escrito de alegaciones frente a acumulacion
Recordatorios: 24h y 2h antes
```

---

### Paso 5: Gestionar archivos sin mapeo

Si hay PDFs que no pudieron clasificarse en ninguna carpeta de Usu2:

1. Mostrar la lista al usuario con nombre de archivo, procedimiento y asunto del correo.
2. Preguntar a que cliente corresponde cada uno.
3. Actualizar el archivo `mapeos\mapeo_expedientes.json` anadiendo la nueva entrada.

Formato del mapeo:

```json
{
  "por_procedimiento": {
    "999/2026": "Nombre del Cliente"
  },
  "por_asunto_regex": {
    "(?i)patron\\s+busqueda": "Nombre del Cliente"
  }
}
```

---

## Mapeo de expedientes conocidos (actualizado 21/03/2026)

### Por numero de procedimiento

| Procedimiento | Cliente (carpeta Usu2) |
|:---|:---|
| 277/2023 | Vinagres Alaveses, S.L |
| 253/2021 | Lazaro Vallejo, Beatriz |
| 197/2017 | Lazaro Vallejo, Beatriz |
| 1210/2025 | Jimenez Vitoria, Alicia |
| 366/2025 | Blanco Sanchez, Angel |
| 56/2024 | Casero Miguel, Oscar |
| 628/2019 | Calahorra Zapatero, Luis Javier |
| 135/2021 | Jimenez Vitoria, Alicia |
| 1497/2025 | The Last One Company, SL |
| 458/2025 | Frutas Pison SL |
| 1147/2026 | Frutas Pison SL |
| 651/2023 | Avenida de Colon 3 Decoracion, SL |
| 953/2025 | Jimenez Vitoria, Alicia |
| 50/2026 | Jimenez Vitoria, Alicia |
| 1601/2025 | Jimenez Vitoria, Alicia |
| 990/2025 | Jimenez Vitoria, Alicia |
| 252/2025 | Jimenez Vitoria, Alicia |
| 120/2026 | Latorre Galilea, Julio |

### Por patron en asunto del correo

| Patron | Cliente |
|:---|:---|
| vinagres alaveses | Vinagres Alaveses, S.L |
| lazaro vallejo | Lazaro Vallejo, Beatriz |
| jimenez vitoria | Jimenez Vitoria, Alicia |
| blanco sanchez | Blanco Sanchez, Angel |
| casero miguel | Casero Miguel, Oscar |
| calahorra zapatero | Calahorra Zapatero, Luis Javier |
| the last one | The Last One Company, SL |
| frutas pison | Frutas Pison SL |
| colon 3 decoracion | Avenida de Colon 3 Decoracion, SL |
| garcia ruiz fidel | Garcia Ruiz, Fidel Pedro |
| julio antolin | Latorre Galilea, Julio |
| latorre galilea | Latorre Galilea, Julio |

---

## Automatizacion diaria en Windows

### Opcion A: Programador de Tareas de Windows

Para que el pipeline base (descarga + clasificacion) se ejecute automaticamente sin intervencion:

```cmd
schtasks /create /tn "Pipeline Judicial ASERGES Manana" /tr "\"C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631\pipeline-judicial-aserges\ejecutar_pipeline.bat\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:00 /f

schtasks /create /tn "Pipeline Judicial ASERGES Tarde" /tr "\"C:\Users\santi\OneDrive - Aserges\DOCS-MNPROGRAM_1631\pipeline-judicial-aserges\ejecutar_pipeline.bat\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:00 /f
```

Esto ejecuta la descarga y clasificacion automaticamente. El analisis IA requiere que un LLM de escritorio lo invoque manualmente o que Manus lo ejecute desde la nube.

### Opcion B: Manus (nube, ya configurado)

Manus ejecuta el pipeline completo (incluido analisis IA, correo e interaccion Calendar) cada 12 horas de lunes a viernes. No requiere que el PC este encendido para el analisis y el correo, pero si para la copia de archivos a Notificaciones/Usu2.

### Opcion C: LLM de escritorio bajo demanda

Abrir el LLM de escritorio y solicitar:

> "Ejecuta el pipeline judicial diario siguiendo el skill en C:\...\pipeline-judicial-aserges\skill-llm-escritorio\SKILL.md"

---

## Solucion de problemas

| Problema | Causa probable | Solucion |
|:---|:---|:---|
| Error de conexion IMAP | Credenciales incorrectas o servidor caido | Verificar config.json, probar con otro cliente de correo |
| pdfplumber no instalado | Falta dependencia | `pip install pdfplumber` |
| openai no instalado | Falta dependencia | `pip install openai` |
| OPENAI_API_KEY no configurada | Variable de entorno ausente | `set OPENAI_API_KEY=sk-...` o `setx` para permanente |
| PDF sin texto extraible | PDF escaneado sin OCR | El analisis IA lo marca como "PDF sin texto extraible" |
| Carpeta Usu2 no encontrada | Ruta incorrecta en config.json | Verificar que la ruta existe y es accesible |
| PDF sin mapeo a cliente | Expediente nuevo no registrado | Anadir en mapeo_expedientes.json |
| Plazo calculado incorrecto | Festivo local no incluido | Revisar funcion obtener_festivos() en analisis_ia_calendar.py |
| Correo no enviado | Sin acceso a Gmail API | Usar Manus (nube) para el envio automatico |

---

## Notas importantes

- **Autor de informes**: Siempre "Asesores y Abogados ASerges SL". Nunca mencionar el nombre del LLM o herramienta de IA.
- **Correo de resultados**: santi.palacios.pinillos@gmail.com
- **Plazos procesales**: Conforme a LEC (arts. 130-131) y LOPJ (arts. 182-183). Dias habiles, excluyendo sabados, domingos, festivos y agosto.
- **Agosto inhabil**: Todo el mes de agosto es inhabil (art. 183.1 LOPJ).
- **Semana Santa**: Jueves y Viernes Santo son inhabiles (calculo automatico por algoritmo de Butcher).
- **Hora de agendacion**: Siempre a las 08:00 del dia de vencimiento.
- **Recordatorios Calendar**: 24 horas y 2 horas antes del evento.
