#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_adc.py — Autenticación Google vía Application Default Credentials (ADC)
con Service Account Impersonation.

Opción A del plan de migración (2026-04-27):
  - No descarga claves JSON de SA (compatible con org policy iam.disableServiceAccountKeyCreation)
  - Usa `gcloud auth application-default login --impersonate-service-account=SA_EMAIL`
    para generar credenciales efímeras locales (~/.config/gcloud/application_default_credentials.json)
  - El módulo detecta automáticamente si ADC está disponible; si no, lanza instrucciones claras.

Uso:
    from auth_adc import get_calendar_service, get_gmail_service, adc_disponible

Requisitos previos (Windows, una sola vez):
    1. Instalar Google Cloud CLI: https://cloud.google.com/sdk/docs/install
    2. Ejecutar configurar_adc_windows.bat (o el comando manual de abajo)
    3. Conceder rol roles/iam.serviceAccountTokenCreator al usuario sobre la SA

Comando manual:
    gcloud auth application-default login \
        --impersonate-service-account=pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com \
        --scopes=https://www.googleapis.com/auth/calendar.events,https://www.googleapis.com/auth/gmail.send
"""

import os
import sys
import logging
from pathlib import Path

log = logging.getLogger("auth_adc")

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────
SA_EMAIL = os.environ.get(
    "PIPELINE_SA_EMAIL",
    "pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com"
)

SCOPES_CALENDAR = ["https://www.googleapis.com/auth/calendar.events"]
SCOPES_GMAIL    = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Ruta del archivo ADC generado por gcloud (Windows y Linux/Mac)
_ADC_PATHS = [
    Path(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json"),
    Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
]


# ─────────────────────────────────────────────────────────────────────────────
# Detección de ADC
# ─────────────────────────────────────────────────────────────────────────────
def adc_disponible() -> bool:
    """Devuelve True si existe un archivo ADC generado por gcloud."""
    for p in _ADC_PATHS:
        if p.exists():
            return True
    # También puede estar definido por variable de entorno GOOGLE_APPLICATION_CREDENTIALS
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    return bool(env_path and Path(env_path).exists())


def _instrucciones_adc() -> str:
    return (
        "\n"
        "╔══════════════════════════════════════════════════════════════════════╗\n"
        "║  CONFIGURACIÓN ADC REQUERIDA                                        ║\n"
        "╠══════════════════════════════════════════════════════════════════════╣\n"
        "║  No se encontraron credenciales ADC de Google en este equipo.       ║\n"
        "║                                                                      ║\n"
        "║  Ejecuta UNA VEZ en Windows (PowerShell o CMD):                     ║\n"
        "║                                                                      ║\n"
        "║  configurar_adc_windows.bat                                          ║\n"
        "║                                                                      ║\n"
        "║  O manualmente:                                                      ║\n"
        f"║  gcloud auth application-default login \\                            ║\n"
        f"║    --impersonate-service-account={SA_EMAIL[:38]}  ║\n"
        "║    --scopes=https://www.googleapis.com/auth/calendar.events,\\       ║\n"
        "║             https://www.googleapis.com/auth/gmail.send              ║\n"
        "╚══════════════════════════════════════════════════════════════════════╝\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Obtención de credenciales
# ─────────────────────────────────────────────────────────────────────────────
def _get_credentials(scopes: list):
    """
    Obtiene credenciales ADC con los scopes indicados.
    Lanza RuntimeError con instrucciones si ADC no está configurado.
    """
    if not adc_disponible():
        raise RuntimeError(_instrucciones_adc())

    try:
        import google.auth
        credentials, project = google.auth.default(scopes=scopes)
        log.info(f"ADC cargado correctamente (proyecto: {project})")
        return credentials
    except ImportError:
        raise RuntimeError(
            "Librería google-auth no instalada. Ejecuta:\n"
            "  pip install google-auth google-auth-httplib2 google-api-python-client"
        )
    except Exception as e:
        raise RuntimeError(
            f"Error al cargar credenciales ADC: {e}\n"
            f"{_instrucciones_adc()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Clientes de API
# ─────────────────────────────────────────────────────────────────────────────
def get_calendar_service():
    """
    Devuelve un cliente autenticado de Google Calendar API v3 usando ADC.

    Returns:
        googleapiclient.discovery.Resource: Servicio Calendar listo para usar.

    Raises:
        RuntimeError: Si ADC no está configurado o las credenciales son inválidas.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Librería google-api-python-client no instalada. Ejecuta:\n"
            "  pip install google-api-python-client"
        )
    credentials = _get_credentials(SCOPES_CALENDAR)
    service = build("calendar", "v3", credentials=credentials)
    log.info("Cliente Google Calendar v3 inicializado (ADC/impersonation)")
    return service


def get_gmail_service():
    """
    Devuelve un cliente autenticado de Gmail API v1 usando ADC.

    Returns:
        googleapiclient.discovery.Resource: Servicio Gmail listo para usar.

    Raises:
        RuntimeError: Si ADC no está configurado o las credenciales son inválidas.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "Librería google-api-python-client no instalada. Ejecuta:\n"
            "  pip install google-api-python-client"
        )
    credentials = _get_credentials(SCOPES_GMAIL)
    service = build("gmail", "v1", credentials=credentials)
    log.info("Cliente Gmail API v1 inicializado (ADC/impersonation)")
    return service


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de Calendar
# ─────────────────────────────────────────────────────────────────────────────
def crear_evento_calendar(
    summary: str,
    description: str,
    start_date: str,
    calendar_id: str = "primary",
    recordatorios_min: list = None,
) -> dict | None:
    """
    Crea un evento en Google Calendar usando ADC.

    Args:
        summary: Título del evento.
        description: Descripción detallada.
        start_date: Fecha en formato YYYY-MM-DD.
        calendar_id: ID del calendario (por defecto 'primary').
        recordatorios_min: Lista de minutos de antelación para recordatorios.
                           Por defecto [1440, 120] (24h y 2h).

    Returns:
        dict con el evento creado, o None si falla.
    """
    if recordatorios_min is None:
        recordatorios_min = [1440, 120]

    service = get_calendar_service()

    # Deduplicación: buscar evento con el mismo título en la misma fecha
    try:
        existing = service.events().list(
            calendarId=calendar_id,
            timeMin=f"{start_date}T00:00:00+01:00",
            timeMax=f"{start_date}T23:59:59+01:00",
            q=summary,
            singleEvents=True,
        ).execute()
        for ev in existing.get("items", []):
            if ev.get("summary") == summary:
                log.info(f"Evento ya existe, omitiendo duplicado: {summary}")
                return ev
    except Exception as e:
        log.warning(f"No se pudo verificar duplicados: {e}")

    evento = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": f"{start_date}T08:00:00+01:00", "timeZone": "Europe/Madrid"},
        "end":   {"dateTime": f"{start_date}T08:30:00+01:00", "timeZone": "Europe/Madrid"},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m} for m in recordatorios_min
            ],
        },
    }

    try:
        result = service.events().insert(calendarId=calendar_id, body=evento).execute()
        log.info(f"Evento creado: {summary} -> {start_date} (id: {result.get('id')})")
        return result
    except Exception as e:
        log.error(f"Error creando evento '{summary}': {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI de diagnóstico
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("  VERIFICACIÓN ADC - Pipeline Judicial ASERGES")
    print("=" * 60)

    if not adc_disponible():
        print(_instrucciones_adc())
        sys.exit(1)

    print("✓ Archivo ADC encontrado en disco")

    # Intentar cargar credenciales de Calendar
    try:
        svc = get_calendar_service()
        # Listar calendarios para confirmar acceso
        result = svc.calendarList().list(maxResults=3).execute()
        cals = result.get("items", [])
        print(f"✓ Google Calendar API: OK ({len(cals)} calendarios accesibles)")
        for c in cals:
            print(f"    - {c.get('summary', 'sin nombre')} ({c.get('id', '')})")
    except Exception as e:
        print(f"✗ Google Calendar API: ERROR\n  {e}")
        sys.exit(1)

    # Intentar cargar credenciales de Gmail
    try:
        svc_gmail = get_gmail_service()
        profile = svc_gmail.users().getProfile(userId="me").execute()
        print(f"✓ Gmail API: OK (cuenta: {profile.get('emailAddress', 'desconocida')})")
    except Exception as e:
        print(f"✗ Gmail API: ERROR\n  {e}")
        sys.exit(1)

    print("=" * 60)
    print("  ADC configurado correctamente. El pipeline puede ejecutarse.")
    print("=" * 60)
