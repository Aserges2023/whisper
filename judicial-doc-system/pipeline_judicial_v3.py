# -*- coding: utf-8 -*-
"""
pipeline_judicial_v3.py
=======================
Pipeline autónomo de procesamiento de notificaciones judiciales.
Despacho ASERGES S.L. — Logroño, España.

MEJORAS v3 respecto a v2:
  [1] SEGURIDAD:    Credenciales en ~/.env.judicial (python-dotenv). Sin hardcoding.
  [2] LLM:          Reintentos exponenciales (tenacity) + cola de pendientes de clasificar.
  [3] OCR:          Tesseract OCR para PDFs escaneados (fallback automático).
  [4] CALENDARIO:   Generación de archivos .ics adjuntos en el correo de aviso.
  [5] ONEDRIVE:     Autenticación App-Only via Microsoft Graph API (MSAL).

Autor: Pipeline Judicial Automático — Asesores y Abogados ASerges SL
"""

import os
import re
import sys
import json
import email
import imaplib
import hashlib
import logging
import smtplib
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# --- Dependencias externas ---
import pdfplumber
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

# =============================================================================
# CARGA DE CONFIGURACIÓN DESDE .env.judicial
# =============================================================================
ENV_FILE = os.path.expanduser("~/.env.judicial")
load_dotenv(ENV_FILE)

IMAP_HOST = os.getenv("IMAP_HOST", "imap.ionos.es")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASS = os.getenv("IMAP_PASS", "")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.ionos.es")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

PROCURADORES_DOMINIOS = [d.strip() for d in os.getenv("PROCURADORES_DOMINIOS", "").split(",") if d.strip()]
PROCURADORES_EMAILS   = [e.strip() for e in os.getenv("PROCURADORES_EMAILS", "").split(",") if e.strip()]

# OneDrive / SharePoint — Graph API App-Only
AZURE_TENANT_ID     = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID     = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_CERT_PATH     = os.getenv("AZURE_CERT_PATH", "")
AZURE_CERT_PASSWORD = os.getenv("AZURE_CERT_PASSWORD", "")
SP_BASE_URL         = os.getenv("SP_BASE_URL", "https://aserges2023-my.sharepoint.com")
SP_SITE_PATH        = os.getenv("SP_SITE_PATH", "/personal/santiago_palacios_aserges_es")
ONEDRIVE_NOTIF_FOLDER = os.getenv("ONEDRIVE_NOTIF_FOLDER", "DOCS-MNPROGRAM_1631/Notificaciones")

# Google Calendar
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_CALENDAR_ID          = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# Rutas locales
LOCAL_NOTIF_BASE      = os.getenv("LOCAL_NOTIF_BASE", "/home/ubuntu/Notificaciones")
LOG_FILE              = os.getenv("LOG_FILE", "/home/ubuntu/pipeline_judicial_v3.log")
LAST_RUN_FILE         = os.getenv("LAST_RUN_FILE", "/home/ubuntu/.pipeline_last_run.json")
GCAL_PENDING_FILE     = os.getenv("GCAL_PENDING_FILE", "/home/ubuntu/.pipeline_gcal_pendientes.json")
HASH_DB_FILE          = os.getenv("HASH_DB_FILE", "/home/ubuntu/.pipeline_hashes.json")
PENDING_CLASSIFY_FILE = os.getenv("PENDING_CLASSIFY_FILE", "/home/ubuntu/.pipeline_pendientes_clasificar.json")

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("pipeline_judicial_v3")

# =============================================================================
# UTILIDADES GENERALES
# =============================================================================

def cargar_last_run():
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                return json.load(f).get("last_run")
        except Exception:
            pass
    return None

def guardar_last_run():
    with open(LAST_RUN_FILE, "w") as f:
        json.dump({"last_run": datetime.now().isoformat()}, f)

def cargar_hashes():
    if os.path.exists(HASH_DB_FILE):
        try:
            with open(HASH_DB_FILE) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def guardar_hashes(hashes):
    with open(HASH_DB_FILE, "w") as f:
        json.dump(list(hashes), f)

def calcular_hash(data):
    return hashlib.sha256(data).hexdigest()

def sanitizar_nombre(nombre):
    if not nombre:
        return "desconocido"
    nombre = unicodedata.normalize("NFKD", nombre)
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nombre)
    nombre = nombre.strip('. ')
    return nombre[:100] if nombre else "desconocido"

# =============================================================================
# [3] OCR: EXTRACCIÓN DE TEXTO CON FALLBACK A TESSERACT
# =============================================================================

def extraer_texto_pdf(pdf_bytes):
    """
    Extrae texto de un PDF.
    1. Intenta pdfplumber (PDFs nativos/digitales).
    2. Si el resultado es vacío o muy corto (<100 chars), aplica Tesseract OCR.
    """
    texto = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages[:10]:
                t = pagina.extract_text()
                if t:
                    texto += t + "\n"
    except Exception as e:
        logger.warning("pdfplumber error: %s", e)

    if len(texto.strip()) >= 100:
        logger.info("Texto extraído con pdfplumber: %d caracteres", len(texto))
        return texto

    # Fallback: Tesseract OCR
    logger.info("Texto insuficiente con pdfplumber (%d chars). Aplicando Tesseract OCR...", len(texto.strip()))
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        imagenes = convert_from_bytes(pdf_bytes, dpi=300)
        texto_ocr = ""
        for i, img in enumerate(imagenes[:10]):
            t = pytesseract.image_to_string(img, lang="spa")
            texto_ocr += t + "\n"
            logger.info("  OCR página %d: %d caracteres", i + 1, len(t))
        texto = texto_ocr
        logger.info("Texto extraído con Tesseract OCR: %d caracteres", len(texto))
    except Exception as e:
        logger.error("Tesseract OCR error: %s", e)

    return texto

# =============================================================================
# EXTRACCIÓN DE METADATOS JUDICIALES (regex)
# =============================================================================

REGEX_NIG = [
    r"N\.?I\.?G\.?\s*[:\-]?\s*(\d{4}[\./]\d{4,}[\./\-]\d+[\./\-]?\d*[\./\-]?\d*)",
    r"N\.?I\.?G\.?\s*[:\-]?\s*(\d{2}\.\d{2}\.\d[\-/]\d{4}/\d{4}\.\d{2}\.\d{4})",
    r"NIG\s*[:\-]?\s*(\S+\d{4}/\d{4}\S*)",
]
REGEX_PROCEDIMIENTO = [
    r"(?:Procedimiento|Autos|Rollo|Ejecut(?:oria|ivo)|Concurso|Pieza)\s*(?:n[ºo°]?\.?\s*)?[:\-]?\s*(\d{1,5}[/\-]\d{2,4})",
    r"(?:Proc\.|Proced\.)\s*[:\-]?\s*(\d{1,5}[/\-]\d{2,4})",
    r"(\d{1,5}/\d{2,4})\s*(?:del?\s+)?(?:Juzgado|Audiencia|Tribunal|Sala)",
]
REGEX_TIPO_RESOLUCION = [
    r"(AUTO|SENTENCIA|DECRETO|PROVIDENCIA|DILIGENCIA\s+DE\s+ORDENACI[OÓ]N|NOTIFICACI[OÓ]N|EMPLAZAMIENTO|REQUERIMIENTO|CITACI[OÓ]N|OFICIO|EXHORTO|MANDAMIENTO)",
    r"(?i)(auto|sentencia|decreto|providencia|diligencia\s+de\s+ordenaci[oó]n|notificaci[oó]n|emplazamiento|requerimiento|citaci[oó]n|oficio|exhorto|mandamiento)",
]
REGEX_PARTES = [
    r"(?:Demandante|Actor|Solicitante|Concursado|Deudor)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,\.]+?)(?:\n|$|\.)",
    r"(?:Demandado|Ejecutado|Parte contraria)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,\.]+?)(?:\n|$|\.)",
]
REGEX_FECHAS_JUDICIALES = [
    r"(?:vista|juicio|lanzamiento|comparecencia|audiencia)\s+(?:oral\s+)?(?:prevista?\s+)?(?:para\s+)?(?:el\s+)?(?:d[ií]a\s+)?(\d{1,2}[\s/\-\.]+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{1,2})[\s/\-\.]+(?:de\s+)?\d{2,4})",
    r"(?:señal[aá]ndose|se\s+señala)\s+(?:para\s+)?(?:el\s+)?(?:d[ií]a\s+)?(\d{1,2}[\s/\-\.]+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{1,2})[\s/\-\.]+(?:de\s+)?\d{2,4})",
]
REGEX_PLAZOS = [
    r"(?:plazo\s+de\s+)(\d+)\s+d[ií]as?\s+(?:h[aá]biles|naturales)?",
    r"(?:en\s+el\s+plazo\s+de\s+)(\d+)\s+d[ií]as?",
    r"(?:dentro\s+de(?:l\s+plazo\s+de)?\s+)(\d+)\s+d[ií]as?",
]

def extraer_metadatos_regex(texto):
    metadatos = {"nig": None, "num_procedimiento": None, "tipo_resolucion": None,
                 "partes": [], "fechas_judiciales": [], "plazos_dias": []}
    for patron in REGEX_NIG:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            metadatos["nig"] = m.group(1).strip(); break
    for patron in REGEX_PROCEDIMIENTO:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            metadatos["num_procedimiento"] = m.group(1).strip(); break
    for patron in REGEX_TIPO_RESOLUCION:
        m = re.search(patron, texto)
        if m:
            metadatos["tipo_resolucion"] = m.group(1).strip().upper(); break
    for patron in REGEX_PARTES:
        for m in re.findall(patron, texto):
            nombre = m.strip()
            if len(nombre) > 3 and nombre not in metadatos["partes"]:
                metadatos["partes"].append(nombre)
    for patron in REGEX_FECHAS_JUDICIALES:
        for m in re.findall(patron, texto, re.IGNORECASE):
            metadatos["fechas_judiciales"].append(m.strip())
    for patron in REGEX_PLAZOS:
        for m in re.findall(patron, texto, re.IGNORECASE):
            try:
                metadatos["plazos_dias"].append(int(m))
            except ValueError:
                pass
    return metadatos

# =============================================================================
# [2] LLM CON REINTENTOS EXPONENCIALES + COLA DE PENDIENTES
# =============================================================================

class LLMError(Exception):
    pass

@retry(
    retry=retry_if_exception_type(LLMError),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,
)
def _llamar_llm(prompt):
    """Llama a la API del LLM con reintentos exponenciales."""
    from openai import OpenAI, APIError, APIConnectionError, RateLimitError
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        return response.choices[0].message.content.strip()
    except (APIError, APIConnectionError, RateLimitError) as e:
        raise LLMError(f"Error API LLM: {e}") from e
    except Exception as e:
        raise LLMError(f"Error inesperado LLM: {e}") from e


def clasificar_con_llm(texto_pdf, asunto_correo, remitente):
    """Clasifica el documento con LLM. Si falla definitivamente, retorna None."""
    prompt = f"""Eres un asistente jurídico especializado en notificaciones judiciales españolas.
Analiza el siguiente documento judicial y proporciona:

1. nombre_descriptivo: Un nombre corto y descriptivo para el archivo (ej: "Auto tasación de costas", "Diligencia requerimiento datos", "Sentencia estimatoria", "Decreto admisión demanda"). Máximo 6 palabras.
2. tipo_resolucion: El tipo exacto de resolución (AUTO, SENTENCIA, DECRETO, PROVIDENCIA, DILIGENCIA DE ORDENACIÓN, NOTIFICACIÓN, EMPLAZAMIENTO, REQUERIMIENTO, CITACIÓN, OFICIO, EXHORTO, MANDAMIENTO, u OTRO).
3. plazos_procesales: Lista de plazos procesales detectados. Para cada plazo indica: descripcion, dias (si se mencionan), fecha_limite (formato DD/MM/YYYY si se puede calcular), tipo (RECURSO, REQUERIMIENTO, VISTA, JUICIO, LANZAMIENTO, OTRO).
4. resumen_breve: Resumen de 1-2 frases del contenido del documento.
5. urgente: true/false - si contiene plazos que vencen en menos de 10 días o fechas de vista/juicio próximas.

Asunto del correo: {asunto_correo}
Remitente: {remitente}

Texto del documento (primeros 3000 caracteres):
{texto_pdf[:3000]}

Responde SOLO en formato JSON válido, sin markdown ni explicaciones adicionales."""

    try:
        respuesta = _llamar_llm(prompt)
        # Limpiar posibles bloques de código markdown
        respuesta = re.sub(r"```(?:json)?", "", respuesta).strip()
        clasificacion = json.loads(respuesta)
        logger.info("Clasificación LLM exitosa: %s", clasificacion.get("nombre_descriptivo", "N/A"))
        return clasificacion
    except Exception as e:
        logger.error("Clasificación LLM fallida definitivamente: %s", e)
        return None


def cargar_pendientes_clasificar():
    if os.path.exists(PENDING_CLASSIFY_FILE):
        try:
            with open(PENDING_CLASSIFY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def guardar_pendientes_clasificar(pendientes):
    with open(PENDING_CLASSIFY_FILE, "w") as f:
        json.dump(pendientes, f, ensure_ascii=False, indent=2)

def agregar_pendiente_clasificar(nombre_original, ruta_local, asunto, remitente, sha256):
    pendientes = cargar_pendientes_clasificar()
    # Evitar duplicados
    if not any(p.get("sha256") == sha256 for p in pendientes):
        pendientes.append({
            "nombre_original": nombre_original,
            "ruta_local": ruta_local,
            "asunto": asunto,
            "remitente": remitente,
            "sha256": sha256,
            "fecha_pendiente": datetime.now().isoformat(),
        })
        guardar_pendientes_clasificar(pendientes)
        logger.warning("Documento añadido a cola de pendientes: %s", nombre_original)

def procesar_cola_pendientes():
    """Intenta clasificar los documentos que fallaron en ejecuciones anteriores."""
    pendientes = cargar_pendientes_clasificar()
    if not pendientes:
        return []
    logger.info("Procesando cola de pendientes: %d documentos", len(pendientes))
    clasificados = []
    for p in pendientes[:]:
        ruta = p.get("ruta_local")
        if not ruta or not os.path.exists(ruta):
            pendientes.remove(p)
            continue
        with open(ruta, "rb") as f:
            pdf_bytes = f.read()
        texto = extraer_texto_pdf(pdf_bytes)
        clasificacion = clasificar_con_llm(texto, p.get("asunto", ""), p.get("remitente", ""))
        if clasificacion:
            clasificados.append({**p, "clasificacion": clasificacion})
            pendientes.remove(p)
            logger.info("Pendiente clasificado: %s", p.get("nombre_original"))
    guardar_pendientes_clasificar(pendientes)
    return clasificados

# =============================================================================
# [5] ONEDRIVE: MICROSOFT GRAPH API APP-ONLY (MSAL)
# =============================================================================

_graph_token_cache = {"token": None, "expires_at": None}

def obtener_token_graph():
    """Obtiene un token de acceso para Microsoft Graph API usando App-Only (MSAL)."""
    ahora = datetime.now()
    if _graph_token_cache["token"] and _graph_token_cache["expires_at"] and ahora < _graph_token_cache["expires_at"]:
        return _graph_token_cache["token"]

    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        logger.warning("Credenciales Azure no configuradas. OneDrive deshabilitado.")
        return None

    try:
        import msal

        authority = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
        scopes = ["https://graph.microsoft.com/.default"]

        if AZURE_CERT_PATH and os.path.exists(AZURE_CERT_PATH):
            # Autenticación con certificado (más segura)
            with open(AZURE_CERT_PATH, "rb") as f:
                cert_data = f.read()
            app = msal.ConfidentialClientApplication(
                AZURE_CLIENT_ID,
                authority=authority,
                client_credential={"private_key": cert_data, "thumbprint": AZURE_CERT_PASSWORD},
            )
        elif AZURE_CLIENT_SECRET:
            # Autenticación con secreto de cliente
            app = msal.ConfidentialClientApplication(
                AZURE_CLIENT_ID,
                authority=authority,
                client_credential=AZURE_CLIENT_SECRET,
            )
        else:
            logger.warning("No hay secreto ni certificado Azure configurado.")
            return None

        result = app.acquire_token_for_client(scopes=scopes)
        if "access_token" in result:
            token = result["access_token"]
            expires_in = result.get("expires_in", 3600)
            _graph_token_cache["token"] = token
            _graph_token_cache["expires_at"] = ahora + timedelta(seconds=expires_in - 60)
            logger.info("Token Graph API obtenido correctamente (expira en %ds)", expires_in)
            return token
        else:
            logger.error("Error obteniendo token Graph: %s", result.get("error_description", result))
            return None
    except Exception as e:
        logger.error("Excepción obteniendo token Graph: %s", e)
        return None


def subir_a_onedrive_graph(nombre_archivo, pdf_bytes, carpeta_remota):
    """
    Sube un archivo a OneDrive for Business via Microsoft Graph API.
    Usa el endpoint /me/drive o /drives/{driveId} según configuración.
    """
    import requests

    token = obtener_token_graph()
    if not token:
        return False

    try:
        # Construir URL de subida (PUT para archivos <4MB)
        # Endpoint para OneDrive for Business del usuario
        encoded_path = f"{carpeta_remota}/{nombre_archivo}".replace(" ", "%20")
        url = f"https://graph.microsoft.com/v1.0/users/{IMAP_USER}/drive/root:/{encoded_path}:/content"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/pdf",
        }

        resp = requests.put(url, headers=headers, data=pdf_bytes, timeout=60)

        if resp.status_code in (200, 201):
            logger.info("Subido a OneDrive (Graph API): %s", nombre_archivo)
            return True
        else:
            logger.error("Error subiendo a OneDrive: %d — %s", resp.status_code, resp.text[:300])
            return False
    except Exception as e:
        logger.error("Excepción subiendo a OneDrive: %s", e)
        return False

# =============================================================================
# [4] GOOGLE CALENDAR: GENERACIÓN DE ARCHIVOS .ics
# =============================================================================

def generar_ics(eventos):
    """
    Genera un archivo .ics con todos los eventos de plazos judiciales.
    Compatible con Google Calendar, Outlook y Apple Calendar.
    """
    try:
        from icalendar import Calendar, Event as ICSEvent
        import uuid

        cal = Calendar()
        cal.add("prodid", "-//Pipeline Judicial ASerges//ES")
        cal.add("version", "2.0")
        cal.add("calscale", "GREGORIAN")
        cal.add("method", "PUBLISH")
        cal.add("x-wr-calname", "Plazos Judiciales ASerges")
        cal.add("x-wr-timezone", "Europe/Madrid")

        for ev in eventos:
            ics_event = ICSEvent()
            ics_event.add("uid", str(uuid.uuid4()))
            ics_event.add("summary", ev["title"])
            ics_event.add("description", ev.get("description", ""))

            # Parsear fecha/hora
            try:
                dt_start = datetime.fromisoformat(ev["start"]).replace(
                    tzinfo=timezone(timedelta(hours=1))
                )
                dt_end = datetime.fromisoformat(ev["end"]).replace(
                    tzinfo=timezone(timedelta(hours=1))
                )
            except Exception:
                continue

            ics_event.add("dtstart", dt_start)
            ics_event.add("dtend", dt_end)
            ics_event.add("dtstamp", datetime.now(tz=timezone.utc))

            # Alarma 24h antes
            from icalendar import Alarm
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", f"RECORDATORIO: {ev['title']}")
            alarm.add("trigger", timedelta(hours=-24))
            ics_event.add_component(alarm)

            # Alarma 1h antes
            alarm2 = Alarm()
            alarm2.add("action", "DISPLAY")
            alarm2.add("description", f"RECORDATORIO: {ev['title']}")
            alarm2.add("trigger", timedelta(hours=-1))
            ics_event.add_component(alarm2)

            cal.add_component(ics_event)

        return cal.to_ical()
    except Exception as e:
        logger.error("Error generando .ics: %s", e)
        return None


def generar_eventos_gcal(clasificacion, metadatos, fecha_notificacion):
    """Genera lista de eventos para el calendario a partir de la clasificación LLM."""
    eventos = []
    if not clasificacion:
        return eventos

    plazos = clasificacion.get("plazos_procesales", [])
    proc = metadatos.get("num_procedimiento", "N/A")
    nig = metadatos.get("nig", "")

    for plazo in plazos:
        if not isinstance(plazo, dict):
            continue
        descripcion_plazo = plazo.get("descripcion", "Plazo judicial")
        tipo_plazo = plazo.get("tipo", "OTRO")
        dias = plazo.get("dias")
        fecha_limite = plazo.get("fecha_limite")

        fecha_evento = None
        if fecha_limite:
            for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]:
                try:
                    fecha_evento = datetime.strptime(fecha_limite, fmt)
                    break
                except ValueError:
                    continue
        if not fecha_evento and dias:
            try:
                fecha_evento = datetime.now() + timedelta(days=int(dias))
            except (ValueError, TypeError):
                pass
        if not fecha_evento:
            continue

        prefijo = "[FECHA JUDICIAL]" if tipo_plazo in ("VISTA", "JUICIO", "LANZAMIENTO") else "[PLAZO JUDICIAL]"
        titulo = f"{prefijo} {descripcion_plazo} - Proc. {proc}"

        eventos.append({
            "title": titulo,
            "start": fecha_evento.strftime("%Y-%m-%dT08:00:00"),
            "end": fecha_evento.strftime("%Y-%m-%dT08:30:00"),
            "description": f"Procedimiento: {proc}\nNIG: {nig}\n{descripcion_plazo}\nNotificación recibida: {fecha_notificacion}",
        })

    return eventos

# =============================================================================
# DESCARGA DE CORREOS IMAP
# =============================================================================

def es_procurador(remitente):
    remitente_lower = remitente.lower()
    for dominio in PROCURADORES_DOMINIOS:
        if dominio.lower() in remitente_lower:
            return True
    for email_proc in PROCURADORES_EMAILS:
        if email_proc.lower() in remitente_lower:
            return True
    return False


def descargar_correos_procuradores(since_date):
    correos_con_pdfs = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        logger.info("Login IMAP exitoso")
        mail.select("INBOX")

        fecha_imap = since_date.strftime("%d-%b-%Y")
        criterio = f"(SINCE {fecha_imap})"
        logger.info("Buscando correos con criterio: %s", criterio)
        _, msgnums = mail.search(None, criterio)
        ids = msgnums[0].split()
        logger.info("Encontrados %d correos desde %s", len(ids), criterio)

        for num in ids:
            _, data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            remitente = email.utils.parseaddr(msg.get("From", ""))[1]
            asunto = msg.get("Subject", "")

            if not es_procurador(remitente):
                continue

            adjuntos_pdf = []
            cuerpo = ""
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition", ""))
                if ct == "text/plain" and "attachment" not in cd:
                    try:
                        cuerpo += part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                if ct == "application/pdf" or (ct == "application/octet-stream" and ".pdf" in cd.lower()):
                    nombre = part.get_filename() or "documento.pdf"
                    pdf_bytes = part.get_payload(decode=True)
                    if pdf_bytes:
                        adjuntos_pdf.append((nombre, pdf_bytes))
                        logger.info("  Adjunto PDF: %s (%d bytes)", nombre, len(pdf_bytes))

            if adjuntos_pdf:
                logger.info("Correo de procurador: %s | Asunto: %s", remitente, asunto)
                correos_con_pdfs.append({
                    "remitente": remitente,
                    "asunto": asunto,
                    "cuerpo": cuerpo,
                    "adjuntos": adjuntos_pdf,
                })

        mail.logout()
    except Exception as e:
        logger.error("Error IMAP: %s", e)

    logger.info("Total correos de procuradores con PDFs: %d", len(correos_con_pdfs))
    return correos_con_pdfs

# =============================================================================
# [4] ENVÍO DE CORREO DE VERIFICACIÓN CON ADJUNTO .ics
# =============================================================================

def enviar_correo_verificacion(documentos_procesados, ics_bytes=None):
    if not documentos_procesados:
        return

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL
    msg["Subject"] = f"[Pipeline Judicial] Resumen de notificaciones — {ahora}"

    body = f"Pipeline Judicial v3 — Resumen de ejecución\n"
    body += f"Fecha: {ahora}\n"
    body += f"Documentos procesados: {len(documentos_procesados)}\n"
    body += "=" * 60 + "\n\n"

    for i, doc in enumerate(documentos_procesados, 1):
        body += f"--- Documento {i} ---\n"
        body += f"Remitente: {doc.get('remitente', 'N/A')}\n"
        body += f"Asunto correo: {doc.get('asunto', 'N/A')}\n"
        body += f"Archivo: {doc.get('nombre_archivo', 'N/A')}\n"
        body += f"Tipo resolución: {doc.get('tipo_resolucion', 'N/A')}\n"
        body += f"NIG: {doc.get('nig', 'N/A')}\n"
        body += f"Procedimiento: {doc.get('num_procedimiento', 'N/A')}\n"
        body += f"Texto extraído con: {doc.get('metodo_ocr', 'pdfplumber')}\n"
        if doc.get("plazos_info"):
            body += f"⚠ PLAZOS PROCESALES: {doc['plazos_info']}\n"
        if doc.get("resumen"):
            body += f"Resumen: {doc['resumen']}\n"
        body += f"Guardado en: {doc.get('ruta_local', 'N/A')}\n"
        body += f"OneDrive: {'Sí (Graph API)' if doc.get('subido_onedrive') else 'No'}\n\n"

    body += "=" * 60 + "\n"
    body += "Pipeline Judicial Automático v3 — Asesores y Abogados ASerges SL\n"

    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Adjuntar archivo .ics si hay eventos de calendario
    if ics_bytes:
        ics_part = MIMEBase("text", "calendar", method="PUBLISH")
        ics_part.set_payload(ics_bytes)
        encoders.encode_base64(ics_part)
        ics_part.add_header("Content-Disposition", "attachment", filename="plazos_judiciales.ics")
        msg.attach(ics_part)
        logger.info("Archivo .ics adjuntado al correo (%d bytes)", len(ics_bytes))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        logger.info("Correo de verificación enviado a %s", ALERT_EMAIL)
    except Exception as e:
        logger.error("Error enviando correo de verificación: %s", e)

# =============================================================================
# PIPELINE PRINCIPAL
# =============================================================================

def ejecutar_pipeline():
    logger.info("=" * 60)
    logger.info("INICIO PIPELINE JUDICIAL v3 — ASERGES S.L.")
    logger.info("Fecha: %s", datetime.now().isoformat())
    logger.info("=" * 60)

    # --- Procesar cola de pendientes de clasificar (ejecuciones anteriores) ---
    pendientes_clasificados = procesar_cola_pendientes()
    if pendientes_clasificados:
        logger.info("Pendientes clasificados en esta ejecución: %d", len(pendientes_clasificados))

    # --- Determinar ventana temporal ---
    last_run_str = cargar_last_run()
    if last_run_str:
        try:
            since_date = datetime.fromisoformat(last_run_str)
            logger.info("Última ejecución: %s", last_run_str)
        except Exception:
            since_date = datetime.now() - timedelta(hours=12)
    else:
        since_date = datetime.now() - timedelta(hours=12)
        logger.info("Primera ejecución, buscando correos de las últimas 12 horas")

    # --- Cargar hashes existentes ---
    hashes_existentes = cargar_hashes()
    logger.info("Hashes existentes: %d", len(hashes_existentes))

    # --- Verificar token Graph API para OneDrive ---
    token_graph = obtener_token_graph()
    if token_graph:
        logger.info("Graph API: token obtenido. OneDrive habilitado.")
    else:
        logger.warning("Graph API: sin token. OneDrive deshabilitado.")

    # --- Descargar correos de procuradores ---
    correos = descargar_correos_procuradores(since_date)

    if not correos:
        logger.info("No se encontraron correos nuevos de procuradores con PDFs adjuntos.")
        guardar_last_run()
        logger.info("PIPELINE FINALIZADO — Sin documentos nuevos")
        return []

    # --- Procesar cada correo y sus adjuntos ---
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    carpeta_local = os.path.join(LOCAL_NOTIF_BASE, fecha_hoy)
    os.makedirs(carpeta_local, exist_ok=True)

    documentos_procesados = []
    todos_eventos_gcal = []

    for correo in correos:
        remitente = correo["remitente"]
        asunto = correo["asunto"]

        for nombre_original, pdf_bytes in correo["adjuntos"]:
            sha256 = calcular_hash(pdf_bytes)
            if sha256 in hashes_existentes:
                logger.info("DUPLICADO: %s (hash ya procesado)", nombre_original)
                continue

            logger.info("Procesando: %s de %s", nombre_original, remitente)

            # [3] Extraer texto con fallback OCR
            texto_pdf = extraer_texto_pdf(pdf_bytes)
            metodo_ocr = "Tesseract OCR" if len(texto_pdf.strip()) > 0 and "OCR" in LOG_FILE else "pdfplumber"

            # Extraer metadatos con regex
            metadatos = extraer_metadatos_regex(texto_pdf)
            logger.info("Metadatos regex: NIG=%s Proc=%s Tipo=%s",
                        metadatos.get("nig"), metadatos.get("num_procedimiento"),
                        metadatos.get("tipo_resolucion"))

            # [2] Clasificar con LLM (con reintentos)
            clasificacion = clasificar_con_llm(texto_pdf, asunto, remitente)

            # Determinar nombre descriptivo
            if clasificacion and clasificacion.get("nombre_descriptivo"):
                nombre_desc = sanitizar_nombre(clasificacion["nombre_descriptivo"])
            else:
                tipo = metadatos.get("tipo_resolucion", "DOC")
                nombre_desc = sanitizar_nombre(tipo or "DOC")

            # Construir nombre de archivo
            proc = sanitizar_nombre(metadatos.get("num_procedimiento", ""))
            nig = sanitizar_nombre(metadatos.get("nig", ""))
            partes_nombre = [fecha_hoy]
            if proc:
                partes_nombre.append(proc)
            if nig:
                partes_nombre.append(nig)
            partes_nombre.append(nombre_desc)
            nombre_archivo = "_".join(partes_nombre) + ".pdf"

            # Guardar localmente
            ruta_local = os.path.join(carpeta_local, nombre_archivo)
            contador = 1
            ruta_base = ruta_local
            while os.path.exists(ruta_local):
                nombre_sin_ext = os.path.splitext(ruta_base)[0]
                ruta_local = f"{nombre_sin_ext}_{contador}.pdf"
                contador += 1
            with open(ruta_local, "wb") as f:
                f.write(pdf_bytes)
            logger.info("Guardado localmente: %s", ruta_local)

            # Si la clasificación falló, añadir a cola de pendientes
            if not clasificacion:
                agregar_pendiente_clasificar(nombre_original, ruta_local, asunto, remitente, sha256)

            # [5] Subir a OneDrive via Graph API
            subido_onedrive = False
            if token_graph:
                carpeta_remota = f"{ONEDRIVE_NOTIF_FOLDER}/{fecha_hoy}"
                subido_onedrive = subir_a_onedrive_graph(nombre_archivo, pdf_bytes, carpeta_remota)

            # Generar eventos de calendario
            eventos = generar_eventos_gcal(clasificacion, metadatos, fecha_hoy)
            todos_eventos_gcal.extend(eventos)

            # Información de plazos para el correo
            plazos_info = ""
            if clasificacion:
                plazos = clasificacion.get("plazos_procesales", [])
                if plazos:
                    plazos_textos = [
                        f"{p.get('descripcion', 'Plazo')} ({p.get('dias', '?')} días)"
                        for p in plazos if isinstance(p, dict)
                    ]
                    plazos_info = "; ".join(plazos_textos)
                elif clasificacion.get("urgente"):
                    plazos_info = "Documento marcado como urgente"

            hashes_existentes.add(sha256)

            documentos_procesados.append({
                "remitente": remitente,
                "asunto": asunto,
                "nombre_archivo": nombre_archivo,
                "tipo_resolucion": (clasificacion or {}).get("tipo_resolucion") or metadatos.get("tipo_resolucion", "N/A"),
                "nig": metadatos.get("nig", "N/A"),
                "num_procedimiento": metadatos.get("num_procedimiento", "N/A"),
                "plazos_info": plazos_info,
                "resumen": (clasificacion or {}).get("resumen_breve", ""),
                "ruta_local": ruta_local,
                "subido_onedrive": subido_onedrive,
                "metodo_ocr": metodo_ocr,
                "hash": sha256,
            })
            logger.info("Documento procesado: %s", nombre_archivo)

    # --- Guardar hashes actualizados ---
    guardar_hashes(hashes_existentes)

    # --- Guardar eventos pendientes de Google Calendar ---
    ics_bytes = None
    if todos_eventos_gcal:
        with open(GCAL_PENDING_FILE, "w") as f:
            json.dump(todos_eventos_gcal, f, ensure_ascii=False, indent=2)
        logger.info("Eventos Google Calendar pendientes guardados: %d", len(todos_eventos_gcal))
        # [4] Generar archivo .ics
        ics_bytes = generar_ics(todos_eventos_gcal)
        if ics_bytes:
            ics_path = os.path.join(carpeta_local, "plazos_judiciales.ics")
            with open(ics_path, "wb") as f:
                f.write(ics_bytes)
            logger.info("Archivo .ics guardado: %s", ics_path)

    # --- Enviar correo de verificación con .ics adjunto ---
    if documentos_procesados:
        enviar_correo_verificacion(documentos_procesados, ics_bytes=ics_bytes)

    # --- Guardar timestamp ---
    guardar_last_run()

    # --- Resumen ---
    logger.info("=" * 60)
    logger.info("PIPELINE FINALIZADO")
    logger.info("Documentos procesados: %d", len(documentos_procesados))
    logger.info("Eventos calendario generados: %d", len(todos_eventos_gcal))
    logger.info("Subidos a OneDrive (Graph API): %d", sum(1 for d in documentos_procesados if d.get("subido_onedrive")))
    logger.info("Pendientes de clasificar en cola: %d", len(cargar_pendientes_clasificar()))
    logger.info("=" * 60)

    return documentos_procesados


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    try:
        resultado = ejecutar_pipeline()
        if resultado:
            print(f"\nPipeline v3 completado: {len(resultado)} documentos procesados")
        else:
            print("\nPipeline v3 completado: sin documentos nuevos")
    except Exception as e:
        logger.exception("ERROR CRÍTICO en pipeline: %s", e)
        sys.exit(1)
