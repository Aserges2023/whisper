#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Judicial Diario - ASERGES (versión sandbox Linux)
==========================================================
Fases:
  1. Descarga IMAP de correos de procuradores autorizados con PDFs adjuntos
  2. Clasificación con worker judicial v3 (pdfplumber + regex especializadas)
  3. Copia a /home/ubuntu/Notificaciones/YYYY-MM-DD con nombre descriptivo
  4. Subida a MNprogram (opcional, --mnprogram)
  5. Informe resumen Markdown + JSON

Uso:
  python3 pipeline_judicial_diario.py                      # día anterior
  python3 pipeline_judicial_diario.py --fecha 2026-08-19
  python3 pipeline_judicial_diario.py --desde 2026-08-01 --hasta 2026-08-19
  python3 pipeline_judicial_diario.py --mnprogram          # activa subida
"""

import argparse
import email
import email.header
import email.utils
import hashlib
import imaplib
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu")
CONFIG_DIR = BASE_DIR / "judicial_config"
CONFIG_PATH = CONFIG_DIR / "config.json"
MAPEO_PATH = CONFIG_DIR / "mapeo_expedientes.json"

NOTIFICACIONES_DIR = BASE_DIR / "Notificaciones"
TRABAJO_DIR = BASE_DIR / "judicial_diario"
USU2_DIR = BASE_DIR / "Usu2"

DEFAULT_CFG = {
    "imap": {
        "host": "imap.ionos.es",
        "port": 993,
        "user": "santiago@aserges.es",
        "password": "Palacios@2024/",
    },
    "mnprogram": {
        "url": "https://mnprogramweb.net",
        "user": "santiago@aserges.es",
        "password": "Pinillos2024",
        "empresa": "ASESORES Y ABOGADOS ASERGES SL",
    },
    "procuradores_autorizados": [
        "solasortega.com",
        "procuradoracarmencarrasco@gmail.com",
        "belengoni.com",
        "pazmontero.com",
    ],
}


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return DEFAULT_CFG


CFG = cargar_config()
IMAP_HOST = CFG["imap"]["host"]
IMAP_PORT = int(CFG["imap"]["port"])
IMAP_USER = CFG["imap"]["user"]
IMAP_PASS = CFG["imap"]["password"]
PROCURADORES_AUTORIZADOS = CFG["procuradores_autorizados"]

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
TRABAJO_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = TRABAJO_DIR / "pipeline_judicial_diario.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("pipeline_judicial_diario")

stats = {
    "correos_revisados": 0,
    "correos_procuradores": 0,
    "pdfs_descargados": 0,
    "pdfs_clasificados": 0,
    "pdfs_vinculables": 0,
    "pdfs_guardados_notificaciones": 0,
    "pdfs_subidos_mnprogram": 0,
    "pdfs_sin_mapeo": 0,
    "duplicados_omitidos": 0,
    "errores": [],
    "sin_mapeo": [],
}


# ─────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    if not name:
        return "documento"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(". ")
    return name[:120] or "documento"


def decode_header_value(value) -> str:
    if value is None:
        return ""
    try:
        parts = email.header.decode_header(value)
    except Exception:
        return str(value)
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(charset or "utf-8", errors="replace"))
            except Exception:
                out.append(part.decode("latin-1", errors="replace"))
        else:
            out.append(str(part))
    return " ".join(out).strip()


def es_procurador_autorizado(from_addr: str) -> bool:
    fl = (from_addr or "").lower()
    return any(p.lower() in fl for p in PROCURADORES_AUTORIZADOS)


def normalizar_procedimiento(proc: str) -> str:
    if not proc:
        return ""
    proc = proc.replace("-", "/").replace(" ", "")
    parts = proc.split("/")
    if len(parts) == 2:
        try:
            num = str(int(parts[0]))
            anho = parts[1]
            if len(anho) == 2:
                anho = "20" + anho
            return f"{num}/{anho}"
        except ValueError:
            pass
    return proc


def limpiar_ocr(texto: str) -> str:
    """Corrige errores típicos de OCR en documentos judiciales españoles."""
    if not texto:
        return ""
    reemplazos = {
        r"D/fla\.": "D/ña.",
        r"D/na\.": "D/ña.",
        r"Dfla\.": "Dña.",
        r"D0n\b": "Don",
        r"JUZQADO": "JUZGADO",
        r"PROCEDlMIENTO": "PROCEDIMIENTO",
        r"N\.l\.G\.": "N.I.G.",
    }
    for pat, rep in reemplazos.items():
        texto = re.sub(pat, rep, texto)
    return texto


def cargar_mapeo() -> dict:
    if MAPEO_PATH.exists():
        try:
            with open(MAPEO_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("No se pudo leer el mapeo de expedientes: %s", e)
    return {"por_procedimiento": {}, "por_asunto_regex": {}}


# ─────────────────────────────────────────────
# WORKER DE CLASIFICACIÓN JUDICIAL v3
# ─────────────────────────────────────────────
PATRONES = {
    "nig": [
        r"N\.?\s?I\.?\s?G\.?\s*[:\-]?\s*([0-9]{2}[\.\s][0-9]{2}[\.\s][0-9][\-\s][0-9]{4}[/\s][0-9]{4,7})",
        r"N\.?I\.?G\.?\s*[:\-]?\s*([0-9]{4,5}\s*[/\-]\s*[0-9]{4,7})",
        r"NIG\s*[:\-]?\s*([0-9][0-9A-Z\.\-/]{8,30})",
    ],
    "procedimiento": [
        r"(?:Procedimiento|Proc\.?|Autos?|Juicio|Expediente)\s*(?:Ordinario|Verbal|Monitorio|Ejecuci[oó]n|Divorcio|Concurso|Apelaci[oó]n|Recurso|de\s+\w+)?\s*(?:n[ºo°]?\.?\s*)?[:\s]*([0-9]{1,6}\s*[/\-]\s*[0-9]{4})",
        r"(?:Rollo|Recurso)\s+(?:de\s+)?(?:Apelaci[oó]n|Casaci[oó]n|Suplicaci[oó]n)?\s*(?:n[ºo°]?\.?\s*)?([0-9]{1,6}\s*[/\-]\s*[0-9]{4})",
        r"\b([0-9]{3,6}\s*[/\-]\s*20[0-9]{2})\b",
    ],
    "organo": [
        r"(JUZGADO\s+DE\s+[A-ZÁÉÍÓÚÑ0-9\.\s\-]{5,80})",
        r"(AUDIENCIA\s+PROVINCIAL\s+DE\s+[A-ZÁÉÍÓÚÑ\s]{3,40})",
        r"(TRIBUNAL\s+SUPERIOR\s+DE\s+JUSTICIA[A-ZÁÉÍÓÚÑ\s]{0,40})",
        r"(JDO\.?\s*[A-ZÁÉÍÓÚÑ0-9\.\s]{5,60})",
    ],
    "localidad": [
        r"(?:de|en)\s+(LOGRO[ÑN]O|CALAHORRA|HARO|N[AÁ]JERA|LA\s+RIOJA|MADRID|BILBAO|VITORIA|ZARAGOZA|PAMPLONA|BURGOS|SORIA)",
    ],
}

REGEX_PARTES = [
    r"(?:Demandante|Actor(?:a)?|Ejecutante|Solicitante|Concursad[oa]|Acreedor)\s*[:\-]?\s*((?:D\.|D[ñn]a\.|DON|DO[ÑN]A)?\s*[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\s,]{4,70})",
    r"(?:Demandad[oa]s?|Ejecutad[oa]s?|Parte\s+contraria|Deudor)\s*[:\-]?\s*((?:D\.|D[ñn]a\.|DON|DO[ÑN]A)?\s*[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\.\s,]{4,70})",
    r"(?:PROCURADOR(?:A)?\s+D[EL]{1,2}\s+)([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ\s,]{4,60})",
]

SUBTIPOS_RESOLUCION = [
    (r"auto\D{0,40}tasaci[oó]n\D{0,20}costas", "Auto tasacion costas"),
    (r"auto\D{0,30}admisi[oó]n", "Auto admision"),
    (r"auto\D{0,30}inadmisi[oó]n", "Auto inadmision"),
    (r"auto\D{0,30}archivo", "Auto archivo"),
    (r"auto\D{0,30}despach\D{0,20}ejecuci[oó]n", "Auto despacho ejecucion"),
    (r"auto\D{0,30}ejecuci[oó]n", "Auto ejecucion"),
    (r"auto\D{0,30}aclaraci[oó]n", "Auto aclaracion"),
    (r"auto\D{0,30}medidas", "Auto medidas"),
    (r"decreto\D{0,30}admisi[oó]n", "Decreto admision"),
    (r"decreto\D{0,30}terminaci[oó]n", "Decreto terminacion"),
    (r"decreto\D{0,30}tasaci[oó]n", "Decreto tasacion costas"),
    (r"diligencia\D{0,30}negator", "Dil negatoria prueba"),
    (r"diligencia\D{0,30}requerimiento\D{0,20}datos", "Dil requerimiento datos"),
    (r"diligencia\D{0,30}requerimiento", "Dil requerimiento"),
    (r"diligencia\D{0,30}ordenaci[oó]n", "Dil ordenacion"),
    (r"diligencia\D{0,30}constancia", "Dil constancia"),
    (r"sentencia\D{0,30}estimator", "Sentencia estimatoria"),
    (r"sentencia\D{0,30}desestimator", "Sentencia desestimatoria"),
    (r"sentencia\D{0,30}firme", "Sentencia firme"),
    (r"\bsentencia\b", "Sentencia"),
    (r"providencia\D{0,30}se[nñ]alamiento", "Providencia senalamiento"),
    (r"\bprovidencia\b", "Providencia"),
    (r"se[nñ]ala\D{0,40}(?:vista|juicio)|acto\s+de\s+(?:la\s+)?vista|acto\s+de\s+juicio", "Senalamiento vista"),
    (r"tasaci[oó]n\D{0,20}costas", "Tasacion costas"),
    (r"emplazamiento|se\s+emplaza", "Emplazamiento"),
    (r"citaci[oó]n|se\s+cita\b", "Citacion"),
    (r"requerimiento\D{0,20}pago", "Requerimiento pago"),
    (r"\brequerimiento\b|se\s+requiere", "Requerimiento"),
    (r"traslado\D{0,30}escrito", "Traslado escrito"),
    (r"acuse\D{0,20}(?:de\s+)?(?:recibo|presentaci[oó]n)", "Acuse presentacion"),
    (r"minuta|proforma|factura", "Minuta proforma"),
    (r"\bexhorto\b", "Exhorto"),
    (r"\bmandamiento\b", "Mandamiento"),
    (r"\bdecreto\b", "Decreto"),
    (r"\bauto\b", "Auto"),
    (r"\bdiligencia\b", "Diligencia"),
]

REGEX_PLAZOS = [
    r"(?:en\s+el\s+)?plazo\s+de\s+(\w+|\d+)\s+d[ií]as?\s*(h[aá]biles|naturales)?",
    r"(?:dentro\s+del?\s+(?:plazo\s+de\s+)?)(\w+|\d+)\s+d[ií]as?",
    r"t[eé]rmino\s+de\s+(\w+|\d+)\s+d[ií]as?",
]

REGEX_SENALAMIENTOS = [
    r"(?:se[nñ]al[aá]ndose|se\s+se[nñ]ala|se[nñ]alad[oa]\s+para)\s+(?:el\s+)?(?:d[ií]a\s+)?(\d{1,2}[\s/\-\.]+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|\d{1,2})[\s/\-\.,]+(?:de\s+)?\d{2,4})[^\n]{0,60}",
    r"(?:vista|juicio|comparecencia|audiencia|lanzamiento)[^\n]{0,40}?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
]

REGEX_RECURSO = [
    r"cabe\s+(?:interponer\s+)?recurso\s+de\s+(\w+)",
    r"recurso\s+de\s+(apelaci[oó]n|reposici[oó]n|revisi[oó]n|casaci[oó]n|queja|suplicaci[oó]n)",
]

NUM_LETRAS = {
    "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "quince": 15, "veinte": 20, "treinta": 30,
}


def extraer_texto_pdf(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber no instalado")
        return ""
    texto = ""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:25]:
                t = page.extract_text()
                if t:
                    texto += t + "\n"
    except Exception as e:
        log.warning("Error extrayendo texto de %s: %s", pdf_path.name, e)
    return limpiar_ocr(texto)


def extraer_metadato(texto: str, campo: str) -> str:
    for patron in PATRONES.get(campo, []):
        m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" .,-")
    return ""


def detectar_tipo_resolucion(texto: str) -> str:
    tl = texto.lower()
    for patron, nombre in SUBTIPOS_RESOLUCION:
        if re.search(patron, tl):
            return nombre
    return "NOTIFICACION"


def extraer_partes(texto: str) -> list:
    partes = []
    for patron in REGEX_PARTES:
        for m in re.findall(patron, texto, re.IGNORECASE):
            nombre = re.sub(r"\s+", " ", m).strip(" .,-")
            nombre = re.sub(r"^(?:D\.|D[ñn]a\.|DON|DO[ÑN]A)\s*", "", nombre, flags=re.IGNORECASE).strip()
            if 4 < len(nombre) < 70 and nombre not in partes:
                partes.append(nombre)
    return partes[:6]


def detectar_plazos(texto: str) -> list:
    plazos = []
    for patron in REGEX_PLAZOS:
        for m in re.finditer(patron, texto, re.IGNORECASE):
            valor = m.group(1)
            dias = None
            if valor.isdigit():
                dias = int(valor)
            elif valor.lower() in NUM_LETRAS:
                dias = NUM_LETRAS[valor.lower()]
            if dias:
                tipo = "hábiles"
                if m.lastindex and m.lastindex >= 2 and m.group(2):
                    tipo = m.group(2)
                item = {"dias": dias, "computo": tipo, "cita": m.group(0).strip()[:160]}
                if item not in plazos:
                    plazos.append(item)
    return plazos[:8]


def detectar_senalamientos(texto: str) -> list:
    res = []
    for patron in REGEX_SENALAMIENTOS:
        for m in re.finditer(patron, texto, re.IGNORECASE):
            item = {"fecha": m.group(1).strip(), "cita": m.group(0).strip()[:160]}
            if item not in res:
                res.append(item)
    return res[:6]


def detectar_recursos(texto: str) -> list:
    res = []
    for patron in REGEX_RECURSO:
        for m in re.findall(patron, texto, re.IGNORECASE):
            v = m.strip().lower()
            if v and v not in res:
                res.append(v)
    return res[:4]


def calcular_prioridad(meta: dict) -> str:
    if not meta.get("texto_len"):
        return "PENDIENTE"
    if meta.get("senalamientos") or meta.get("plazos") or meta.get("recursos"):
        return "ALTA"
    tipo = (meta.get("tipo_resolucion") or "").lower()
    if any(k in tipo for k in ["sentencia", "auto", "decreto", "requerimiento", "emplazamiento", "citacion"]):
        return "MEDIA"
    return "BAJA"


def clasificar_pdf(info: dict) -> dict:
    pdf_path = info["path"]
    texto = extraer_texto_pdf(pdf_path)

    nig = extraer_metadato(texto, "nig")
    procedimiento = extraer_metadato(texto, "procedimiento")
    organo = extraer_metadato(texto, "organo")
    localidad = extraer_metadato(texto, "localidad")
    tipo_resolucion = detectar_tipo_resolucion(texto)
    partes = extraer_partes(texto)
    plazos = detectar_plazos(texto)
    senalamientos = detectar_senalamientos(texto)
    recursos = detectar_recursos(texto)

    # Fallback: buscar procedimiento en el asunto del correo
    if not procedimiento:
        m = re.search(r"\b(\d{1,5})\s*[/\-]\s*(\d{2,4})\b", info.get("subject", ""))
        if m:
            procedimiento = f"{m.group(1)}/{m.group(2)}"

    parte_principal = partes[0] if partes else ""
    vinculable = bool(procedimiento or nig)

    proc_fn = procedimiento.replace("/", "-").replace(" ", "") if procedimiento else "SIN-PROC"
    parte_corta = sanitize_filename(parte_principal[:28]) if parte_principal else "PARTE"
    nombre_desc = sanitize_filename(
        f"{info['hora']} - {parte_corta} - {proc_fn} - {tipo_resolucion}.pdf"
    )
    if not nombre_desc.lower().endswith(".pdf"):
        nombre_desc += ".pdf"

    meta = {
        **info,
        "path": str(pdf_path),
        "texto_len": len(texto.strip()),
        "texto_breve": texto[:2000],
        "nig": nig,
        "procedimiento": procedimiento,
        "proc_normalizado": normalizar_procedimiento(procedimiento),
        "organo": organo,
        "localidad": localidad,
        "tipo_resolucion": tipo_resolucion,
        "partes": partes,
        "parte_principal": parte_principal,
        "plazos": plazos,
        "senalamientos": senalamientos,
        "recursos": recursos,
        "vinculable": vinculable,
        "nombre_descriptivo": nombre_desc,
    }
    meta["prioridad"] = calcular_prioridad(meta)

    stats["pdfs_clasificados"] += 1
    if vinculable:
        stats["pdfs_vinculables"] += 1

    log.info(
        "  Clasificado: %s | NIG:%s | Proc:%s | %s | Prioridad:%s | %d chars",
        nombre_desc, nig or "-", procedimiento or "-", tipo_resolucion,
        meta["prioridad"], meta["texto_len"],
    )
    return meta


# ─────────────────────────────────────────────
# FASE 1: DESCARGA IMAP
# ─────────────────────────────────────────────
def descargar_pdfs_imap(fecha_inicio: datetime, fecha_fin: datetime, work_dir: Path) -> list:
    log.info("=" * 70)
    log.info("FASE 1: Descarga IMAP %s | %s -> %s",
             IMAP_HOST, fecha_inicio.strftime("%Y-%m-%d %H:%M"), fecha_fin.strftime("%Y-%m-%d %H:%M"))
    log.info("=" * 70)

    work_dir.mkdir(parents=True, exist_ok=True)
    descargados = []
    hashes = set()

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        log.info("Login IMAP exitoso (%s)", IMAP_USER)
        mail.select("INBOX")

        fecha_imap = fecha_inicio.strftime("%d-%b-%Y")
        before_imap = (fecha_fin + timedelta(days=1)).strftime("%d-%b-%Y")
        criterio = f'(SINCE "{fecha_imap}" BEFORE "{before_imap}")'
        log.info("Criterio de búsqueda: %s", criterio)
        status, messages = mail.search(None, criterio)
        if status != "OK":
            log.warning("Búsqueda IMAP sin resultados")
            mail.logout()
            return []

        ids = messages[0].split()
        stats["correos_revisados"] = len(ids)
        log.info("Mensajes en la ventana temporal: %d", len(ids))

        for msg_id in ids:
            try:
                status, data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    continue
                msg = email.message_from_bytes(data[0][1])

                from_raw = decode_header_value(msg.get("From", ""))
                from_addr = email.utils.parseaddr(msg.get("From", ""))[1] or from_raw
                subject = decode_header_value(msg.get("Subject", "Sin asunto"))
                date_str = msg.get("Date", "")

                if not (es_procurador_autorizado(from_addr) or es_procurador_autorizado(from_raw)):
                    continue

                try:
                    msg_date = email.utils.parsedate_to_datetime(date_str)
                    msg_dt = msg_date.replace(tzinfo=None)
                except Exception:
                    msg_dt = fecha_inicio
                if not (fecha_inicio <= msg_dt <= fecha_fin):
                    continue

                stats["correos_procuradores"] += 1
                hora_str = msg_dt.strftime("%Hh%M")
                fecha_recepcion = msg_dt.strftime("%Y-%m-%d")
                log.info("Correo procurador: %s | %s | %s", from_addr, msg_dt.strftime("%d/%m %H:%M"), subject[:70])

                tiene_pdf = False
                for part in msg.walk():
                    fn = part.get_filename()
                    fn = decode_header_value(fn) if fn else ""
                    ct = part.get_content_type()
                    if not (ct == "application/pdf" or (fn and fn.lower().endswith(".pdf"))):
                        continue
                    pdf_data = part.get_payload(decode=True)
                    if not pdf_data or len(pdf_data) < 100:
                        continue
                    if not pdf_data[:5].startswith(b"%PDF"):
                        log.warning("  Adjunto sin cabecera %%PDF, omitido: %s", fn)
                        continue

                    sha = hashlib.sha256(pdf_data).hexdigest()
                    if sha in hashes:
                        stats["duplicados_omitidos"] += 1
                        log.info("  Duplicado omitido: %s", fn)
                        continue
                    hashes.add(sha)

                    filename = sanitize_filename(fn or "adjunto.pdf")
                    if not filename.lower().endswith(".pdf"):
                        filename += ".pdf"
                    pdf_path = work_dir / filename
                    c = 1
                    while pdf_path.exists():
                        pdf_path = work_dir / f"{Path(filename).stem}_{c}.pdf"
                        c += 1
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_data)

                    tiene_pdf = True
                    stats["pdfs_descargados"] += 1
                    log.info("  PDF descargado: %s (%d bytes)", pdf_path.name, len(pdf_data))
                    descargados.append({
                        "path": pdf_path,
                        "from": from_addr,
                        "subject": subject,
                        "hora": hora_str,
                        "fecha_recepcion": fecha_recepcion,
                        "filename_original": filename,
                        "sha256": sha,
                    })

                if not tiene_pdf:
                    log.warning("  Correo de procurador SIN PDF adjunto: %s", subject[:60])

            except Exception as e:
                log.error("Error procesando mensaje: %s", e)
                stats["errores"].append(f"IMAP mensaje: {e}")

        mail.logout()
        log.info("Total PDFs descargados: %d", stats["pdfs_descargados"])

    except Exception as e:
        log.error("Error IMAP: %s", e)
        stats["errores"].append(f"IMAP: {e}")

    return descargados


# ─────────────────────────────────────────────
# FASE 3: GUARDAR EN NOTIFICACIONES
# ─────────────────────────────────────────────
def guardar_en_notificaciones(clasificados: list):
    log.info("=" * 70)
    log.info("FASE 3: Copia en /home/ubuntu/Notificaciones por fecha de recepción")
    log.info("=" * 70)

    for doc in clasificados:
        try:
            fecha = doc.get("fecha_recepcion") or datetime.now().strftime("%Y-%m-%d")
            destino_dir = NOTIFICACIONES_DIR / fecha
            destino_dir.mkdir(parents=True, exist_ok=True)
            nombre = doc["nombre_descriptivo"]
            dest = destino_dir / nombre
            c = 1
            while dest.exists():
                dest = destino_dir / f"{Path(nombre).stem}_{c}.pdf"
                c += 1
            shutil.copy2(doc["path"], dest)
            doc["ruta_notificacion"] = str(dest)
            stats["pdfs_guardados_notificaciones"] += 1
            log.info("  Guardado: %s/%s", fecha, dest.name)
        except Exception as e:
            log.error("Error guardando en Notificaciones: %s", e)
            stats["errores"].append(f"Notificaciones: {e}")


# ─────────────────────────────────────────────
# FASE 3b: CLASIFICAR EN USU2 (si existe)
# ─────────────────────────────────────────────
def clasificar_en_usu2(clasificados: list, mapeo: dict):
    if not USU2_DIR.exists():
        log.info("Usu2 no disponible en el sandbox; se omite la reclasificación local.")
        return
    for doc in clasificados:
        cliente = None
        proc = doc.get("proc_normalizado", "")
        if proc and proc in mapeo.get("por_procedimiento", {}):
            cliente = mapeo["por_procedimiento"][proc]
        if not cliente:
            for rx, c in mapeo.get("por_asunto_regex", {}).items():
                if re.search(rx, doc.get("subject", "")) or re.search(rx, doc.get("texto_breve", "")):
                    cliente = c
                    break
        if cliente:
            dest_dir = USU2_DIR / cliente
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(doc.get("ruta_notificacion", doc["path"]), dest_dir / Path(doc["nombre_descriptivo"]).name)
                doc["carpeta_usu2"] = cliente
                log.info("  Usu2: %s -> %s", doc["nombre_descriptivo"], cliente)
            except Exception as e:
                stats["errores"].append(f"Usu2: {e}")
        else:
            stats["pdfs_sin_mapeo"] += 1
            stats["sin_mapeo"].append(doc["nombre_descriptivo"])


# ─────────────────────────────────────────────
# FASE 4: SUBIDA A MNPROGRAM
# ─────────────────────────────────────────────
def subir_a_mnprogram(clasificados: list):
    log.info("=" * 70)
    log.info("FASE 4: Subida a MNprogram")
    log.info("=" * 70)

    vinculables = [d for d in clasificados if d.get("vinculable")]
    if not vinculables:
        log.info("No hay documentos vinculables para subir.")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright no instalado; se omite la subida a MNprogram.")
        stats["errores"].append("Playwright no disponible")
        return

    mn = CFG["mnprogram"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        try:
            page.goto(mn["url"], timeout=60000)
            page.wait_for_timeout(3000)
            page.fill("input[placeholder*='Correo']", mn["user"], timeout=30000)
            page.click("text=Siguiente", timeout=15000)
            page.wait_for_timeout(2000)
            page.fill("input[type='password']", mn["password"], timeout=30000)
            page.click("button:has-text('Iniciar')", timeout=15000)
            page.wait_for_timeout(6000)
            try:
                page.click(f"text={mn['empresa']}", force=True, timeout=30000)
            except Exception:
                log.warning("Selector de empresa no encontrado; se continúa.")
            page.wait_for_timeout(8000)
            log.info("Login MNprogram completado")

            for doc in vinculables:
                try:
                    # La navegación por expediente depende de la UI concreta.
                    log.info("  Buscando expediente para: %s (%s)",
                             doc.get("parte_principal") or "sin parte", doc.get("proc_normalizado") or "sin proc")
                    page.wait_for_selector("div[id='col_numyearcompuesto']", timeout=60000)
                    # Aquí se implementa la búsqueda concreta y subida
                    tab = page.locator("div[role='tab']:has-text('ADJUNTOS')")
                    if tab.count() > 0:
                        tab.first.click()
                        page.wait_for_timeout(2000)
                        with page.expect_file_chooser() as fc:
                            page.click("button[title='Subir fichero']")
                        fc.value.set_files(doc.get("ruta_notificacion", doc["path"]))
                        page.wait_for_timeout(4000)
                        stats["pdfs_subidos_mnprogram"] += 1
                        doc["subido_mnprogram"] = True
                        log.info("  Subido a MNprogram: %s", doc["nombre_descriptivo"])
                except Exception as e:
                    log.error("  Error subiendo %s: %s", doc.get("nombre_descriptivo"), e)
                    stats["errores"].append(f"MNprogram {doc.get('nombre_descriptivo')}: {e}")
        except Exception as e:
            log.error("Error en MNprogram: %s", e)
            stats["errores"].append(f"MNprogram login: {e}")
        finally:
            try:
                page.screenshot(path=str(TRABAJO_DIR / "mnprogram_estado.png"), full_page=True)
            except Exception:
                pass
            browser.close()


# ─────────────────────────────────────────────
# FASE 5: INFORME
# ─────────────────────────────────────────────
def generar_informe(clasificados: list, etiqueta: str, work_dir: Path) -> Path:
    log.info("=" * 70)
    log.info("FASE 5: Informe resumen")
    log.info("=" * 70)

    work_dir.mkdir(parents=True, exist_ok=True)
    informe_path = work_dir / "informe_resumen.md"
    ahora = datetime.now()

    L = [
        "# Informe del Pipeline Judicial Diario",
        "",
        "**Despacho:** Asesores y Abogados ASERGES SL  ",
        f"**Fecha de ejecución:** {ahora.strftime('%d/%m/%Y %H:%M')}  ",
        f"**Ventana procesada:** {etiqueta}",
        "",
        "## Resumen de ejecución",
        "",
        "| Métrica | Valor |",
        "|:---|---:|",
        f"| Correos revisados en la ventana | {stats['correos_revisados']} |",
        f"| Correos de procuradores autorizados | {stats['correos_procuradores']} |",
        f"| PDFs descargados | {stats['pdfs_descargados']} |",
        f"| PDFs clasificados | {stats['pdfs_clasificados']} |",
        f"| PDFs vinculables a expediente | {stats['pdfs_vinculables']} |",
        f"| Guardados en Notificaciones | {stats['pdfs_guardados_notificaciones']} |",
        f"| Subidos a MNprogram | {stats['pdfs_subidos_mnprogram']} |",
        f"| Duplicados omitidos | {stats['duplicados_omitidos']} |",
        f"| Errores registrados | {len(stats['errores'])} |",
        "",
    ]

    if clasificados:
        L += [
            "## Documentos procesados",
            "",
            "| Hora | Parte | Procedimiento | NIG | Tipo | Prioridad |",
            "|:---|:---|:---|:---|:---|:---|",
        ]
        for d in clasificados:
            L.append(
                f"| {d.get('hora','-')} | {d.get('parte_principal') or '-'} | "
                f"{d.get('proc_normalizado') or '-'} | {d.get('nig') or '-'} | "
                f"{d.get('tipo_resolucion','-')} | {d.get('prioridad','-')} |"
            )
        L.append("")

        altas = [d for d in clasificados if d.get("prioridad") == "ALTA"]
        if altas:
            L += ["## Prioridad ALTA — actuación requerida", ""]
            for d in altas:
                L.append(f"### {d['nombre_descriptivo']}")
                L.append("")
                L.append(f"- **Órgano:** {d.get('organo') or 'No identificado'}")
                L.append(f"- **Procedimiento:** {d.get('proc_normalizado') or 'No identificado'}")
                L.append(f"- **NIG:** {d.get('nig') or 'No identificado'}")
                for p in d.get("plazos", []):
                    L.append(f"- **Plazo:** {p['dias']} días {p['computo']} — «{p['cita']}»")
                for s in d.get("senalamientos", []):
                    L.append(f"- **Señalamiento:** {s['fecha']} — «{s['cita']}»")
                for r in d.get("recursos", []):
                    L.append(f"- **Recurso:** {r}")
                L.append(f"- **Ruta:** `{d.get('ruta_notificacion', d.get('path'))}`")
                L.append("")

        pendientes = [d for d in clasificados if d.get("prioridad") == "PENDIENTE" or not d.get("vinculable")]
        if pendientes:
            L += [
                "## Pendientes de revisión manual",
                "",
                "| Archivo | Motivo |",
                "|:---|:---|",
            ]
            for d in pendientes:
                motivo = "PDF sin texto extraíble (requiere OCR)" if not d.get("texto_len") else "Sin NIG ni número de procedimiento identificable"
                L.append(f"| {d['nombre_descriptivo']} | {motivo} |")
            L.append("")
    else:
        L += ["## Documentos procesados", "", "No se recibieron notificaciones judiciales en la ventana analizada.", ""]

    if stats["errores"]:
        L += ["## Incidencias", ""]
        for e in stats["errores"]:
            L.append(f"- {e}")
        L.append("")

    with open(informe_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))

    with open(work_dir / "_clasificacion.json", "w", encoding="utf-8") as f:
        json.dump(clasificados, f, ensure_ascii=False, indent=2, default=str)
    with open(work_dir / "estadisticas.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)

    log.info("Informe generado: %s", informe_path)
    return informe_path


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Pipeline Judicial Diario - ASERGES")
    ap.add_argument("--fecha", help="Día concreto YYYY-MM-DD")
    ap.add_argument("--desde", help="Fecha inicio YYYY-MM-DD")
    ap.add_argument("--hasta", help="Fecha fin YYYY-MM-DD")
    ap.add_argument("--mnprogram", action="store_true", help="Activar subida a MNprogram")
    args = ap.parse_args()

    if args.fecha:
        ini = datetime.strptime(args.fecha, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        fin = ini.replace(hour=23, minute=59, second=59)
    elif args.desde:
        ini = datetime.strptime(args.desde, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        fin = (datetime.strptime(args.hasta, "%Y-%m-%d") if args.hasta else datetime.now()).replace(
            hour=23, minute=59, second=59)
    else:
        ayer = datetime.now() - timedelta(days=1)
        ini = ayer.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = ayer.replace(hour=23, minute=59, second=59, microsecond=0)

    etiqueta = ini.strftime("%Y-%m-%d") if ini.date() == fin.date() else f"{ini:%Y-%m-%d}_al_{fin:%Y-%m-%d}"
    work_dir = TRABAJO_DIR / etiqueta

    print("=" * 70)
    print("  PIPELINE JUDICIAL DIARIO — ASERGES")
    print(f"  Ventana: {ini:%Y-%m-%d %H:%M} → {fin:%Y-%m-%d %H:%M}")
    print("=" * 70)

    pdfs = descargar_pdfs_imap(ini, fin, work_dir)

    log.info("=" * 70)
    log.info("FASE 2: Clasificación judicial (worker v3)")
    log.info("=" * 70)
    clasificados = []
    for info in pdfs:
        try:
            clasificados.append(clasificar_pdf(info))
        except Exception as e:
            log.error("Error clasificando %s: %s", info.get("filename_original"), e)
            stats["errores"].append(f"Clasificación: {e}")

    if clasificados:
        guardar_en_notificaciones(clasificados)
        clasificar_en_usu2(clasificados, cargar_mapeo())

    if args.mnprogram and clasificados:
        subir_a_mnprogram(clasificados)
    elif clasificados:
        log.info("FASE 4 omitida: subida a MNprogram desactivada (usar --mnprogram)")

    informe = generar_informe(clasificados, etiqueta, work_dir)

    print("\n" + "=" * 70)
    print("  RESUMEN")
    print("=" * 70)
    for k in ["correos_revisados", "correos_procuradores", "pdfs_descargados",
              "pdfs_clasificados", "pdfs_vinculables", "pdfs_guardados_notificaciones",
              "pdfs_subidos_mnprogram", "duplicados_omitidos"]:
        print(f"  {k:32s}: {stats[k]}")
    print(f"  {'errores':32s}: {len(stats['errores'])}")
    print("=" * 70)
    print(f"  Informe: {informe}")
    print("=" * 70)


if __name__ == "__main__":
    main()
