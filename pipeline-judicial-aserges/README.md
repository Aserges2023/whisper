# Pipeline Judicial Diario - ASERGES

Automatización de la gestión de notificaciones judiciales recibidas por correo de procuradores.

## Estructura

```
pipeline-judicial-aserges/
├── ejecutar_pipeline.bat      # Lanzador principal (doble clic)
├── instalar.bat               # Instalación de dependencias
├── README.md
├── config/
│   └── config.json            # Configuración (IMAP, rutas, procuradores)
├── mapeos/
│   └── mapeo_expedientes.json # Mapeo procedimiento -> carpeta cliente
└── scripts/
    └── pipeline_judicial.py   # Script principal Python
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

## Qué hace el pipeline

1. **Descarga** correos con PDFs adjuntos de procuradores autorizados
2. **Clasifica** cada PDF extrayendo metadatos judiciales (procedimiento, tipo, partes, plazos)
3. **Renombra** con formato descriptivo: `HHhMM - PARTE - PROCEDIMIENTO - TIPO.pdf`
4. **Copia a Notificaciones** organizado por fecha
5. **Clasifica en Usu2** copiando a la subcarpeta del cliente correspondiente
6. **Genera informe** con resumen, documentos mapeados y pendientes

## Configuración

Editar `config/config.json` para modificar:
- Credenciales IMAP
- Procuradores autorizados
- Rutas de carpetas Windows

Editar `mapeos/mapeo_expedientes.json` para añadir nuevos expedientes.
