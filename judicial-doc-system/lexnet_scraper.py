# -*- coding: utf-8 -*-
"""
lexnet_scraper.py
=================
Scraper automatizado de LexNET para el despacho ASERGES S.L.

Funcionalidades:
- Usa Playwright con perfil de Chrome existente (certificado digital instalado)
- Login en https://lexnet.justicia.es usando certificado digital
- Detecta notificaciones no leídas en el buzón
- Descarga PDF adjunto de cada notificación
- Extrae metadatos de la interfaz (NIG, órgano, tipo)
- Envía cada documento al worker Python vía POST http://localhost:8765/procesar
- Marca notificación como leída tras procesarla
- Diseñado para ejecutarse cada 30 minutos como tarea programada

Autor: Sistema de automatización ASERGES S.L.
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
WORKER_URL = os.getenv("WORKER_URL", "http://localhost:8765/procesar")
CHROME_USER_DATA_DIR = os.getenv(
    "CHROME_USER_DATA_DIR",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
)
CHROME_PROFILE = os.getenv("CHROME_PROFILE", "Default")
CHROME_EXECUTABLE = os.getenv(
    "CHROME_EXECUTABLE",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
LEXNET_URL = os.getenv("LEXNET_URL", "https://lexnet.justicia.es")
DOWNLOAD_DIR = os.getenv("LEXNET_DOWNLOAD_DIR", r"C:\Escaner\_LexNET_Temp")
LOG_FILE = os.getenv("LEXNET_LOG_FILE", "lexnet_scraper.log")
MAX_NOTIFICACIONES = int(os.getenv("LEXNET_MAX_NOTIFICACIONES", "50"))
TIMEOUT_PAGINA = int(os.getenv("LEXNET_TIMEOUT_PAGINA", "60000"))  # ms
TIMEOUT_DESCARGA = int(os.getenv("LEXNET_TIMEOUT_DESCARGA", "30000"))  # ms
PAUSA_ENTRE_NOTIFICACIONES = int(os.getenv("LEXNET_PAUSA_SEGUNDOS", "5"))

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
logger = logging.getLogger("lexnet_scraper")


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def enviar_al_worker(pdf_path: str, metadatos: dict) -> dict:
    """
    Envía un PDF descargado al worker Flask para su procesamiento.
    """
    try:
        with open(pdf_path, "rb") as f:
            files = {"archivo": (os.path.basename(pdf_path), f, "application/pdf")}
            data = {
                "origen": "lexnet",
                "remitente": metadatos.get("organo", "LexNET"),
                "asunto": metadatos.get("tipo_notificacion", "Notificación LexNET"),
                "nig_manual": metadatos.get("nig", ""),
                "procedimiento_manual": metadatos.get("num_procedimiento", ""),
            }
            response = requests.post(WORKER_URL, files=files, data=data, timeout=60)
            response.raise_for_status()
            resultado = response.json()
            logger.info("Worker respondió: %s", json.dumps(resultado, ensure_ascii=False, default=str))
            return resultado
    except requests.exceptions.ConnectionError:
        logger.error("No se pudo conectar con el worker en %s. ¿Está en ejecución?", WORKER_URL)
        return {"error": "Worker no disponible"}
    except Exception as e:
        logger.error("Error enviando al worker: %s", e)
        return {"error": str(e)}


def verificar_worker() -> bool:
    """Verifica que el worker Flask esté activo."""
    try:
        health_url = WORKER_URL.replace("/procesar", "/salud")
        resp = requests.get(health_url, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# =============================================================================
# SCRAPER PRINCIPAL
# =============================================================================

def ejecutar_scraper():
    """
    Función principal del scraper LexNET.
    Usa Playwright con el perfil de Chrome existente para acceder a LexNET
    con certificado digital.
    """
    from playwright.sync_api import sync_playwright

    logger.info("=" * 60)
    logger.info("Iniciando scraper LexNET — ASERGES S.L.")
    logger.info("Fecha/hora: %s", datetime.now().isoformat())
    logger.info("=" * 60)

    # Verificar worker
    if not verificar_worker():
        logger.error("El worker no está disponible en %s. Abortando.", WORKER_URL)
        logger.error("Asegúrese de que judicial_worker.py está en ejecución.")
        return

    # Crear directorio de descargas temporal
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    notificaciones_procesadas = 0
    errores = 0

    with sync_playwright() as p:
        try:
            # Lanzar Chrome con el perfil existente (certificado digital)
            # IMPORTANTE: Chrome debe estar cerrado antes de ejecutar el scraper
            logger.info("Lanzando navegador con perfil de Chrome existente...")
            logger.info("User Data Dir: %s", CHROME_USER_DATA_DIR)
            logger.info("Perfil: %s", CHROME_PROFILE)

            context = p.chromium.launch_persistent_context(
                user_data_dir=CHROME_USER_DATA_DIR,
                channel="chrome",
                executable_path=CHROME_EXECUTABLE,
                headless=False,  # Necesario para certificado digital
                accept_downloads=True,
                args=[
                    f"--profile-directory={CHROME_PROFILE}",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                ignore_default_args=["--enable-automation"],
                downloads_path=DOWNLOAD_DIR,
            )

            page = context.pages[0] if context.pages else context.new_page()

            # --- ACCEDER A LEXNET ---
            logger.info("Navegando a LexNET: %s", LEXNET_URL)
            page.goto(LEXNET_URL, wait_until="networkidle", timeout=TIMEOUT_PAGINA)
            time.sleep(3)

            # --- GESTIONAR LOGIN CON CERTIFICADO ---
            # LexNET puede presentar diferentes pantallas de login
            # El certificado digital debería seleccionarse automáticamente
            # si está configurado en Chrome

            # Verificar si estamos en la página de login
            if _esta_en_login(page):
                logger.info("Página de login detectada. Intentando acceso con certificado...")
                _realizar_login_certificado(page)
                time.sleep(5)

            # Verificar acceso exitoso
            if not _esta_autenticado(page):
                logger.error("No se pudo autenticar en LexNET. Verifique el certificado digital.")
                context.close()
                return

            logger.info("Autenticación exitosa en LexNET.")

            # --- NAVEGAR AL BUZÓN DE NOTIFICACIONES ---
            logger.info("Navegando al buzón de notificaciones...")
            _navegar_buzon(page)
            time.sleep(3)

            # --- OBTENER NOTIFICACIONES NO LEÍDAS ---
            logger.info("Buscando notificaciones no leídas...")
            notificaciones = _obtener_notificaciones_no_leidas(page)
            logger.info("Notificaciones no leídas encontradas: %d", len(notificaciones))

            if not notificaciones:
                logger.info("No hay notificaciones nuevas. Finalizando.")
                context.close()
                return

            # --- PROCESAR CADA NOTIFICACIÓN ---
            for i, notif in enumerate(notificaciones[:MAX_NOTIFICACIONES]):
                try:
                    logger.info("-" * 40)
                    logger.info("Procesando notificación %d/%d", i + 1, len(notificaciones))

                    # Abrir la notificación
                    _abrir_notificacion(page, notif)
                    time.sleep(2)

                    # Extraer metadatos de la interfaz
                    metadatos = _extraer_metadatos_notificacion(page)
                    logger.info("Metadatos LexNET: %s", json.dumps(metadatos, ensure_ascii=False))

                    # Descargar PDF adjunto
                    pdf_path = _descargar_pdf_adjunto(page)

                    if pdf_path and os.path.exists(pdf_path):
                        logger.info("PDF descargado: %s", pdf_path)

                        # Enviar al worker
                        resultado = enviar_al_worker(pdf_path, metadatos)

                        if "error" not in resultado:
                            # Marcar como leída
                            _marcar_como_leida(page, notif)
                            notificaciones_procesadas += 1
                            logger.info("Notificación procesada correctamente.")
                        else:
                            errores += 1
                            logger.warning("Error del worker: %s", resultado.get("error"))

                        # Limpiar archivo temporal
                        try:
                            os.remove(pdf_path)
                        except Exception:
                            pass
                    else:
                        logger.warning("No se pudo descargar el PDF adjunto.")
                        errores += 1

                    # Volver al buzón
                    _volver_al_buzon(page)
                    time.sleep(PAUSA_ENTRE_NOTIFICACIONES)

                except Exception as e:
                    logger.error("Error procesando notificación %d: %s", i + 1, e)
                    errores += 1
                    try:
                        _volver_al_buzon(page)
                    except Exception:
                        pass
                    time.sleep(PAUSA_ENTRE_NOTIFICACIONES)

            context.close()

        except Exception as e:
            logger.exception("Error fatal en el scraper: %s", e)

    # --- RESUMEN ---
    logger.info("=" * 60)
    logger.info("RESUMEN DE EJECUCIÓN")
    logger.info("Notificaciones procesadas: %d", notificaciones_procesadas)
    logger.info("Errores: %d", errores)
    logger.info("Fecha/hora finalización: %s", datetime.now().isoformat())
    logger.info("=" * 60)


# =============================================================================
# FUNCIONES DE INTERACCIÓN CON LEXNET
# =============================================================================

def _esta_en_login(page) -> bool:
    """Detecta si estamos en la página de login de LexNET."""
    try:
        # LexNET típicamente muestra un botón de acceso con certificado
        selectores_login = [
            "text=Acceso con certificado",
            "text=Certificado electrónico",
            "text=Acceder",
            "#loginCertificado",
            "a[href*='certificado']",
            "button:has-text('Certificado')",
        ]
        for selector in selectores_login:
            if page.query_selector(selector):
                return True
        # También verificar por URL
        if "login" in page.url.lower() or "acceso" in page.url.lower():
            return True
        return False
    except Exception:
        return False


def _realizar_login_certificado(page):
    """
    Intenta realizar el login con certificado digital.
    El certificado debe estar instalado en el perfil de Chrome.
    """
    try:
        # Buscar y hacer clic en el botón de acceso con certificado
        selectores_boton = [
            "#loginCertificado",
            "a:has-text('Acceso con certificado')",
            "button:has-text('Certificado')",
            "a:has-text('Certificado electrónico')",
            "a[href*='certificado']",
            "#accesoCertificado",
            ".btn-certificado",
        ]

        for selector in selectores_boton:
            elemento = page.query_selector(selector)
            if elemento:
                logger.info("Botón de certificado encontrado: %s", selector)
                elemento.click()
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)
                return

        # Si no se encuentra botón específico, buscar cualquier enlace de acceso
        enlaces = page.query_selector_all("a")
        for enlace in enlaces:
            texto = enlace.inner_text().lower()
            if "certificado" in texto or "acceder" in texto:
                logger.info("Enlace de acceso encontrado: %s", texto)
                enlace.click()
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)
                return

        logger.warning("No se encontró botón de acceso con certificado.")

    except Exception as e:
        logger.error("Error en login con certificado: %s", e)


def _esta_autenticado(page) -> bool:
    """Verifica si el usuario está autenticado en LexNET."""
    try:
        # Indicadores de sesión activa
        selectores_auth = [
            "text=Buzón",
            "text=Notificaciones",
            "text=Cerrar sesión",
            "text=Mi cuenta",
            "#menuPrincipal",
            ".menu-lateral",
            "nav",
        ]
        for selector in selectores_auth:
            if page.query_selector(selector):
                return True

        # Verificar que no estamos en login
        if "login" not in page.url.lower():
            return True

        return False
    except Exception:
        return False


def _navegar_buzon(page):
    """Navega al buzón de notificaciones recibidas."""
    try:
        # Intentar diferentes selectores para el buzón
        selectores_buzon = [
            "a:has-text('Buzón')",
            "a:has-text('Notificaciones recibidas')",
            "a:has-text('Bandeja de entrada')",
            "a[href*='buzon']",
            "a[href*='notificaciones']",
            "#menuBuzon",
            ".menu-buzon",
        ]

        for selector in selectores_buzon:
            elemento = page.query_selector(selector)
            if elemento:
                logger.info("Enlace al buzón encontrado: %s", selector)
                elemento.click()
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)
                return

        # Intentar navegación directa
        page.goto(f"{LEXNET_URL}/lexnet/pages/buzon/listado.seam", timeout=TIMEOUT_PAGINA)
        page.wait_for_load_state("networkidle")

    except Exception as e:
        logger.error("Error navegando al buzón: %s", e)


def _obtener_notificaciones_no_leidas(page) -> list:
    """
    Obtiene la lista de notificaciones no leídas del buzón.
    Retorna una lista de elementos (locators) de notificaciones.
    """
    notificaciones = []
    try:
        # Buscar filas de notificaciones no leídas
        selectores_no_leidas = [
            "tr.no-leida",
            "tr.unread",
            "tr[class*='noLeida']",
            "tr[class*='nueva']",
            ".notificacion-nueva",
            "tr.bold",
        ]

        for selector in selectores_no_leidas:
            elementos = page.query_selector_all(selector)
            if elementos:
                logger.info("Notificaciones no leídas encontradas con selector: %s", selector)
                notificaciones = elementos
                break

        # Si no se encontraron con selectores específicos, buscar en tabla general
        if not notificaciones:
            # Buscar todas las filas de la tabla de notificaciones
            filas = page.query_selector_all("table tbody tr")
            for fila in filas:
                # Verificar si tiene indicador de no leída (negrita, icono, clase)
                clase = fila.get_attribute("class") or ""
                estilo = fila.get_attribute("style") or ""
                texto = fila.inner_text()

                if ("bold" in clase.lower() or
                    "nueva" in clase.lower() or
                    "no-leida" in clase.lower() or
                    "font-weight: bold" in estilo.lower() or
                    "●" in texto):
                    notificaciones.append(fila)

        return notificaciones

    except Exception as e:
        logger.error("Error obteniendo notificaciones: %s", e)
        return []


def _abrir_notificacion(page, notif_element):
    """Abre una notificación haciendo clic en ella."""
    try:
        # Intentar hacer clic en el enlace dentro de la fila
        enlace = notif_element.query_selector("a")
        if enlace:
            enlace.click()
        else:
            notif_element.click()
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)
    except Exception as e:
        logger.error("Error abriendo notificación: %s", e)


def _extraer_metadatos_notificacion(page) -> dict:
    """
    Extrae metadatos de la interfaz de LexNET para la notificación abierta.
    """
    metadatos = {
        "nig": "",
        "organo": "",
        "tipo_notificacion": "",
        "num_procedimiento": "",
        "fecha_notificacion": "",
        "asunto": "",
    }

    try:
        # Mapeo de etiquetas a campos
        mapeo_campos = {
            "nig": ["NIG", "N.I.G.", "Número Identificación General"],
            "organo": ["Órgano", "Organo", "Juzgado", "Tribunal", "Órgano judicial"],
            "tipo_notificacion": ["Tipo", "Tipo de resolución", "Tipo resolución", "Clase"],
            "num_procedimiento": ["Procedimiento", "Nº Procedimiento", "Número procedimiento", "Autos"],
            "fecha_notificacion": ["Fecha", "Fecha notificación", "Fecha de notificación"],
            "asunto": ["Asunto", "Descripción", "Materia"],
        }

        # Estrategia 1: Buscar pares etiqueta-valor en la página
        texto_pagina = page.inner_text("body")
        lineas = texto_pagina.split("\n")

        for campo, etiquetas in mapeo_campos.items():
            for etiqueta in etiquetas:
                for linea in lineas:
                    if etiqueta.lower() in linea.lower():
                        # Extraer valor después de la etiqueta
                        partes = linea.split(":", 1)
                        if len(partes) > 1:
                            metadatos[campo] = partes[1].strip()
                            break
                        # También intentar con tabulación
                        partes = linea.split("\t", 1)
                        if len(partes) > 1:
                            metadatos[campo] = partes[1].strip()
                            break
                if metadatos[campo]:
                    break

        # Estrategia 2: Buscar en elementos específicos de la interfaz
        selectores_detalle = [
            ("nig", "#nig, .nig, [data-field='nig']"),
            ("organo", "#organo, .organo, [data-field='organo']"),
            ("tipo_notificacion", "#tipo, .tipo, [data-field='tipo']"),
            ("num_procedimiento", "#procedimiento, .procedimiento, [data-field='procedimiento']"),
        ]

        for campo, selector in selectores_detalle:
            if not metadatos[campo]:
                elemento = page.query_selector(selector)
                if elemento:
                    metadatos[campo] = elemento.inner_text().strip()

    except Exception as e:
        logger.error("Error extrayendo metadatos de la interfaz: %s", e)

    return metadatos


def _descargar_pdf_adjunto(page) -> str:
    """
    Descarga el PDF adjunto de la notificación abierta.
    Retorna la ruta del archivo descargado o None.
    """
    try:
        # Buscar enlace de descarga del documento
        selectores_descarga = [
            "a[href*='.pdf']",
            "a:has-text('Descargar')",
            "a:has-text('Documento')",
            "a:has-text('Adjunto')",
            "a:has-text('Ver documento')",
            "a:has-text('Descargar documento')",
            "button:has-text('Descargar')",
            ".descarga-documento a",
            ".adjunto a",
            "a[href*='download']",
            "a[href*='descarga']",
            "a[title*='Descargar']",
            "a[title*='documento']",
        ]

        for selector in selectores_descarga:
            elemento = page.query_selector(selector)
            if elemento:
                logger.info("Enlace de descarga encontrado: %s", selector)

                # Iniciar descarga
                with page.expect_download(timeout=TIMEOUT_DESCARGA) as download_info:
                    elemento.click()

                download = download_info.value
                # Guardar en directorio temporal
                nombre_archivo = download.suggested_filename or f"lexnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                ruta_destino = os.path.join(DOWNLOAD_DIR, nombre_archivo)
                download.save_as(ruta_destino)

                if os.path.exists(ruta_destino) and os.path.getsize(ruta_destino) > 0:
                    return ruta_destino

        # Estrategia alternativa: buscar iframes con el documento
        iframes = page.query_selector_all("iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if ".pdf" in src.lower() or "document" in src.lower():
                logger.info("PDF encontrado en iframe: %s", src)
                # Descargar directamente
                import urllib.request
                ruta_destino = os.path.join(
                    DOWNLOAD_DIR,
                    f"lexnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                )
                urllib.request.urlretrieve(src, ruta_destino)
                if os.path.exists(ruta_destino):
                    return ruta_destino

        logger.warning("No se encontró PDF adjunto para descargar.")
        return None

    except Exception as e:
        logger.error("Error descargando PDF: %s", e)
        return None


def _marcar_como_leida(page, notif_element):
    """Marca la notificación como leída (generalmente se marca al abrirla)."""
    try:
        # En LexNET, abrir la notificación generalmente la marca como leída
        # Pero si hay un botón explícito, lo usamos
        selectores_marcar = [
            "button:has-text('Marcar como leída')",
            "a:has-text('Marcar como leída')",
            "button:has-text('Aceptar')",
            "#btnAceptar",
            ".btn-aceptar",
        ]

        for selector in selectores_marcar:
            elemento = page.query_selector(selector)
            if elemento:
                logger.info("Marcando notificación como leída: %s", selector)
                elemento.click()
                time.sleep(1)
                return

        logger.info("La notificación se marcó como leída al abrirla (comportamiento por defecto).")

    except Exception as e:
        logger.error("Error marcando como leída: %s", e)


def _volver_al_buzon(page):
    """Navega de vuelta al buzón de notificaciones."""
    try:
        # Intentar botón de volver
        selectores_volver = [
            "a:has-text('Volver')",
            "a:has-text('Buzón')",
            "button:has-text('Volver')",
            ".btn-volver",
            "a[href*='buzon']",
        ]

        for selector in selectores_volver:
            elemento = page.query_selector(selector)
            if elemento:
                elemento.click()
                page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)
                return

        # Fallback: navegar directamente
        page.go_back()
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA)

    except Exception as e:
        logger.error("Error volviendo al buzón: %s", e)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    logger.info("Scraper LexNET iniciado.")
    try:
        ejecutar_scraper()
    except KeyboardInterrupt:
        logger.info("Scraper detenido por el usuario.")
    except Exception as e:
        logger.exception("Error fatal: %s", e)
    finally:
        logger.info("Scraper LexNET finalizado.")
