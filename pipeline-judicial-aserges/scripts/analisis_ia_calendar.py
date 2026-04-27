#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análisis IA de documentos judiciales + Agendado en Google Calendar
==================================================================
Lee los PDFs ya descargados, los analiza con GPT-4.1-mini para obtener:
  - Resumen (1-2 líneas)
  - Prioridad (ALTA / MEDIA / BAJA)
  - Plazos relevantes (solo Autos, Decretos, Sentencias) o fechas concretas
Luego agenda en Google Calendar los plazos/fechas detectados.

Modos de autenticación para Google Calendar:
  --modo-auth mcp   (por defecto) Usa manus-mcp-cli (requiere Manus Cowork)
  --modo-auth adc   Usa Application Default Credentials con Service Account
                    Impersonation (Opción A). Requiere haber ejecutado
                    configurar_adc_windows.bat una vez.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Modo de autenticación: 'mcp' (Manus Cowork) o 'adc' (Service Account Impersonation)
# Se puede sobreescribir con la variable de entorno PIPELINE_AUTH_MODE
AUTH_MODE = os.environ.get("PIPELINE_AUTH_MODE", "mcp")

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
JUDICIAL_DIR = Path("/home/ubuntu/judicial_diario")
NOTIF_DIR = Path("/home/ubuntu/Notificaciones")
RESULTADOS_DIR = Path("/home/ubuntu/analisis_ia_resultados")
RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

# Fecha de hoy para referencia de plazos
HOY = datetime.now()

try:
    import pdfplumber
except ImportError:
    print("Instalando pdfplumber...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pdfplumber"], check=True)
    import pdfplumber

from openai import OpenAI
client = OpenAI()

# ─────────────────────────────────────────────
# PROMPT DE ANÁLISIS JUDICIAL
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un abogado procesalista español experto. Analizas documentos judiciales y produces un análisis estructurado.

REGLAS:
1. RESUMEN: Máximo 2 líneas describiendo qué es el documento y su contenido esencial.
2. PRIORIDAD: 
   - ALTA: Sentencias, Autos que ponen fin al procedimiento, Decretos de archivo, requerimientos con plazo perentorio, señalamientos de vista/juicio.
   - MEDIA: Autos interlocutorios, Diligencias de ordenación con trámite relevante, emplazamientos.
   - BAJA: Notificaciones de mero trámite, acuses de recibo, comunicaciones informativas.
3. PLAZO_RELEVANTE: Solo indicar plazos cuando se trate de:
   - Recursos frente a Autos, Decretos o Sentencias (reposición, apelación, casación)
   - Requerimientos con plazo concreto
   - Fechas de vista, comparecencia o juicio
   - NO incluir plazos ordinarios genéricos de notificaciones de trámite
4. FECHA_CONCRETA: Si hay una fecha específica (vista, comparecencia, juicio, vencimiento), indicarla en formato YYYY-MM-DD.
5. DIAS_PLAZO: Si hay un plazo en días hábiles para recurrir o actuar, indicar el número.

Responde SIEMPRE en JSON con esta estructura exacta:
{
  "resumen": "texto de 1-2 líneas",
  "prioridad": "ALTA|MEDIA|BAJA",
  "tiene_plazo_relevante": true|false,
  "tipo_plazo": "recurso_reposicion|recurso_apelacion|recurso_casacion|requerimiento|vista|comparecencia|juicio|otro|ninguno",
  "descripcion_plazo": "texto breve del plazo o null",
  "fecha_concreta": "YYYY-MM-DD o null",
  "dias_plazo": número o null,
  "tipo_resolucion": "Auto|Decreto|Sentencia|Diligencia|Providencia|Notificacion|Otro",
  "accion_requerida": "texto breve de la acción que debe tomar el abogado o null"
}"""


def extraer_texto_pdf(pdf_path: Path) -> str:
    """Extrae texto de un PDF."""
    texto = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:10]:  # Máximo 10 páginas
                t = page.extract_text()
                if t:
                    texto += t + "\n"
    except Exception as e:
        print(f"  Error extrayendo texto: {e}")
    return texto


def analizar_con_ia(texto_pdf: str, nombre_archivo: str, asunto_correo: str = "") -> dict:
    """Analiza un documento judicial con GPT-4.1-mini."""
    contenido = f"NOMBRE ARCHIVO: {nombre_archivo}\n"
    if asunto_correo:
        contenido += f"ASUNTO CORREO PROCURADOR: {asunto_correo}\n"
    contenido += f"\nCONTENIDO DEL DOCUMENTO:\n{texto_pdf[:6000]}"

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": contenido}
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        resultado = json.loads(response.choices[0].message.content)
        return resultado
    except Exception as e:
        print(f"  Error IA: {e}")
        return {
            "resumen": f"Error en análisis: {e}",
            "prioridad": "MEDIA",
            "tiene_plazo_relevante": False,
            "tipo_plazo": "ninguno",
            "descripcion_plazo": None,
            "fecha_concreta": None,
            "dias_plazo": None,
            "tipo_resolucion": "Otro",
            "accion_requerida": None
        }


def obtener_festivos(anio: int) -> set:
    """Devuelve el conjunto de fechas festivas (nacionales + La Rioja) para un año.
    Conforme al art. 130-131 LEC y art. 182-183 LOPJ:
    - Sábados y domingos son inhábiles
    - Todo el mes de agosto es inhábil
    - Festivos nacionales y autonómicos (La Rioja)
    """
    festivos = set()
    # ── Festivos nacionales fijos ──
    festivos.add(datetime(anio, 1, 1))    # Año Nuevo
    festivos.add(datetime(anio, 1, 6))    # Epifanía
    festivos.add(datetime(anio, 5, 1))    # Día del Trabajo
    festivos.add(datetime(anio, 8, 15))   # Asunción (cae en agosto inhábil)
    festivos.add(datetime(anio, 10, 12))  # Fiesta Nacional
    festivos.add(datetime(anio, 11, 1))   # Todos los Santos
    festivos.add(datetime(anio, 12, 6))   # Constitución
    festivos.add(datetime(anio, 12, 8))   # Inmaculada
    festivos.add(datetime(anio, 12, 25))  # Navidad
    # ── Festivos autonómicos La Rioja (fijos habituales) ──
    festivos.add(datetime(anio, 6, 9))    # Día de La Rioja
    # ── Semana Santa (aproximación; se puede ajustar por año) ──
    # Cálculo de Pascua (algoritmo de Butcher)
    a = anio % 19
    b = anio // 100
    c = anio % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    pascua = datetime(anio, mes, dia)
    # Jueves y Viernes Santo
    festivos.add(pascua - timedelta(days=3))  # Jueves Santo
    festivos.add(pascua - timedelta(days=2))  # Viernes Santo
    # ── Agosto completo inhábil (art. 183.1 LOPJ) ──
    for d_ago in range(1, 32):
        try:
            festivos.add(datetime(anio, 8, d_ago))
        except ValueError:
            pass
    return festivos


def es_dia_habil(fecha: datetime, festivos_cache: dict = {}) -> bool:
    """Determina si una fecha es día hábil procesal conforme a la LEC."""
    anio = fecha.year
    if anio not in festivos_cache:
        festivos_cache[anio] = obtener_festivos(anio)
    # Sábado o domingo
    if fecha.weekday() >= 5:
        return False
    # Festivo o agosto
    fecha_sin_hora = datetime(fecha.year, fecha.month, fecha.day)
    if fecha_sin_hora in festivos_cache[anio]:
        return False
    return True


def calcular_fecha_vencimiento(dias_habiles: int, desde: datetime = None) -> str:
    """Calcula la fecha de vencimiento contando días hábiles procesales (LEC).
    Excluye sábados, domingos, festivos nacionales, autonómicos (La Rioja)
    y todo el mes de agosto (art. 183.1 LOPJ).
    """
    if desde is None:
        desde = HOY
    fecha = desde
    dias_contados = 0
    while dias_contados < dias_habiles:
        fecha += timedelta(days=1)
        if es_dia_habil(fecha):
            dias_contados += 1
    return fecha.strftime("%Y-%m-%d")


def agendar_en_calendar(evento: dict, modo_auth: str = None) -> bool:
    """
    Agenda un evento en Google Calendar.

    Soporta dos modos de autenticación:
      - 'mcp': Usa manus-mcp-cli (requiere Manus Cowork activo).
      - 'adc': Usa Application Default Credentials con Service Account
               Impersonation (Opción A). No depende de Cowork.

    El modo se determina en este orden de precedencia:
      1. Parámetro `modo_auth` de esta función.
      2. Variable de entorno PIPELINE_AUTH_MODE.
      3. Por defecto: 'mcp'.
    """
    modo = (modo_auth or AUTH_MODE or "mcp").lower()
    summary = evento["summary"]
    description = evento.get("description", "")
    start_date = evento["start_date"]  # YYYY-MM-DD

    # ── Modo ADC (Service Account Impersonation) ──────────────────────────────
    if modo == "adc":
        try:
            from auth_adc import crear_evento_calendar, adc_disponible
            if not adc_disponible():
                print("  Calendar ADC ERROR: ADC no configurado. Ejecuta configurar_adc_windows.bat")
                return False
            result = crear_evento_calendar(
                summary=summary,
                description=description,
                start_date=start_date,
            )
            if result:
                print(f"  Calendar ADC OK: {summary} -> {start_date}")
                return True
            else:
                print(f"  Calendar ADC ERROR: la función crear_evento_calendar devolvió None")
                return False
        except Exception as e:
            print(f"  Calendar ADC ERROR: {e}")
            return False

    # ── Modo MCP (Manus Cowork) ───────────────────────────────────────────────
    start_time = f"{start_date}T08:00:00+01:00"
    end_time = f"{start_date}T08:30:00+01:00"

    input_json = json.dumps({
        "events": [{
            "summary": summary,
            "description": description,
            "start_time": start_time,
            "end_time": end_time,
            "reminders": [1440, 120]  # 24h y 2h antes
        }]
    })

    cmd = f"manus-mcp-cli tool call google_calendar_create_events --server google-calendar --input '{input_json}'"

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"  Calendar MCP OK: {summary} -> {start_date}")
            return True
        else:
            print(f"  Calendar MCP ERROR: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"  Calendar MCP ERROR: {e}")
        return False


def procesar_directorio(directorio: Path) -> list:
    """Procesa todos los PDFs de un directorio."""
    resultados = []
    pdfs = sorted(directorio.glob("*.pdf"))
    
    if not pdfs:
        print(f"No se encontraron PDFs en {directorio}")
        return resultados
    
    print(f"\nAnalizando {len(pdfs)} PDFs de {directorio.name}...")
    print("=" * 60)
    
    for i, pdf_path in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] {pdf_path.name}")
        
        # Extraer texto
        texto = extraer_texto_pdf(pdf_path)
        if len(texto.strip()) < 30:
            print("  Texto insuficiente, omitiendo.")
            resultados.append({
                "archivo": pdf_path.name,
                "analisis": {"resumen": "PDF sin texto extraíble", "prioridad": "BAJA", "tiene_plazo_relevante": False}
            })
            continue
        
        # Analizar con IA
        analisis = analizar_con_ia(texto, pdf_path.name)
        print(f"  Resumen: {analisis.get('resumen', 'N/A')}")
        print(f"  Prioridad: {analisis.get('prioridad', 'N/A')}")
        
        resultado = {
            "archivo": pdf_path.name,
            "ruta": str(pdf_path),
            "analisis": analisis
        }
        
        # Determinar si hay que agendar
        if analisis.get("tiene_plazo_relevante"):
            fecha_evento = None
            
            # Si hay fecha concreta
            if analisis.get("fecha_concreta"):
                fecha_evento = analisis["fecha_concreta"]
                print(f"  Fecha concreta: {fecha_evento}")
            
            # Si hay plazo en días, calcular vencimiento
            elif analisis.get("dias_plazo"):
                fecha_evento = calcular_fecha_vencimiento(analisis["dias_plazo"])
                print(f"  Plazo: {analisis['dias_plazo']} días hábiles -> vence {fecha_evento}")
            
            if fecha_evento:
                tipo = analisis.get("tipo_plazo", "plazo")
                parte = pdf_path.stem.split(" - ")[1] if " - " in pdf_path.stem else "Expediente"
                proc = pdf_path.stem.split(" - ")[2] if pdf_path.stem.count(" - ") >= 2 else ""
                
                evento = {
                    "summary": f"JUDICIAL {analisis['prioridad']}: {tipo.upper()} - {parte} {proc}",
                    "description": (
                        f"Documento: {pdf_path.name}\n"
                        f"Resumen: {analisis.get('resumen', '')}\n"
                        f"Tipo resolución: {analisis.get('tipo_resolucion', '')}\n"
                        f"Plazo: {analisis.get('descripcion_plazo', '')}\n"
                        f"Acción requerida: {analisis.get('accion_requerida', '')}"
                    ),
                    "start_date": fecha_evento
                }
                resultado["evento_calendar"] = evento
                resultado["agendado"] = True
            else:
                resultado["agendado"] = False
                print(f"  Plazo relevante pero sin fecha calculable")
        else:
            resultado["agendado"] = False
        
        resultados.append(resultado)
    
    return resultados


def generar_informe_ia(resultados: list, fecha_str: str) -> Path:
    """Genera informe Markdown con los análisis IA."""
    informe_path = RESULTADOS_DIR / f"analisis_ia_{fecha_str}.md"
    
    # Separar por prioridad
    alta = [r for r in resultados if r["analisis"].get("prioridad") == "ALTA"]
    media = [r for r in resultados if r["analisis"].get("prioridad") == "MEDIA"]
    baja = [r for r in resultados if r["analisis"].get("prioridad") == "BAJA"]
    agendados = [r for r in resultados if r.get("agendado")]
    
    lineas = [
        "# Análisis IA de Documentos Judiciales",
        f"**Autor:** Asesores y Abogados ASerges SL",
        f"**Fecha de análisis:** {HOY.strftime('%d/%m/%Y %H:%M')}",
        f"**Periodo:** {fecha_str}",
        f"**Total documentos:** {len(resultados)}",
        "",
        "## Resumen por Prioridad",
        "",
        "| Prioridad | Cantidad |",
        "|:---|---:|",
        f"| ALTA | {len(alta)} |",
        f"| MEDIA | {len(media)} |",
        f"| BAJA | {len(baja)} |",
        f"| **Agendados en Calendar** | **{len(agendados)}** |",
        "",
    ]
    
    # Documentos de prioridad ALTA
    if alta:
        lineas.append("## Prioridad ALTA")
        lineas.append("")
        for r in alta:
            a = r["analisis"]
            lineas.append(f"### {r['archivo']}")
            lineas.append(f"**Resumen:** {a.get('resumen', 'N/A')}")
            lineas.append(f"**Tipo resolución:** {a.get('tipo_resolucion', 'N/A')}")
            if a.get("tiene_plazo_relevante"):
                lineas.append(f"**Plazo:** {a.get('descripcion_plazo', 'N/A')}")
                if a.get("fecha_concreta"):
                    lineas.append(f"**Fecha:** {a['fecha_concreta']}")
                if a.get("dias_plazo"):
                    lineas.append(f"**Días hábiles:** {a['dias_plazo']}")
            if a.get("accion_requerida"):
                lineas.append(f"**Acción requerida:** {a['accion_requerida']}")
            if r.get("agendado"):
                ev = r["evento_calendar"]
                lineas.append(f"**Agendado en Calendar:** {ev['start_date']} a las 08:00")
            lineas.append("")
    
    # Documentos de prioridad MEDIA
    if media:
        lineas.append("## Prioridad MEDIA")
        lineas.append("")
        lineas.append("| Archivo | Resumen | Tipo | Plazo |")
        lineas.append("|:---|:---|:---|:---|")
        for r in media:
            a = r["analisis"]
            plazo = a.get("descripcion_plazo", "-") or "-"
            lineas.append(f"| {r['archivo'][:40]} | {a.get('resumen','N/A')[:60]} | {a.get('tipo_resolucion','N/A')} | {plazo[:30]} |")
        lineas.append("")
    
    # Documentos de prioridad BAJA
    if baja:
        lineas.append("## Prioridad BAJA")
        lineas.append("")
        lineas.append("| Archivo | Resumen |")
        lineas.append("|:---|:---|")
        for r in baja:
            a = r["analisis"]
            lineas.append(f"| {r['archivo'][:40]} | {a.get('resumen','N/A')[:80]} |")
        lineas.append("")
    
    # Eventos agendados
    if agendados:
        lineas.append("## Eventos Agendados en Google Calendar")
        lineas.append("")
        lineas.append("| Fecha | Evento | Documento |")
        lineas.append("|:---|:---|:---|")
        for r in agendados:
            ev = r["evento_calendar"]
            lineas.append(f"| {ev['start_date']} | {ev['summary'][:50]} | {r['archivo'][:40]} |")
        lineas.append("")
    
    with open(informe_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
    
    # Guardar JSON completo
    json_path = RESULTADOS_DIR / f"analisis_ia_{fecha_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
    
    return informe_path


def main():
    """Punto de entrada principal."""
    import argparse
    parser = argparse.ArgumentParser(description="Análisis IA de documentos judiciales")
    parser.add_argument("--dir", type=str, help="Directorio con PDFs a analizar")
    parser.add_argument("--fecha", type=str, default="", help="Etiqueta de fecha para el informe")
    parser.add_argument("--agendar", action="store_true", default=True, help="Agendar plazos en Google Calendar")
    parser.add_argument("--no-agendar", action="store_true", help="No agendar en Calendar")
    parser.add_argument(
        "--modo-auth",
        choices=["mcp", "adc"],
        default=os.environ.get("PIPELINE_AUTH_MODE", "mcp"),
        help="Modo de autenticación para Google Calendar: 'mcp' (Manus Cowork) o 'adc' (Service Account Impersonation). "
             "Por defecto: valor de PIPELINE_AUTH_MODE o 'mcp'."
    )
    args = parser.parse_args()
    
    # Determinar directorio
    if args.dir:
        directorio = Path(args.dir)
    else:
        # Buscar el directorio más reciente de Notificaciones
        dirs = sorted(NOTIF_DIR.glob("*"), key=lambda d: d.name, reverse=True)
        if dirs:
            directorio = dirs[0]
        else:
            print("No se encontraron directorios de notificaciones.")
            sys.exit(1)
    
    fecha_str = args.fecha or directorio.name
    agendar = not args.no_agendar
    modo_auth = args.modo_auth
    
    print("="*60)
    print("  ANÁLISIS IA DE DOCUMENTOS JUDICIALES - ASERGES")
    print(f"  Directorio: {directorio}")
    print(f"  Agendar Calendar: {'Sí' if agendar else 'No'}")
    print(f"  Modo autenticación: {modo_auth.upper()}")
    print("="*60)
    
    # Analizar PDFs
    resultados = procesar_directorio(directorio)
    
    # Agendar en Calendar
    if agendar:
        agendables = [r for r in resultados if r.get("agendado") and "evento_calendar" in r]
        if agendables:
            print(f"\n{'='*60}")
            print(f"Agendando {len(agendables)} eventos en Google Calendar (modo: {modo_auth.upper()})...")
            for r in agendables:
                ok = agendar_en_calendar(r["evento_calendar"], modo_auth=modo_auth)
                r["calendar_ok"] = ok
        else:
            print("\nNo hay plazos relevantes que agendar.")
    
    # Generar informe
    informe = generar_informe_ia(resultados, fecha_str)
    
    # Resumen
    alta = sum(1 for r in resultados if r["analisis"].get("prioridad") == "ALTA")
    agendados = sum(1 for r in resultados if r.get("calendar_ok"))
    
    print(f"\n{'='*60}")
    print("  RESUMEN ANÁLISIS IA")
    print(f"{'='*60}")
    print(f"  Documentos analizados:  {len(resultados)}")
    print(f"  Prioridad ALTA:         {alta}")
    print(f"  Agendados en Calendar:  {agendados}")
    print(f"  Informe: {informe}")
    print(f"{'='*60}")
    
    return resultados


if __name__ == "__main__":
    main()
