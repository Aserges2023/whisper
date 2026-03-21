# Flujo de lectura de respuesta Gmail y agendación

## Contexto

Tras enviar el informe con propuestas de agendación, el usuario responde al correo indicando qué números agendar. Este documento describe la lógica para parsear la respuesta y agendar.

## Paso 1: Buscar respuesta

```bash
manus-mcp-cli tool call gmail_search_messages --server gmail --input '{"q":"subject:ASERGES Informe Judicial in:inbox is:unread","max_results":10}'
```

Buscar mensajes que sean respuestas al informe enviado (mismo thread).

## Paso 2: Leer el thread completo

```bash
manus-mcp-cli tool call gmail_read_threads --server gmail --input '{"thread_ids":["THREAD_ID"],"include_full_messages":true}'
```

## Paso 3: Parsear la respuesta

Buscar en el cuerpo del mensaje del usuario patrones como:
- "Agendar 1, 3, 10" -> extraer números [1, 3, 10]
- "Agendar todas" -> agendar todas las propuestas
- "Ninguna" o "No agendar" -> no agendar nada
- "Agendar la 9 y la 10" -> extraer [9, 10]
- Números sueltos separados por comas, "y", espacios

Regex sugerido: `r'(\d+)'` sobre el texto de respuesta, filtrando por rango válido.

## Paso 4: Cruzar con el JSON de análisis

Cargar `analisis_ia_resultados/analisis_ia_{fecha}.json`. Los números del correo corresponden al orden de las propuestas enviadas. Filtrar solo los que tienen `agendado: true` y `evento_calendar`.

## Paso 5: Agendar cada evento confirmado

Para cada número confirmado:

```bash
manus-mcp-cli tool call google_calendar_create_events --server google-calendar --input '{"events":[{"summary":"JUDICIAL: Vto. {tipo} - {parte} {proc}","description":"...","start_time":"{fecha}T08:00:00+01:00","end_time":"{fecha}T08:30:00+01:00","reminders":[1440,120]}]}'
```

## Paso 6: Confirmar por correo

Enviar correo de confirmación:

```bash
manus-mcp-cli tool call gmail_send_messages --server gmail --input '{"messages":[{"subject":"ASERGES - Confirmación agendación {fecha}","to":["santi.palacios.pinillos@gmail.com"],"content":"Se han agendado los siguientes eventos en Google Calendar:\n\n1. [FECHA] EVENTO\n2. [FECHA] EVENTO\n\n--\nAsesores y Abogados ASerges SL"}]}'
```
