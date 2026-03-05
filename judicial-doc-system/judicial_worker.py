# -*- coding: utf-8 -*-
"""
judicial_worker.py
==================
Worker Flask para procesamiento de notificaciones judiciales.
Despacho ASERGES S.L. — Logroño, España.

Funcionalidades:
- Endpoint POST /procesar: recibe PDF + metadatos
- Extracción de NIG, número de procedimiento, tipo de resolución y cliente
  mediante regex + OCR (pdfplumber + pytesseract)
- Búsqueda en SQL Server (Mnprogram) por prioridad:
  NIG exacto → número procedimiento → nombre expediente → nombre cliente
- Opción de consulta vía API SOAP de Mnprogram (GetExpedientes)
- Guardado de PDF en C:\\Escaner\\{año}\\{mes}\\{fecha}_{NIG}_{tipo}_{cliente}.pdf
- Documentos sin expediente: C:\\Escaner\\_Pendientes\\
- Deduplicación por hash SHA-256
- Log completo en judicial_worker.log

Autor: Sistema de automatización ASERGES S.L.
"""

import os
import re
import sys
import json
import hashlib
import logging
import unicodedata
from datetime import datetime
from pathlib import Path
from io import BytesIO

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
WORKER_PORT = int(os.getenv("WORKER_PORT", "8765"))
ESCANER_BASE = os.getenv("ESCANER_BASE", r"C:\Escaner")
PENDIENTES_DIR = os.getenv("PENDIENTES_DIR", r"C:\Escaner\_Pendientes")
LOG_FILE = os.getenv("LOG_FILE", "judicial_worker.log")
HASH_DB_FILE = os.getenv("HASH_DB_FILE", "hashes_procesados.json")

# SQL Server
SQL_SERVER = os.getenv("SQL_SERVER", "localhost")
SQL_DATABASE = os.getenv("SQL_DATABASE", "MnProgram")
SQL_USER = os.getenv("SQL_USER", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
SQL_DRIVER = os.getenv("SQL_DRIVER", "{ODBC Driver 17 for SQL Server}")
SQL_TRUSTED = os.getenv("SQL_TRUSTED_CONNECTION", "no").lower() in ("yes", "true", "1")

# Mnprogram API SOAP (opcional)
MNPROGRAM_API_URL = os.getenv("MNPROGRAM_API_URL", "")
MNPROGRAM_EMPRESA = os.getenv("MNPROGRAM_EMPRESA", "2")
MNPROGRAM_OPERADOR = os.getenv("MNPROGRAM_OPERADOR", "")
MNPROGRAM_PASS_MD5 = os.getenv("MNPROGRAM_PASS_MD5", "")
MNPROGRAM_INSTANCIA = os.getenv("MNPROGRAM_INSTANCIA", "")
MNPROGRAM_TOKEN = os.getenv("MNPROGRAM_TOKEN", "")
USE_SOAP_API = os.getenv("USE_SOAP_API", "false").lower() in ("true", "1", "yes")

# Tesseract
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

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
logger = logging.getLogger("judicial_worker")

# =============================================================================
# APP FLASK
# =============================================================================
app = Flask(__name__)

# =============================================================================
# BASE DE DATOS DE HASHES (deduplicación)
# =============================================================================

def cargar_hashes() -> set:
    """Carga el conjunto de hashes SHA-256 ya procesados."""
    if os.path.exists(HASH_DB_FILE):
        try:
            with open(HASH_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data)
        except Exception as e:
            logger.warning("Error cargando hashes: %s. Se reinicia el registro.", e)
    return set()


def guardar_hash(sha256: str):
    """Añade un hash al registro persistente."""
    hashes = cargar_hashes()
    hashes.add(sha256)
    with open(HASH_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(hashes), f)


def calcular_hash(data: bytes) -> str:
    """Calcula el SHA-256 de un bloque de bytes."""
    return hashlib.sha256(data).hexdigest()


# =============================================================================
# EXTRACCIÓN DE TEXTO DEL PDF
# =============================================================================

def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """
    Extrae texto de un PDF usando pdfplumber.
    Si no obtiene texto suficiente, recurre a OCR con pytesseract.
    """
    import pdfplumber

    texto = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for pagina in pdf.pages:
                t = pagina.extract_text()
                if t:
                    texto += t + "\n"
    except Exception as e:
        logger.warning("Error con pdfplumber: %s", e)

    # Si el texto extraído es muy corto, intentar OCR
    if len(texto.strip()) < 50:
        logger.info("Texto insuficiente con pdfplumber (%d chars). Intentando OCR...", len(texto.strip()))
        texto_ocr = extraer_texto_ocr(pdf_bytes)
        if texto_ocr:
            texto = texto_ocr

    return texto


def extraer_texto_ocr(pdf_bytes: bytes) -> str:
    """Extrae texto mediante OCR (pdf2image + pytesseract)."""
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

        imagenes = convert_from_bytes(pdf_bytes, dpi=300)
        texto = ""
        for img in imagenes:
            t = pytesseract.image_to_string(img, lang="spa")
            texto += t + "\n"
        return texto
    except Exception as e:
        logger.error("Error en OCR: %s", e)
        return ""


# =============================================================================
# EXTRACCIÓN DE METADATOS JUDICIALES (regex)
# =============================================================================

# Patrones de NIG (Número de Identificación General)
# Formato típico: DDDD/DDDD o DD.DD.D-DDDD/DDDD.DD.DDDD
REGEX_NIG = [
    r"N\.?I\.?G\.?\s*[:\-]?\s*(\d{4}[\./]\d{4,}[\./\-]\d+[\./\-]?\d*[\./\-]?\d*)",
    r"N\.?I\.?G\.?\s*[:\-]?\s*(\d{2}\.\d{2}\.\d[\-/]\d{4}/\d{4}\.\d{2}\.\d{4})",
    r"NIG\s*[:\-]?\s*(\S+\d{4}/\d{4}\S*)",
]

# Patrones de número de procedimiento
REGEX_PROCEDIMIENTO = [
    r"(?:Procedimiento|Autos|Rollo|Ejecut(?:oria|ivo)|Concurso|Pieza)\s*(?:n[ºo°]?\.?\s*)?[:\-]?\s*(\d{1,5}[/\-]\d{2,4})",
    r"(?:Proc\.|Proced\.)\s*[:\-]?\s*(\d{1,5}[/\-]\d{2,4})",
    r"(\d{1,5}/\d{2,4})\s*(?:del?\s+)?(?:Juzgado|Audiencia|Tribunal|Sala)",
]

# Patrones de tipo de resolución
REGEX_TIPO_RESOLUCION = [
    r"(AUTO|SENTENCIA|DECRETO|PROVIDENCIA|DILIGENCIA\s+DE\s+ORDENACI[OÓ]N|NOTIFICACI[OÓ]N|EMPLAZAMIENTO|REQUERIMIENTO|CITACI[OÓ]N|OFICIO|EXHORTO|MANDAMIENTO)",
    r"(auto|sentencia|decreto|providencia|diligencia\s+de\s+ordenaci[oó]n|notificaci[oó]n|emplazamiento|requerimiento|citaci[oó]n|oficio|exhorto|mandamiento)",
]

# Patrones para extraer nombres de partes
REGEX_PARTES = [
    r"(?:Demandante|Actor|Solicitante|Concursado|Deudor)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,\.]+?)(?:\n|$|\.)",
    r"(?:Demandado|Ejecutado|Parte contraria)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,\.]+?)(?:\n|$|\.)",
]


def extraer_metadatos(texto: str) -> dict:
    """
    Extrae NIG, número de procedimiento, tipo de resolución y nombres
    de partes del texto de un documento judicial.
    """
    metadatos = {
        "nig": None,
        "num_procedimiento": None,
        "tipo_resolucion": None,
        "partes": [],
    }

    # Extraer NIG
    for patron in REGEX_NIG:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            metadatos["nig"] = match.group(1).strip()
            break

    # Extraer número de procedimiento
    for patron in REGEX_PROCEDIMIENTO:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            metadatos["num_procedimiento"] = match.group(1).strip()
            break

    # Extraer tipo de resolución
    for patron in REGEX_TIPO_RESOLUCION:
        match = re.search(patron, texto)
        if match:
            metadatos["tipo_resolucion"] = match.group(1).strip().upper()
            break

    # Extraer partes
    for patron in REGEX_PARTES:
        matches = re.findall(patron, texto)
        for m in matches:
            nombre = m.strip()
            if len(nombre) > 3 and nombre not in metadatos["partes"]:
                metadatos["partes"].append(nombre)

    return metadatos


# =============================================================================
# BÚSQUEDA EN SQL SERVER (Mnprogram)
# =============================================================================

def obtener_conexion_sql():
    """Crea y devuelve una conexión a SQL Server vía pyodbc."""
    import pyodbc

    if SQL_TRUSTED:
        conn_str = (
            f"DRIVER={SQL_DRIVER};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DATABASE};"
            f"Trusted_Connection=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={SQL_DRIVER};"
            f"SERVER={SQL_SERVER};"
            f"DATABASE={SQL_DATABASE};"
            f"UID={SQL_USER};"
            f"PWD={SQL_PASSWORD};"
        )
    return pyodbc.connect(conn_str)


def buscar_expediente_sql(nig: str = None, num_proc: str = None,
                          nombre_exp: str = None, nombre_cliente: str = None) -> dict:
    """
    Busca un expediente en la base de datos Mnprogram por prioridad:
    1. NIG exacto
    2. Número de procedimiento
    3. Nombre de expediente (parcial)
    4. Nombre de cliente (parcial)

    Retorna dict con datos del expediente o None.
    """
    try:
        conn = obtener_conexion_sql()
        cursor = conn.cursor()

        # Prioridad 1: NIG exacto
        if nig:
            cursor.execute("""
                SELECT TOP 1 e.Numero, e.Anho, e.Codigo, e.Descripcion, e.Tipo, e.Estado
                FROM Expedientes e
                WHERE e.NIG = ? OR e.Codigo LIKE ?
                ORDER BY e.Anho DESC
            """, (nig, f"%{nig}%"))
            row = cursor.fetchone()
            if row:
                logger.info("Expediente encontrado por NIG: %s", nig)
                conn.close()
                return _row_to_dict(row)

        # Prioridad 2: Número de procedimiento
        if num_proc:
            cursor.execute("""
                SELECT TOP 1 e.Numero, e.Anho, e.Codigo, e.Descripcion, e.Tipo, e.Estado
                FROM Expedientes e
                WHERE e.Codigo LIKE ? OR e.Descripcion LIKE ?
                ORDER BY e.Anho DESC
            """, (f"%{num_proc}%", f"%{num_proc}%"))
            row = cursor.fetchone()
            if row:
                logger.info("Expediente encontrado por procedimiento: %s", num_proc)
                conn.close()
                return _row_to_dict(row)

        # Prioridad 3: Nombre de expediente
        if nombre_exp:
            cursor.execute("""
                SELECT TOP 1 e.Numero, e.Anho, e.Codigo, e.Descripcion, e.Tipo, e.Estado
                FROM Expedientes e
                WHERE e.Descripcion LIKE ?
                ORDER BY e.Anho DESC
            """, (f"%{nombre_exp}%",))
            row = cursor.fetchone()
            if row:
                logger.info("Expediente encontrado por nombre expediente: %s", nombre_exp)
                conn.close()
                return _row_to_dict(row)

        # Prioridad 4: Nombre de cliente
        if nombre_cliente:
            cursor.execute("""
                SELECT TOP 1 e.Numero, e.Anho, e.Codigo, e.Descripcion, e.Tipo, e.Estado
                FROM Expedientes e
                INNER JOIN Clientes c ON e.NumeroCliente = c.Numero
                WHERE c.Nombre LIKE ? OR c.RazonSocial LIKE ?
                ORDER BY e.Anho DESC
            """, (f"%{nombre_cliente}%", f"%{nombre_cliente}%"))
            row = cursor.fetchone()
            if row:
                logger.info("Expediente encontrado por cliente: %s", nombre_cliente)
                conn.close()
                return _row_to_dict(row)

        conn.close()
        return None

    except Exception as e:
        logger.error("Error buscando expediente en SQL Server: %s", e)
        return None


def _row_to_dict(row) -> dict:
    """Convierte una fila de pyodbc a diccionario."""
    return {
        "numero": row[0],
        "anho": row[1],
        "codigo": row[2],
        "descripcion": row[3],
        "tipo": row[4],
        "estado": row[5],
    }


# =============================================================================
# BÚSQUEDA VÍA API SOAP MNPROGRAM (opcional)
# =============================================================================

def buscar_expediente_soap(nig: str = None, num_proc: str = None,
                           nombre_exp: str = None) -> dict:
    """
    Consulta expedientes vía API SOAP de Mnprogram (GetExpedientes).
    Filtra localmente por NIG, número de procedimiento o nombre.
    """
    if not USE_SOAP_API or not MNPROGRAM_API_URL:
        return None

    try:
        import requests

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:tem="http://tempuri.org/">
  <soap:Header/>
  <soap:Body>
    <tem:GetExpedientes>
      <tem:instancia>{MNPROGRAM_INSTANCIA}</tem:instancia>
      <tem:numEmpresa>{MNPROGRAM_EMPRESA}</tem:numEmpresa>
      <tem:operador>{MNPROGRAM_OPERADOR}</tem:operador>
      <tem:passMD5>{MNPROGRAM_PASS_MD5}</tem:passMD5>
    </tem:GetExpedientes>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://tempuri.org/GetExpedientes",
        }

        url = f"{MNPROGRAM_API_URL}/API/ClientesService.asmx"
        resp = requests.post(url, data=soap_body.encode("utf-8"), headers=headers, timeout=30)

        if resp.status_code != 200:
            logger.warning("API SOAP respondió con código %d", resp.status_code)
            return None

        # Parsear respuesta XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)

        # Namespace handling
        ns = {
            "soap": "http://schemas.xmlsoap.org/soap/envelope/",
            "tem": "http://tempuri.org/",
        }

        # Buscar expedientes en la respuesta
        expedientes = []
        for exp_elem in root.iter():
            if "numero" in exp_elem.tag.lower() or "expediente" in exp_elem.tag.lower():
                # Intentar parsear como JSON o XML
                pass

        # Parseo simplificado: buscar en texto de respuesta
        texto_resp = resp.text

        # Buscar por NIG
        if nig and nig in texto_resp:
            logger.info("Expediente encontrado en API SOAP por NIG: %s", nig)
            return {"encontrado_via": "soap_nig", "nig": nig}

        # Buscar por número de procedimiento
        if num_proc and num_proc in texto_resp:
            logger.info("Expediente encontrado en API SOAP por procedimiento: %s", num_proc)
            return {"encontrado_via": "soap_procedimiento", "num_procedimiento": num_proc}

        # Buscar por nombre
        if nombre_exp and nombre_exp.lower() in texto_resp.lower():
            logger.info("Expediente encontrado en API SOAP por nombre: %s", nombre_exp)
            return {"encontrado_via": "soap_nombre", "nombre": nombre_exp}

        return None

    except Exception as e:
        logger.error("Error consultando API SOAP Mnprogram: %s", e)
        return None


# =============================================================================
# BÚSQUEDA COMBINADA
# =============================================================================

def buscar_expediente(metadatos: dict) -> dict:
    """
    Busca expediente usando primero API SOAP (si está configurada)
    y luego SQL Server como fallback.
    """
    nig = metadatos.get("nig")
    num_proc = metadatos.get("num_procedimiento")
    partes = metadatos.get("partes", [])
    nombre_cliente = partes[0] if partes else None

    # Intentar API SOAP primero
    if USE_SOAP_API:
        resultado = buscar_expediente_soap(nig, num_proc, nombre_cliente)
        if resultado:
            return resultado

    # Fallback a SQL Server
    resultado = buscar_expediente_sql(
        nig=nig,
        num_proc=num_proc,
        nombre_exp=num_proc,  # Buscar también por descripción
        nombre_cliente=nombre_cliente,
    )
    return resultado


# =============================================================================
# GUARDADO DE ARCHIVOS
# =============================================================================

def sanitizar_nombre(nombre: str) -> str:
    """Elimina caracteres no válidos para nombres de archivo en Windows."""
    if not nombre:
        return "desconocido"
    # Normalizar unicode
    nombre = unicodedata.normalize("NFKD", nombre)
    # Eliminar caracteres no válidos
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nombre)
    nombre = nombre.strip('. ')
    return nombre[:100] if nombre else "desconocido"


def guardar_pdf(pdf_bytes: bytes, metadatos: dict, expediente: dict) -> str:
    """
    Guarda el PDF en la ruta correspondiente.
    Si hay expediente: C:\\Escaner\\{año}\\{mes}\\{fecha}_{NIG}_{tipo}_{cliente}.pdf
    Si no hay expediente: C:\\Escaner\\_Pendientes\\
    """
    ahora = datetime.now()
    fecha_str = ahora.strftime("%Y%m%d")
    anho = ahora.strftime("%Y")
    mes = ahora.strftime("%m")

    nig = sanitizar_nombre(metadatos.get("nig") or "SIN_NIG")
    tipo = sanitizar_nombre(metadatos.get("tipo_resolucion") or "DOC")
    cliente = sanitizar_nombre(
        metadatos.get("partes", [None])[0] if metadatos.get("partes") else "DESCONOCIDO"
    )

    if expediente:
        # Ruta con expediente vinculado
        directorio = os.path.join(ESCANER_BASE, anho, mes)
        nombre_archivo = f"{fecha_str}_{nig}_{tipo}_{cliente}.pdf"
    else:
        # Ruta pendientes
        directorio = PENDIENTES_DIR
        nombre_archivo = f"{fecha_str}_{nig}_{tipo}_{cliente}_PENDIENTE.pdf"

    # Crear directorio si no existe
    os.makedirs(directorio, exist_ok=True)

    ruta_completa = os.path.join(directorio, nombre_archivo)

    # Evitar sobrescritura
    contador = 1
    ruta_base = ruta_completa
    while os.path.exists(ruta_completa):
        nombre_sin_ext = os.path.splitext(ruta_base)[0]
        ruta_completa = f"{nombre_sin_ext}_{contador}.pdf"
        contador += 1

    with open(ruta_completa, "wb") as f:
        f.write(pdf_bytes)

    logger.info("PDF guardado en: %s", ruta_completa)
    return ruta_completa


# =============================================================================
# ENDPOINT PRINCIPAL
# =============================================================================

@app.route("/procesar", methods=["POST"])
def procesar():
    """
    Endpoint POST /procesar
    Recibe un PDF (multipart/form-data o JSON base64) con metadatos opcionales.

    Parámetros form-data:
      - archivo: archivo PDF (file upload)
      - origen: "lexnet" | "correo" | "manual"
      - remitente: email o nombre del remitente (opcional)
      - asunto: asunto del email (opcional)
      - nig_manual: NIG proporcionado manualmente (opcional)
      - procedimiento_manual: número de procedimiento manual (opcional)

    Retorna JSON con resultado del procesamiento.
    """
    try:
        logger.info("=" * 60)
        logger.info("Nueva solicitud de procesamiento recibida")

        # Obtener archivo PDF
        pdf_bytes = None
        origen = "desconocido"
        remitente = ""
        asunto = ""
        nig_manual = ""
        procedimiento_manual = ""

        if "archivo" in request.files:
            archivo = request.files["archivo"]
            pdf_bytes = archivo.read()
            origen = request.form.get("origen", "desconocido")
            remitente = request.form.get("remitente", "")
            asunto = request.form.get("asunto", "")
            nig_manual = request.form.get("nig_manual", "")
            procedimiento_manual = request.form.get("procedimiento_manual", "")
        elif request.is_json:
            data = request.get_json()
            import base64
            pdf_b64 = data.get("archivo_base64", "")
            if pdf_b64:
                pdf_bytes = base64.b64decode(pdf_b64)
            origen = data.get("origen", "desconocido")
            remitente = data.get("remitente", "")
            asunto = data.get("asunto", "")
            nig_manual = data.get("nig_manual", "")
            procedimiento_manual = data.get("procedimiento_manual", "")
        else:
            return jsonify({"error": "No se recibió archivo PDF"}), 400

        if not pdf_bytes:
            return jsonify({"error": "El archivo PDF está vacío"}), 400

        logger.info("Origen: %s | Remitente: %s | Asunto: %s", origen, remitente, asunto)
        logger.info("Tamaño del PDF: %d bytes", len(pdf_bytes))

        # --- DEDUPLICACIÓN ---
        sha256 = calcular_hash(pdf_bytes)
        logger.info("Hash SHA-256: %s", sha256)

        hashes_existentes = cargar_hashes()
        if sha256 in hashes_existentes:
            logger.warning("DUPLICADO detectado. Hash ya procesado: %s", sha256)
            return jsonify({
                "estado": "duplicado",
                "mensaje": "Este documento ya fue procesado anteriormente.",
                "hash": sha256,
            }), 200

        # --- EXTRACCIÓN DE TEXTO ---
        logger.info("Extrayendo texto del PDF...")
        texto = extraer_texto_pdf(pdf_bytes)
        logger.info("Texto extraído: %d caracteres", len(texto))

        # --- EXTRACCIÓN DE METADATOS ---
        logger.info("Extrayendo metadatos judiciales...")
        metadatos = extraer_metadatos(texto)

        # Sobrescribir con datos manuales si se proporcionaron
        if nig_manual:
            metadatos["nig"] = nig_manual
        if procedimiento_manual:
            metadatos["num_procedimiento"] = procedimiento_manual

        logger.info("Metadatos extraídos: %s", json.dumps(metadatos, ensure_ascii=False))

        # --- BÚSQUEDA DE EXPEDIENTE ---
        logger.info("Buscando expediente en base de datos...")
        expediente = buscar_expediente(metadatos)

        if expediente:
            logger.info("Expediente encontrado: %s", json.dumps(expediente, ensure_ascii=False, default=str))
            estado = "vinculado"
        else:
            logger.warning("No se encontró expediente. El documento quedará pendiente de clasificación.")
            estado = "pendiente"

        # --- GUARDAR PDF ---
        ruta_guardado = guardar_pdf(pdf_bytes, metadatos, expediente)

        # --- REGISTRAR HASH ---
        guardar_hash(sha256)

        # --- RESULTADO ---
        resultado = {
            "estado": estado,
            "hash": sha256,
            "origen": origen,
            "remitente": remitente,
            "metadatos": metadatos,
            "expediente": expediente,
            "ruta_archivo": ruta_guardado,
            "timestamp": datetime.now().isoformat(),
        }

        logger.info("Procesamiento completado: %s", estado)
        logger.info("Resultado: %s", json.dumps(resultado, ensure_ascii=False, default=str))

        return jsonify(resultado), 200

    except Exception as e:
        logger.exception("Error procesando documento: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/salud", methods=["GET"])
def salud():
    """Endpoint de health check."""
    return jsonify({
        "estado": "activo",
        "servicio": "judicial_worker",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }), 200


@app.route("/estadisticas", methods=["GET"])
def estadisticas():
    """Endpoint para consultar estadísticas básicas."""
    hashes = cargar_hashes()
    return jsonify({
        "documentos_procesados": len(hashes),
        "timestamp": datetime.now().isoformat(),
    }), 200


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Iniciando Judicial Worker — ASERGES S.L.")
    logger.info("Puerto: %d", WORKER_PORT)
    logger.info("Directorio base: %s", ESCANER_BASE)
    logger.info("Directorio pendientes: %s", PENDIENTES_DIR)
    logger.info("API SOAP habilitada: %s", USE_SOAP_API)
    logger.info("=" * 60)

    # Crear directorios base
    os.makedirs(ESCANER_BASE, exist_ok=True)
    os.makedirs(PENDIENTES_DIR, exist_ok=True)

    app.run(host="0.0.0.0", port=WORKER_PORT, debug=False)
