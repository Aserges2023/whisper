# Pipeline Judicial Diario - ASERGES

Automatización de la gestión de notificaciones judiciales recibidas por correo de procuradores.

> **Estado (2026-04-27):** Implementada la Opción A de autenticación (Service Account Impersonation / ADC).
> El pipeline ya no depende de tokens OAuth de usuario (que caducan cada 7 días en modo Testing).
> Ver sección **Configuración ADC** más abajo.

## Estructura

```
pipeline-judicial-aserges/
├── ejecutar_pipeline.bat           # Lanzador principal (doble clic)
├── instalar.bat                    # Instalación de dependencias
├── configurar_adc_windows.bat      # Configuración ADC (ejecutar una vez)
├── README.md
├── config/
│   ├── config.json                 # Configuración (IMAP, rutas, procuradores)
│   └── .env.example                # Variables de entorno (copiar a .env)
├── mapeos/
│   └── mapeo_expedientes.json      # Mapeo procedimiento -> carpeta cliente
├── skill-manus/
│   └── SKILL.md                    # Skill operativo para Manus Cowork
└── scripts/
    ├── pipeline_judicial.py        # Fases 1-4: IMAP, clasificación, Notificaciones, Usu2
    ├── analisis_ia_calendar.py     # Fase 5: Análisis IA + agendamiento Calendar (MCP o ADC)
    └── auth_adc.py                 # Módulo de autenticación ADC (Service Account Impersonation)
```

## Uso

### Ejecución diaria (correos de hoy)
```
ejecutar_pipeline.bat
```

### Rango de fechas personalizado
```
ejecutar_pipeline.bat --desde 2026-03-16
ejecutar_pipeline.bat --desde 2026-03-16 --hasta 2026-03-21
```

### Análisis IA con agendamiento (modo MCP, requiere Manus Cowork)
```
python scripts\analisis_ia_calendar.py --dir Notificaciones\{fecha}
```

### Análisis IA con agendamiento (modo ADC, autónomo)
```
python scripts\analisis_ia_calendar.py --dir Notificaciones\{fecha} --modo-auth adc
```

## Qué hace el pipeline

1. **Descarga** correos con PDFs adjuntos de procuradores autorizados (IMAP)
2. **Clasifica** cada PDF extrayendo metadatos judiciales (procedimiento, tipo, partes, plazos)
3. **Renombra** con formato descriptivo: `HHhMM - PARTE - PROCEDIMIENTO - TIPO.pdf`
4. **Copia a Notificaciones** organizado por fecha
5. **Clasifica en Usu2** copiando a la subcarpeta del cliente correspondiente
6. **Analiza con IA** (GPT-4.1-mini): resumen, prioridad ALTA/MEDIA/BAJA, plazos LEC
7. **Agenda en Calendar** los plazos relevantes (modo MCP o ADC)
8. **Genera informe** con resumen, documentos mapeados y pendientes

## Configuración ADC (Service Account Impersonation)

El modo ADC permite que el pipeline agende eventos en Google Calendar **sin depender de Manus Cowork** y sin tokens OAuth que caducan cada 7 días.

### Pasos (una sola vez por equipo)

1. **Instalar Google Cloud CLI:** https://cloud.google.com/sdk/docs/install

2. **Asignar rol en GCP** (pedir al admin):
   - Rol: `roles/iam.serviceAccountTokenCreator`
   - Sobre la SA: `pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com`
   - Para el usuario: `santiago@aserges.es`

3. **Ejecutar el script de configuración:**
   ```
   configurar_adc_windows.bat
   ```

4. **Activar modo ADC de forma permanente:**
   ```
   setx PIPELINE_AUTH_MODE adc
   ```

### Verificar configuración

```
python scripts\auth_adc.py
```

Salida esperada:
```
✓ Archivo ADC encontrado en disco
✓ Google Calendar API: OK (N calendarios accesibles)
✓ Gmail API: OK (cuenta: santiago@aserges.es)
```

## Configuración general

Editar `config/config.json` para modificar:
- Credenciales IMAP
- Procuradores autorizados
- Rutas de carpetas Windows

Editar `mapeos/mapeo_expedientes.json` para añadir nuevos expedientes.

Copiar `config/.env.example` a `config/.env` y rellenar las variables necesarias.

## Solución de problemas

| Error | Causa | Solución |
|:---|:---|:---|
| `invalid_grant` | Tokens OAuth caducados (7 días, modo Testing) | Migrar a modo ADC con `configurar_adc_windows.bat` |
| `ADC no configurado` | Falta archivo ADC en disco | Ejecutar `configurar_adc_windows.bat` |
| `Error IMAP` | Credenciales incorrectas | Verificar `config/config.json` |
| `PDF sin mapeo` | Expediente no registrado | Añadir en `mapeos/mapeo_expedientes.json` |
