# -*- coding: utf-8 -*-
"""
generar_indice.py — Catálogo inteligente de la carpeta public/ (Firebase Hosting)

Correr desde la raíz del repo (donde está la carpeta public/):

    python generar_indice.py                 # escanea, captura miniaturas nuevas/cambiadas y genera index.html
    python generar_indice.py --sin-capturas  # no toma screenshots (usa portadas generadas)
    python generar_indice.py --forzar        # vuelve a capturar todas las miniaturas

Qué hace solo, sin configurar nada:
  * Título, descripción (meta o primer párrafo), secciones (h1-h3) y palabras.
  * Fechas: creación y última actualización desde git (o del sistema de archivos si no hay git),
    y la "fecha de datos/corte" si el HTML la menciona ("Generado el 29/08/2026", "corte", etc.).
  * Categoría, tipo (Mapa, Tablero, Informe, Herramienta, Guía, Menú), territorio (departamentos),
    años y tecnología (ArcGIS JS, Leaflet, D3, Chart.js...).
  * Duplicados y versiones: contenido idéntico, mismo título, mismo nombre base (v2, v3, final...)
    y similitud de contenido. Marca cuál es la versión vigente (la más reciente).
  * Miniaturas reales con Playwright (si está instalado), en caché por hash: solo recaptura lo que cambió.
      pip install playwright
      python -m playwright install chromium

Opcional (para afinar a mano, no es obligatorio):
  * Etiquetas dentro de cualquier HTML:
      <meta name="description" content="...">
      <meta name="catalogo:categoria" content="Logística y simulacros">
      <meta name="catalogo:tags" content="simulacro, transmisión">
      <meta name="catalogo:estado" content="obsoleto">        (vigente | borrador | obsoleto)
      <meta name="catalogo:ocultar" content="si">
  * Archivo catalogo.config.json en la raíz del repo con overrides por archivo (ver CONFIG_EJEMPLO).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote

# ───────────────────────────── Configuración ─────────────────────────────
CARPETA_PUBLIC = "public"
ARCHIVO_SALIDA = os.path.join(CARPETA_PUBLIC, "index.html")
ARCHIVO_JSON = os.path.join(CARPETA_PUBLIC, "catalogo.json")
CARPETA_MINIS = os.path.join(CARPETA_PUBLIC, "_miniaturas")
ARCHIVO_CONFIG = "catalogo.config.json"
ARCHIVO_LOG = "generar_indice.log"
DOMINIO_BASE = "https://dashboard-datos.web.app"
TITULO_SITIO = "Análisis y Datos"
SUBTITULO_SITIO = "Repositorio de tableros, mapas e informes"

ARCHIVOS_IGNORADOS = {"index.html", "404.html"}
CARPETAS_IGNORADAS = {"_miniaturas", "node_modules", ".git", "assets", "lib", "vendor"}
UMBRAL_SIMILITUD = 0.55      # Jaccard de contenido para considerar "posible duplicado"
ESPERA_CAPTURA_MS = 3500     # tiempo extra para que carguen mapas/gráficos antes del screenshot

CONFIG_EJEMPLO = {
    "archivos": {
        "mapa_simulacro2.html": {"estado": "obsoleto", "nota": "Reemplazado por panel_personal_v3"},
        "pisa2025_el_salvador.html": {"categoria": "Educación", "tags": ["PISA", "MINED"]},
    },
    "ocultar": ["borrador_*.html"],
    "no_duplicados": [["panel_reparto_v3.html", "panel_personal_v3.html"]],
}

# Categorías: nombre, color, palabras clave (sin tildes, minúsculas). El orden desempata.
# Las palabras se comparan sin tildes y aceptan plural (centro/centros); se muestran tal cual como etiqueta.
CATEGORIAS = [
    ("Logística y simulacros", "#0e7490", ["simulacro", "transmisión", "reparto", "despacho", "ruta", "sede",
                                            "vehículo", "material electoral", "asignación de personal", "COT"]),
    ("Padrón y centros", "#7c3aed", ["padrón", "JRV", "junta receptora", "reasignación", "centro de votación",
                                     "inconsistencia", "densidad", "electores", "DUI"]),
    ("Análisis electoral", "#b45309", ["escrutinio", "conducta", "voto", "coalición", "riesgo", "D'Hondt",
                                       "candidato", "asamblea", "participación", "polarización",
                                       "ingeniería electoral", "legislativa", "atlas electoral", "electoral"]),
    ("Estructura territorial", "#be123c", ["estructura", "actividades", "panel de carga", "referente",
                                           "cuerpo electoral", "zona electoral", "paneles de gestión", "cobertura"]),
    ("Encuestas y opinión", "#15803d", ["encuesta", "sondeo", "opinión", "Survey123", "levantamiento"]),
    ("Calendario y planificación", "#4338ca", ["calendario", "cronograma", "PLAGEL", "planificación", "hito"]),
    ("Voto en el exterior", "#0369a1", ["exterior", "diáspora", "consulado", "Cancillería"]),
    ("Educación", "#a16207", ["PISA", "educación", "escuela", "estudiantes", "MINED", "docente"]),
    ("IA y catastro", "#475569", ["transformer", "attention", "catastro", "inteligencia artificial", "laboratorio"]),
]
CATEGORIA_DEFECTO = ("Otros", "#64748b")

DEPARTAMENTOS = ["Ahuachapán", "Santa Ana", "Sonsonate", "Chalatenango", "La Libertad", "San Salvador",
                 "Cuscatlán", "La Paz", "Cabañas", "San Vicente", "Usulután", "San Miguel", "Morazán", "La Unión"]

TECNOLOGIAS = [
    ("ArcGIS JS", [r"js\.arcgis\.com"]),
    ("Leaflet", [r"leaflet(\.min)?\.js", r"unpkg\.com/leaflet", r"\bL\.map\("]),
    ("MapLibre", [r"maplibre"]),
    ("Mapbox", [r"mapbox-gl"]),
    ("D3", [r"d3(\.v\d)?(\.min)?\.js", r"/d3@", r"cdn\.jsdelivr\.net/npm/d3"]),
    ("Chart.js", [r"chart(\.umd)?(\.min)?\.js", r"npm/chart\.js"]),
    ("ECharts", [r"echarts"]),
    ("Plotly", [r"plotly"]),
    ("Tailwind", [r"cdn\.tailwindcss\.com"]),
]

PALABRAS_VACIAS = set("""de la el los las y en a que por para con del al un una se su sus es o lo como mas más
no si sí este esta estos estas ese esa cada entre sobre sin desde hasta ya pero cuando donde cual cuál
""".split())


# ───────────────────────────── Utilidades ─────────────────────────────
def log(msg):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linea)
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto.lower()).strip()


def limpiar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def slug(ruta):
    return re.sub(r"[^a-zA-Z0-9]+", "_", os.path.splitext(ruta)[0]).strip("_").lower()


def nombre_base(ruta):
    """Nombre sin versiones/sufijos: panel_personal_v3__final -> panel personal"""
    b = normalizar(os.path.splitext(os.path.basename(ruta))[0])
    b = re.sub(r"[_\-\s.]+", " ", b)
    b = re.sub(r"\b(v\d+|ver\d+|version\s*\d+|final|definitivo|copia|copy|old|viejo|nuevo|new|bk|backup|test|prueba|\d{1,2})\b", " ", b)
    b = re.sub(r"\b(19|20)\d{6}\b", " ", b)  # fechas tipo 20261030
    return re.sub(r"\s+", " ", b).strip()


def contiene_palabra(texto_norm, kw):
    """Coincidencia de palabra completa, sin tildes, aceptando plural simple (s / es)."""
    return re.search(r"(?<![a-z0-9])" + re.escape(normalizar(kw)) + r"(?:s|es)?(?![a-z0-9])", texto_norm) is not None


# ───────────────────────────── Parser HTML ─────────────────────────────
class Extractor(HTMLParser):
    OCULTOS = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.oculto = 0
        self.en_title = False
        self.titulo = ""
        self.meta = {}
        self.encabezados = []          # (nivel, texto)
        self._h = None
        self._p = None
        self.parrafos = []
        self.textos = []
        self.n_chars = 0
        self.ids = set()
        self.enlaces_html = 0
        self.inputs = 0
        self.tablas = 0
        self.canvas = 0
        self.iconos = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.en_title = True
        if tag == "meta":
            k = (a.get("name") or a.get("property") or "").lower()
            if k and a.get("content"):
                self.meta[k] = a["content"]
        if tag == "link" and "icon" in (a.get("rel") or "") and a.get("href"):
            self.iconos = a["href"]
        if tag in self.OCULTOS and tag != "head":
            self.oculto += 1
        if tag == "head":
            self.oculto += 1
        if a.get("id"):
            self.ids.add(a["id"].lower())
        if tag in ("h1", "h2", "h3") and not self.oculto:
            self._h = [int(tag[1]), []]
        if tag == "p" and not self.oculto:
            self._p = []
        if tag == "a" and (a.get("href") or "").split("?")[0].lower().endswith(".html"):
            self.enlaces_html += 1
        if tag in ("input", "select", "textarea"):
            self.inputs += 1
        if tag == "table":
            self.tablas += 1
        if tag == "canvas":
            self.canvas += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.en_title = False
        if (tag in self.OCULTOS or tag == "head") and self.oculto:
            self.oculto -= 1
        if tag in ("h1", "h2", "h3") and self._h:
            t = limpiar(" ".join(self._h[1]))
            if t and "${" not in t:
                self.encabezados.append((self._h[0], t))
            self._h = None
        if tag == "p" and self._p is not None:
            t = limpiar(" ".join(self._p))
            if len(t) > 50 and "${" not in t:
                self.parrafos.append(t)
            self._p = None

    def handle_data(self, data):
        if self.en_title:
            self.titulo += data
            return
        if self.oculto:
            return
        if self._h is not None:
            self._h[1].append(data)
        if self._p is not None:
            self._p.append(data)
        if self.n_chars < 300000 and data.strip():
            self.textos.append(data)
            self.n_chars += len(data)


# ───────────────────────────── Fechas ─────────────────────────────
def fechas_git():
    """Una sola pasada por git log: {ruta_rel_a_public: (creado_iso, actualizado_iso, n_commits)}"""
    try:
        raiz = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
        if not raiz:
            return {}
        public_abs = os.path.abspath(CARPETA_PUBLIC)
        out = subprocess.run(["git", "-c", "core.quotepath=off", "log", "--format=@@%aI", "--name-only",
                              "--", public_abs], capture_output=True, text=True, encoding="utf-8",
                             errors="ignore", cwd=raiz, timeout=120).stdout
    except Exception:
        return {}
    res, fecha = {}, None
    for linea in out.splitlines():
        if linea.startswith("@@"):
            fecha = linea[2:].strip()
        elif linea.strip() and fecha:
            rel = os.path.relpath(os.path.join(raiz, linea.strip()), public_abs).replace("\\", "/")
            if rel in res:
                c, u, n = res[rel]
                res[rel] = (fecha, u, n + 1)       # el log va de nuevo a viejo
            else:
                res[rel] = (fecha, fecha, 1)
    return res


MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def fecha_de_datos(crudo, meta):
    """Busca una fecha de corte/generación dentro del HTML."""
    if meta.get("catalogo:fecha-datos"):
        return meta["catalogo:fecha-datos"][:10]
    candidatos = []
    patron_ctx = r"(generad[oa]|corte|actualizad[oa]|fecha de corte|elaborad[oa]|datos al|\"generado\")"
    for m in re.finditer(patron_ctx + r"[^0-9]{0,25}(\d{1,2})[/-](\d{1,2})[/-](20\d\d)", crudo, re.I):
        candidatos.append((int(m.group(4)), int(m.group(3)), int(m.group(2))))
    for m in re.finditer(patron_ctx + r"[^0-9]{0,25}(20\d\d)-(\d\d)-(\d\d)", crudo, re.I):
        candidatos.append((int(m.group(2)), int(m.group(3)), int(m.group(4))))
    for m in re.finditer(patron_ctx + r"[^0-9]{0,25}(\d{1,2}) de ([a-z]+) (?:de )?(20\d\d)", normalizar(crudo[:400000])):
        if m.group(3) in MESES:
            candidatos.append((int(m.group(4)), MESES[m.group(3)], int(m.group(2))))
    validos = []
    hoy = datetime.now()
    for y, mo, d in candidatos:
        try:
            f = datetime(y, mo, d)
            if 2015 <= y and f <= hoy.replace(year=hoy.year + 1):
                validos.append(f)
        except ValueError:
            pass
    return max(validos).strftime("%Y-%m-%d") if validos else None


# ───────────────────────────── Clasificación ─────────────────────────────
def clasificar(titulo, archivo, descripcion, encabezados, texto_visible, meta):
    t_tit = normalizar(titulo + " " + archivo.replace("_", " ").replace("-", " "))
    t_desc = normalizar(descripcion)
    t_enc = normalizar(" ".join(h for _, h in encabezados[:15]))
    t_cuerpo = normalizar(texto_visible[:8000])

    puntajes, palabras = {}, set()
    for nombre, _, kws in CATEGORIAS:
        p = 0
        for kw in kws:
            hits = 3 * contiene_palabra(t_tit, kw) + 2 * contiene_palabra(t_desc, kw) + \
                   1 * contiene_palabra(t_enc, kw) + 0.3 * contiene_palabra(t_cuerpo, kw)
            if hits:
                p += hits
                if contiene_palabra(t_tit, kw) or contiene_palabra(t_desc, kw):
                    palabras.add(kw)
        puntajes[nombre] = p
    mejor = max(CATEGORIAS, key=lambda c: (puntajes[c[0]], -CATEGORIAS.index(c)))
    categoria = mejor[0] if puntajes[mejor[0]] >= 1 else CATEGORIA_DEFECTO[0]
    if meta.get("catalogo:categoria"):
        categoria = meta["catalogo:categoria"].strip()
    secundarias = [c for c, _, _ in CATEGORIAS if c != categoria and puntajes[c] >= 3]
    return categoria, secundarias[:2], palabras


def detectar_territorio(titulo, archivo, descripcion, encabezados):
    texto = normalizar(" ".join([titulo, archivo.replace("_", " "), descripcion] + [h for _, h in encabezados[:6]]))
    deps = [d for d in DEPARTAMENTOS if contiene_palabra(texto, normalizar(d))]
    if not deps and re.search(r"\b(nacional|el salvador|pais)\b", texto):
        return ["Nacional"]
    return deps


def detectar_tecnologia(crudo):
    return [nombre for nombre, pats in TECNOLOGIAS if any(re.search(p, crudo, re.I) for p in pats)]


def detectar_tipo(titulo, archivo, ex, tecnologias, palabras):
    t = normalizar(titulo + " " + archivo.replace("_", " "))
    es_mapa = any(x in tecnologias for x in ("ArcGIS JS", "Leaflet", "MapLibre", "Mapbox")) or \
        any(i in ex.ids for i in ("map", "mapa", "viewdiv", "mapdiv"))
    if re.search(r"\b(menu|portal|indice|inicio)\b", t) or ex.enlaces_html >= 6:
        return "Menú"
    if re.search(r"\b(guia|manual|tutorial|metodologia)\b", t):
        return "Guía"
    if re.search(r"\b(simulador|evaluar|evaluador|calculadora|herramienta|simulacion)\b", t):
        return "Herramienta"
    if re.search(r"\b(informe|reporte|propuesta|analisis)\b", t) and not re.search(r"\b(panel|tablero|dashboard)\b", t):
        return "Informe"
    if re.search(r"\b(atlas|mapa)\b", t):
        return "Mapa"
    if re.search(r"\b(panel|tablero|dashboard|monitoreo|despacho)\b", t):
        return "Tablero"
    palabras_vis = len(" ".join(ex.textos).split())
    if palabras_vis > 1200 and len(ex.encabezados) >= 4:
        return "Informe"
    if es_mapa:
        return "Mapa"
    return "Tablero"


# ───────────────────────────── Similitud ─────────────────────────────
def huella(texto_visible, ex, crudo):
    palabras = [w for w in re.findall(r"[a-z0-9áéíóúñ]+", normalizar(texto_visible)) if w not in PALABRAS_VACIAS]
    sh = {hash(" ".join(palabras[i:i + 4])) for i in range(0, max(0, len(palabras) - 3))}
    sh |= {hash("id:" + i) for i in ex.ids}
    # Estructura de scripts (nombres de funciones), útil para tableros que pintan todo con JS
    sh |= {hash("fn:" + f) for f in re.findall(r"function\s+([A-Za-z_$][\w$]*)", crudo)}
    return sh


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ───────────────────────────── Miniaturas ─────────────────────────────
def servidor_local():
    """Sirve public/ por http en un puerto libre (más fiel a Firebase que file://)."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Silencioso(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                          ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
                          ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
                          ".css": "text/css; charset=utf-8"}

        def log_message(self, *a):
            pass

    manejador = functools.partial(Silencioso, directory=os.path.abspath(CARPETA_PUBLIC))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def captura_vacia(ruta_img):
    """True si la captura es casi de un solo color (pantalla de carga en blanco)."""
    try:
        from PIL import Image, ImageStat
        im = Image.open(ruta_img).convert("L").resize((64, 40))
        return ImageStat.Stat(im).stddev[0] < 9
    except ImportError:
        return os.path.getsize(ruta_img) < 6000
    except Exception:
        return False


def capturar_miniaturas(informes, forzar=False):
    os.makedirs(CARPETA_MINIS, exist_ok=True)
    ruta_cache = os.path.join(CARPETA_MINIS, "cache.json")
    try:
        cache = json.load(open(ruta_cache, encoding="utf-8"))
    except Exception:
        cache = {}

    pendientes = []
    for inf in informes:
        archivo_img = os.path.join(CARPETA_MINIS, inf["slug"] + ".jpg")
        previo = cache.get(inf["ruta"])
        if not forzar and previo == inf["hash"] and os.path.exists(archivo_img):
            inf["miniatura"] = f"_miniaturas/{inf['slug']}.jpg?v={inf['hash'][:8]}"
        elif not forzar and previo == "vacia:" + inf["hash"]:
            pass  # la última captura salió en blanco y el archivo no cambió: se usa la portada generada
        else:
            pendientes.append(inf)

    if pendientes:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("Playwright no está instalado → se usan portadas generadas. "
                "Para miniaturas reales: pip install playwright && python -m playwright install chromium")
            return
        log(f"Capturando {len(pendientes)} miniatura(s) nuevas o modificadas...")
        servidor, puerto = servidor_local()
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            ctx = nav.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=0.5)
            for i, inf in enumerate(pendientes, 1):
                pag = ctx.new_page()
                pag.on("dialog", lambda d: d.dismiss())
                destino = os.path.join(CARPETA_MINIS, inf["slug"] + ".jpg")
                try:
                    url = f"http://127.0.0.1:{puerto}/" + quote(inf["ruta"])
                    try:
                        pag.goto(url, wait_until="networkidle", timeout=25000)
                    except Exception:
                        pass  # ArcGIS mantiene peticiones abiertas: seguimos con lo que haya cargado
                    pag.wait_for_timeout(ESPERA_CAPTURA_MS)
                    pag.screenshot(path=destino, type="jpeg", quality=68)
                    if captura_vacia(destino):
                        cache[inf["ruta"]] = "vacia:" + inf["hash"]
                        os.remove(destino)
                        log(f"   [{i}/{len(pendientes)}] {inf['ruta']}  (salió en blanco → portada generada; "
                            f"se reintenta cuando cambie el archivo o con --forzar)")
                    else:
                        cache[inf["ruta"]] = inf["hash"]
                        inf["miniatura"] = f"_miniaturas/{inf['slug']}.jpg?v={inf['hash'][:8]}"
                        log(f"   [{i}/{len(pendientes)}] {inf['ruta']}")
                except Exception as e:
                    log(f"   [{i}/{len(pendientes)}] No se pudo capturar {inf['ruta']}: {e}")
                finally:
                    pag.close()
            nav.close()
        servidor.shutdown()

    # Limpia miniaturas de archivos que ya no existen
    vigentes = {inf["slug"] + ".jpg" for inf in informes}
    for f in os.listdir(CARPETA_MINIS):
        if f.endswith(".jpg") and f not in vigentes:
            try:
                os.remove(os.path.join(CARPETA_MINIS, f))
            except OSError:
                pass
    cache = {k: v for k, v in cache.items() if any(inf["ruta"] == k for inf in informes)}
    json.dump(cache, open(ruta_cache, "w", encoding="utf-8"), indent=1)


# ───────────────────────────── Escaneo ─────────────────────────────
def cargar_config():
    if os.path.exists(ARCHIVO_CONFIG):
        try:
            return json.load(open(ARCHIVO_CONFIG, encoding="utf-8"))
        except Exception as e:
            log(f"Aviso: {ARCHIVO_CONFIG} no es JSON válido ({e}); se ignora.")
    return {}


def coincide_patron(ruta, patrones):
    import fnmatch
    return any(fnmatch.fnmatch(ruta.lower(), p.lower()) or fnmatch.fnmatch(os.path.basename(ruta).lower(), p.lower())
               for p in patrones)


def analizar_archivo(ruta_completa, ruta_rel, git, config):
    crudo_b = open(ruta_completa, "rb").read()
    crudo = crudo_b.decode("utf-8", errors="ignore")
    h = hashlib.sha1(crudo_b).hexdigest()

    ex = Extractor()
    try:
        ex.feed(crudo)
    except Exception:
        pass
    meta = ex.meta
    texto_visible = limpiar(" ".join(ex.textos))
    archivo = os.path.basename(ruta_rel)

    titulo = limpiar(ex.titulo) or (ex.encabezados[0][1] if ex.encabezados else "") or \
        os.path.splitext(archivo)[0].replace("_", " ").replace("-", " ").title()
    descripcion = limpiar(meta.get("description") or meta.get("og:description") or "")
    parrafos = [p for p in ex.parrafos if not re.search(r"\b(cargando|conectando|loading|espere|iniciar sesion)\b", normalizar(p))]
    if not descripcion and parrafos:
        descripcion = parrafos[0]
    if not descripcion:
        subt = list(dict.fromkeys(t for n, t in ex.encabezados if normalizar(t) not in normalizar(titulo)))[:3]
        if subt:
            descripcion = " · ".join(subt)
    if len(descripcion) > 240:
        descripcion = descripcion[:237].rsplit(" ", 1)[0] + "…"

    categoria, secundarias, palabras = clasificar(titulo, archivo, descripcion, ex.encabezados, texto_visible, meta)
    tecnologia = detectar_tecnologia(crudo)
    tipo = meta.get("catalogo:tipo") or detectar_tipo(titulo, archivo, ex, tecnologia, palabras)
    territorio = detectar_territorio(titulo, archivo, descripcion, ex.encabezados)
    anios = sorted(set(re.findall(r"\b(20[12]\d)\b", titulo + " " + archivo + " " + descripcion)))

    tags = []
    for kw in sorted(palabras, key=len, reverse=True):
        if not any(normalizar(kw) in normalizar(t) for t in tags):
            tags.append(kw if kw[:1].isupper() else kw[:1].upper() + kw[1:])
    if meta.get("catalogo:tags"):
        tags = [t.strip() for t in meta["catalogo:tags"].split(",") if t.strip()] + tags
    tags = list(dict.fromkeys(tags))[:6]

    st = os.stat(ruta_completa)
    if ruta_rel in git:
        creado, actualizado, commits = git[ruta_rel]
        origen_fecha = "git"
    else:
        creado = datetime.fromtimestamp(min(st.st_ctime, st.st_mtime), timezone.utc).astimezone().isoformat()
        actualizado = datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat()
        commits, origen_fecha = 0, "archivo"

    inf = {
        "ruta": ruta_rel,
        "slug": slug(ruta_rel),
        "archivo": archivo,
        "carpeta": os.path.dirname(ruta_rel),
        "titulo": titulo,
        "descripcion": descripcion,
        "secciones": list(dict.fromkeys(t for n, t in ex.encabezados if n <= 2 and normalizar(t) != normalizar(titulo)))[:8],
        "categoria": categoria,
        "categorias_sec": secundarias,
        "tipo": tipo,
        "territorio": territorio,
        "anios": anios,
        "tecnologia": tecnologia,
        "tags": tags,
        "creado": creado,
        "actualizado": actualizado,
        "fecha_datos": fecha_de_datos(crudo, meta),
        "origen_fecha": origen_fecha,
        "commits": commits,
        "bytes": len(crudo_b),
        "palabras": len(texto_visible.split()),
        "interactivo": ex.inputs,
        "estado": (meta.get("catalogo:estado") or "vigente").lower(),
        "nota": meta.get("catalogo:nota", ""),
        "hash": h,
        "miniatura": None,
        "duplicados": [],
        "oculto": (meta.get("catalogo:ocultar", "").lower() in ("si", "sí", "true", "1")),
    }
    # Overrides del archivo de configuración
    ov = (config.get("archivos") or {}).get(ruta_rel) or (config.get("archivos") or {}).get(archivo)
    if ov:
        for k, v in ov.items():
            if k in inf:
                inf[k] = v
    if coincide_patron(ruta_rel, config.get("ocultar") or []):
        inf["oculto"] = True
    return inf, huella(texto_visible, ex, crudo)


def detectar_duplicados(informes, huellas, config):
    excluir = {frozenset(p) for p in (config.get("no_duplicados") or [])}
    n = len(informes)
    padre = list(range(n))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    titulos = [normalizar(i["titulo"]) for i in informes]
    bases = [nombre_base(i["ruta"]) for i in informes]
    pares = []
    for a in range(n):
        for b in range(a + 1, n):
            A, B = informes[a], informes[b]
            if frozenset((A["archivo"], B["archivo"])) in excluir or frozenset((A["ruta"], B["ruta"])) in excluir:
                continue
            motivos = []
            if A["hash"] == B["hash"]:
                motivos.append("contenido idéntico")
            if titulos[a] == titulos[b]:
                motivos.append("mismo título")
            if bases[a] and bases[a] == bases[b]:
                motivos.append("mismo nombre base")
            sim = jaccard(huellas[a], huellas[b])
            if sim >= UMBRAL_SIMILITUD and "contenido idéntico" not in motivos:
                motivos.append(f"{round(sim * 100)}% de contenido similar")
            if motivos:
                pares.append((a, b, motivos, sim))
                padre[raiz(a)] = raiz(b)

    grupos = {}
    for i in range(n):
        grupos.setdefault(raiz(i), []).append(i)
    lista_grupos = []
    for miembros in grupos.values():
        if len(miembros) < 2:
            continue
        miembros.sort(key=lambda i: informes[i]["actualizado"], reverse=True)
        gid = "g" + informes[miembros[0]]["slug"][:24]
        principal = informes[miembros[0]]["ruta"]
        for pos, i in enumerate(miembros):
            inf = informes[i]
            inf["grupo"] = gid
            inf["grupo_principal"] = principal
            if pos > 0 and inf["estado"] == "vigente":
                inf["estado"] = "anterior"
        for a, b, motivos, sim in pares:
            if a in miembros:
                informes[a]["duplicados"].append({"ruta": informes[b]["ruta"], "motivos": motivos, "similitud": round(sim, 2)})
                informes[b]["duplicados"].append({"ruta": informes[a]["ruta"], "motivos": motivos, "similitud": round(sim, 2)})
        lista_grupos.append({"id": gid, "principal": principal, "miembros": [informes[i]["ruta"] for i in miembros]})
    return lista_grupos


def generar_indice(capturas=True, forzar=False):
    with open(ARCHIVO_LOG, "w", encoding="utf-8") as f:
        f.write(f"--- GENERACIÓN DEL CATÁLOGO · {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    if not os.path.isdir(CARPETA_PUBLIC):
        log(f"ERROR: no existe la carpeta '{CARPETA_PUBLIC}'. Corré el script desde la raíz del repo.")
        sys.exit(1)

    config = cargar_config()
    git = fechas_git()
    log(f"Fechas desde {'git (' + str(len(git)) + ' archivos con historial)' if git else 'el sistema de archivos (no se encontró git)'}")

    informes, huellas = [], []
    for raiz_dir, dirs, archivos in os.walk(CARPETA_PUBLIC):
        dirs[:] = [d for d in dirs if d not in CARPETAS_IGNORADAS and not d.startswith(".")]
        for arch in sorted(archivos):
            if not arch.lower().endswith((".html", ".htm")):
                continue
            ruta_completa = os.path.join(raiz_dir, arch)
            ruta_rel = os.path.relpath(ruta_completa, CARPETA_PUBLIC).replace("\\", "/")
            if arch.lower() in ARCHIVOS_IGNORADOS and "/" not in ruta_rel:
                continue
            try:
                inf, hu = analizar_archivo(ruta_completa, ruta_rel, git, config)
            except Exception as e:
                log(f"Aviso: no se pudo analizar {ruta_rel}: {e}")
                continue
            if inf["oculto"]:
                log(f" - Oculto por configuración: {ruta_rel}")
                continue
            informes.append(inf)
            huellas.append(hu)

    log(f"Archivos analizados: {len(informes)}")
    grupos = detectar_duplicados(informes, huellas, config)
    if grupos:
        log(f"Posibles duplicados / versiones: {len(grupos)} grupo(s)")
        for g in grupos:
            log(f"   ★ {g['principal']}  (vigente)")
            for m in g["miembros"][1:]:
                inf = next(i for i in informes if i["ruta"] == m)
                mot = "; ".join(sorted({x for d in inf["duplicados"] for x in d["motivos"]}))
                log(f"     ↳ {m}  [{mot}]")

    if capturas:
        capturar_miniaturas(informes, forzar)

    colores = {n: c for n, c, _ in CATEGORIAS}
    colores[CATEGORIA_DEFECTO[0]] = CATEGORIA_DEFECTO[1]
    for inf in informes:
        inf.pop("oculto", None)
    datos = {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dominio": DOMINIO_BASE,
        "colores": colores,
        "grupos": grupos,
        "informes": sorted(informes, key=lambda x: x["actualizado"], reverse=True),
    }
    with open(ARCHIVO_JSON, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)

    html = PLANTILLA.replace("__TITULO__", TITULO_SITIO).replace("__SUBTITULO__", SUBTITULO_SITIO) \
        .replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Listo: {ARCHIVO_SALIDA} y {ARCHIVO_JSON}")


# ───────────────────────────── Plantilla del index ─────────────────────────────
PLANTILLA = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITULO__ · Catálogo</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f7f7f5; --panel:#ffffff; --ink:#0f2d2e; --text:#3f4b5b; --muted:#7a8696; --line:#e5e7eb; --line2:#f1f2f4;
  --gold:#c59b27; --teal:#0d4a4d; --teal-soft:#e6f0f0; --warn:#b45309; --warn-soft:#fef3c7; --bad:#b91c1c; --bad-soft:#fee2e2;
  --ok:#15803d; --ok-soft:#dcfce7; --shadow:0 1px 2px rgba(15,45,46,.04),0 2px 8px rgba(15,45,46,.04);
  --shadow-h:0 10px 28px rgba(15,45,46,.10);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0e1416; --panel:#151d20; --ink:#e8efee; --text:#c3cdd1; --muted:#8a979c; --line:#253136; --line2:#1c262a;
    --teal:#5fb3b3; --teal-soft:#16302f; --warn-soft:#3a2a0d; --bad-soft:#3a1616; --ok-soft:#12301d;
    --shadow:none; --shadow-h:0 10px 28px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --bg:#0e1416; --panel:#151d20; --ink:#e8efee; --text:#c3cdd1; --muted:#8a979c; --line:#253136; --line2:#1c262a;
  --teal:#5fb3b3; --teal-soft:#16302f; --warn-soft:#3a2a0d; --bad-soft:#3a1616; --ok-soft:#12301d;
  --shadow:none; --shadow-h:0 10px 28px rgba(0,0,0,.4);
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:inherit}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
.wrap{max-width:1440px;margin:0 auto;padding:2.2rem 1.5rem 4rem}

/* ── Encabezado ── */
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:1.5rem;flex-wrap:wrap;margin-bottom:1.6rem}
.eyebrow{text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;font-weight:700;color:var(--gold);display:flex;align-items:center;gap:.5rem;margin-bottom:.55rem}
.eyebrow::before{content:"";width:3px;height:14px;background:var(--gold)}
h1{font-family:'Playfair Display',Georgia,serif;font-size:clamp(2rem,4vw,2.8rem);line-height:1.05;color:var(--ink);letter-spacing:-.02em}
.lead{color:var(--muted);margin-top:.5rem;font-size:.95rem}
.top-actions{display:flex;gap:.5rem;align-items:center}
.icon-btn{width:36px;height:36px;border:1px solid var(--line);border-radius:8px;display:grid;place-items:center;background:var(--panel);color:var(--text)}
.icon-btn:hover{border-color:var(--teal);color:var(--teal)}

.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.75rem;margin-bottom:1.6rem}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:.85rem 1rem;text-align:left;display:flex;flex-direction:column;justify-content:flex-start;align-items:flex-start;box-shadow:var(--shadow);transition:border-color .15s}
button.stat:hover{border-color:var(--teal)}
.stat b{display:block;font-size:1.5rem;color:var(--ink);font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.stat span{font-size:.76rem;color:var(--muted)}
.stat.alert b{color:var(--warn)}

/* ── Barra de búsqueda ── */
.toolbar{position:sticky;top:0;z-index:20;background:var(--bg);padding:.7rem 0;display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;border-bottom:1px solid transparent}
.toolbar.stuck{border-bottom-color:var(--line)}
.search{flex:1 1 320px;position:relative}
.search input{width:100%;height:42px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:0 2.6rem 0 2.5rem;font:inherit;font-size:.95rem;color:var(--ink)}
.search input:focus{outline:2px solid var(--teal);outline-offset:-1px}
.search svg{position:absolute;left:.85rem;top:50%;transform:translateY(-50%);color:var(--muted)}
.search kbd{position:absolute;right:.7rem;top:50%;transform:translateY(-50%);font:600 .7rem Inter;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:1px 6px;background:var(--bg)}
.ctrl{height:42px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:0 .75rem;font:inherit;color:var(--text)}
.seg{display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--panel);height:42px}
.seg button{padding:0 .8rem;display:flex;align-items:center;gap:.35rem;color:var(--muted)}
.seg button.on{background:var(--teal-soft);color:var(--teal);font-weight:600}
.filtros-btn{display:none}

/* ── Layout ── */
.layout{display:grid;grid-template-columns:250px 1fr;gap:1.75rem;margin-top:.6rem}
aside{position:sticky;top:74px;align-self:start;max-height:calc(100vh - 90px);overflow:auto;padding-right:.25rem}
.facet{margin-bottom:1.25rem}
.facet h4{font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:.45rem;font-weight:700}
.opt{display:flex;align-items:center;gap:.5rem;width:100%;padding:.32rem .5rem;border-radius:6px;text-align:left;font-size:.86rem}
.opt:hover{background:var(--line2)}
.opt.on{background:var(--teal-soft);color:var(--teal);font-weight:600}
.opt.zero{opacity:.38}
.opt .dot{width:9px;height:9px;border-radius:50%;flex:none}
.opt .n{margin-left:auto;font-size:.75rem;color:var(--muted);font-variant-numeric:tabular-nums}
.switch{display:flex;align-items:center;gap:.55rem;font-size:.85rem;padding:.3rem .5rem;cursor:pointer}
.switch input{accent-color:var(--teal);width:15px;height:15px}

.status{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;min-height:28px}
.count{font-size:.85rem;color:var(--muted);margin-right:.3rem}
.count b{color:var(--ink)}
.chip{display:inline-flex;align-items:center;gap:.35rem;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:.15rem .4rem .15rem .65rem;font-size:.78rem}
.chip button{width:18px;height:18px;border-radius:50%;display:grid;place-items:center;color:var(--muted)}
.chip button:hover{background:var(--line2);color:var(--bad)}
.clear{font-size:.78rem;color:var(--teal);font-weight:600}

/* ── Tarjetas ── */
.group-h{display:flex;align-items:center;gap:.6rem;margin:1.6rem 0 .8rem;font-weight:700;color:var(--ink);font-size:.95rem}
.group-h:first-child{margin-top:0}
.group-h .dot{width:10px;height:10px;border-radius:50%}
.group-h small{color:var(--muted);font-weight:500}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:1.1rem}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column;box-shadow:var(--shadow);transition:transform .15s,box-shadow .15s,border-color .15s;position:relative}
.card:hover{transform:translateY(-2px);box-shadow:var(--shadow-h);border-color:color-mix(in srgb,var(--c) 40%,var(--line))}
.card::before{content:"";position:absolute;left:0;top:0;right:0;height:3px;background:var(--c);z-index:3}
.card.dim{opacity:.72}
.thumb{aspect-ratio:16/9.2;position:relative;overflow:hidden;background:var(--line2);border-bottom:1px solid var(--line);display:block}
.thumb img{width:100%;height:100%;object-fit:cover;object-position:top;display:block;transition:transform .4s}
.card:hover .thumb img{transform:scale(1.03)}
.thumb svg.cover{width:100%;height:100%;display:block}
.badges{position:absolute;top:10px;left:10px;right:10px;display:flex;justify-content:space-between;gap:.4rem;z-index:2;pointer-events:none}
.pill{font-size:.66rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:3px 8px;border-radius:5px;background:rgba(255,255,255,.95);color:#1f2937;box-shadow:0 1px 3px rgba(0,0,0,.12);white-space:nowrap}
.pill.new{background:var(--gold);color:#fff}
.pill.old{background:#fff7e6;color:#92400e}
.pill.obs{background:#fee2e2;color:#991b1b}
.peek{position:absolute;inset:auto 10px 10px auto;z-index:2;opacity:0;transform:translateY(4px);transition:.15s;background:rgba(15,45,46,.88);color:#fff;font-size:.75rem;font-weight:600;border-radius:6px;padding:.35rem .65rem}
.card:hover .peek,.peek:focus{opacity:1;transform:none}
.body{padding:.95rem 1rem 1rem;display:flex;flex-direction:column;gap:.45rem;flex:1}
.cat{font-size:.68rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--c);display:flex;align-items:center;gap:.4rem}
.cat button{color:inherit;font:inherit;letter-spacing:inherit;text-transform:inherit}
.cat button:hover{text-decoration:underline}
.title{font-size:1.02rem;font-weight:700;line-height:1.3;color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.title a{text-decoration:none}
.title a:hover{color:var(--teal)}
.file{font-size:.74rem;color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.desc{font-size:.84rem;color:var(--text);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.meta{display:flex;flex-wrap:wrap;gap:.25rem .85rem;font-size:.76rem;color:var(--muted);margin-top:.15rem}
.meta span{display:inline-flex;align-items:center;gap:.3rem}
.meta svg{flex:none;opacity:.8}
.tags{display:flex;flex-wrap:wrap;gap:.3rem}
.tag{font-size:.7rem;padding:2px 7px;border-radius:5px;background:var(--line2);color:var(--text);font-weight:500}
button.tag:hover{background:var(--teal-soft);color:var(--teal)}
.tag.terr{background:transparent;border:1px solid var(--line)}
.dup{font-size:.76rem;background:var(--warn-soft);color:var(--warn);border-radius:7px;padding:.4rem .6rem;display:flex;gap:.4rem;align-items:flex-start;text-align:left}
.dup:hover{filter:brightness(.97)}
.foot{margin-top:auto;padding-top:.7rem;border-top:1px solid var(--line2);display:flex;align-items:center;gap:.35rem}
.tech{font-size:.7rem;color:var(--muted);margin-right:auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.act{height:30px;padding:0 .6rem;border-radius:7px;font-size:.78rem;font-weight:600;display:inline-flex;align-items:center;gap:.3rem;color:var(--text);border:1px solid var(--line)}
.act:hover{border-color:var(--teal);color:var(--teal)}
.act.primary{background:var(--teal);border-color:var(--teal);color:#fff;text-decoration:none}
.act.primary:hover{filter:brightness(1.1);color:#fff}
[data-theme="dark"] .act.primary{color:#0e1416}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]) .act.primary{color:#0e1416}}

/* ── Lista ── */
.list{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.row{display:grid;grid-template-columns:88px minmax(0,2.4fr) minmax(0,1.1fr) 110px 120px 80px 112px;gap:1rem;align-items:center;padding:.6rem 1rem;border-bottom:1px solid var(--line2)}
.row:last-child{border-bottom:0}
.row:hover{background:var(--line2)}
.row.head{font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:700;background:var(--bg)}
.row .mini{width:88px;height:50px;border-radius:6px;overflow:hidden;background:var(--line2);border:1px solid var(--line)}
.row .mini img,.row .mini svg{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.row .t{font-weight:600;color:var(--ink);text-decoration:none;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .t:hover{color:var(--teal)}
.row .sub{font-size:.74rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .c{font-size:.8rem;display:flex;align-items:center;gap:.4rem;white-space:nowrap;overflow:hidden}
.row .num{font-size:.8rem;font-variant-numeric:tabular-nums}
.row .acts{display:flex;gap:.3rem;justify-content:flex-end}

.empty{text-align:center;padding:4rem 1rem;color:var(--muted)}
.empty b{display:block;color:var(--ink);font-size:1.05rem;margin-bottom:.3rem}

/* ── Paneles (detalle y duplicados) ── */
.scrim{position:fixed;inset:0;background:rgba(8,20,22,.5);z-index:50;opacity:0;pointer-events:none;transition:.2s}
.scrim.on{opacity:1;pointer-events:auto}
.sheet{position:fixed;z-index:60;background:var(--panel);box-shadow:0 20px 60px rgba(0,0,0,.25);transition:.25s;display:flex;flex-direction:column}
.modal{inset:3vh 3vw;border-radius:14px;opacity:0;transform:scale(.98);pointer-events:none}
.modal.on{opacity:1;transform:none;pointer-events:auto}
.drawer{top:0;right:0;bottom:0;width:min(560px,100vw);transform:translateX(100%)}
.drawer.on{transform:none}
.sheet-h{display:flex;align-items:center;gap:.75rem;padding:.9rem 1.1rem;border-bottom:1px solid var(--line)}
.sheet-h h3{font-size:1rem;color:var(--ink);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.modal-body{display:grid;grid-template-columns:330px 1fr;flex:1;min-height:0}
.info{padding:1.1rem;overflow:auto;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:1rem}
.info h5{font-size:.68rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:.35rem}
.info dl{display:grid;grid-template-columns:auto 1fr;gap:.3rem .8rem;font-size:.82rem}
.info dt{color:var(--muted)}
.info dd{color:var(--ink);font-weight:500}
.info ol{padding-left:1.1rem;font-size:.83rem;display:flex;flex-direction:column;gap:.2rem}
.frame{position:relative;background:var(--line2)}
.frame iframe{width:100%;height:100%;border:0;background:#fff}
.frame .loading{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:.85rem}
.drawer-body{overflow:auto;padding:1rem 1.1rem;display:flex;flex-direction:column;gap:1rem}
.dgroup{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.dgroup .it{display:flex;gap:.75rem;padding:.7rem .8rem;align-items:center;border-bottom:1px solid var(--line2)}
.dgroup .it:last-child{border-bottom:0}
.dgroup .it.main{background:var(--ok-soft)}
.dgroup .mini{width:78px;height:44px;border-radius:5px;overflow:hidden;flex:none;border:1px solid var(--line);background:var(--line2)}
.dgroup .mini img,.dgroup .mini svg{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.dgroup .tx{flex:1;min-width:0;font-size:.8rem}
.dgroup .tx b{display:block;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dgroup .why{font-size:.72rem;color:var(--warn)}
.hint{font-size:.8rem;color:var(--muted);background:var(--line2);border-radius:8px;padding:.7rem .8rem}
.hint code{font-size:.75rem}
.toast{position:fixed;bottom:22px;left:50%;transform:translate(-50%,20px);background:var(--ink);color:var(--bg);padding:.55rem 1rem;border-radius:8px;font-size:.85rem;opacity:0;transition:.2s;z-index:80;pointer-events:none}
.toast.on{opacity:1;transform:translate(-50%,0)}
.foot-note{margin-top:2.5rem;font-size:.76rem;color:var(--muted);text-align:center}

@media (max-width:1100px){.row{grid-template-columns:72px minmax(0,1fr) 120px 96px}.row .hide-md{display:none}.row .mini{width:72px;height:42px}}
@media (max-width:860px){
  .layout{grid-template-columns:1fr}
  aside{position:fixed;top:0;left:0;bottom:0;width:min(320px,88vw);max-height:none;background:var(--panel);z-index:60;padding:1.1rem;transform:translateX(-100%);transition:.25s;box-shadow:0 0 40px rgba(0,0,0,.2)}
  aside.on{transform:none}
  .filtros-btn{display:flex}
  .modal{inset:0;border-radius:0}
  .modal-body{grid-template-columns:1fr;grid-template-rows:auto 1fr}
  .info{max-height:38vh;border-right:0;border-bottom:1px solid var(--line)}
}
@media (max-width:560px){
  .wrap{padding:1.4rem 1rem 3rem}
  .top{position:relative;padding-right:48px}.top-actions{position:absolute;top:0;right:0}
  .stats{grid-template-columns:1fr 1fr}.stat b{font-size:1.25rem}
  .search{order:-1;flex-basis:100%}.search kbd{display:none}
  .toolbar .ctrl{flex:1;min-width:0}.filtros-btn{flex:none!important}
  .row{grid-template-columns:64px minmax(0,1fr) 40px}.row .hide-sm{display:none}.row .mini{width:64px;height:38px}
  .seg .lbl{display:none}
  .grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <div class="eyebrow">__SUBTITULO__</div>
      <h1>__TITULO__</h1>
      <p class="lead" id="lead"></p>
    </div>
    <div class="top-actions">
      <button class="icon-btn" id="tema" title="Cambiar tema claro/oscuro" aria-label="Cambiar tema">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
      </button>
    </div>
  </header>

  <section class="stats" id="stats"></section>

  <div class="toolbar" id="toolbar">
    <button class="ctrl filtros-btn" id="abrirFiltros" style="align-items:center;gap:.4rem">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 5h18M6 12h12M10 19h4"/></svg>Filtros
    </button>
    <label class="search">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="q" type="search" placeholder="Buscar por título, archivo, etiqueta, sección, territorio…" autocomplete="off" aria-label="Buscar">
      <kbd>/</kbd>
    </label>
    <select class="ctrl" id="orden" aria-label="Ordenar">
      <option value="act">Más recientes</option>
      <option value="cre">Creados recientemente</option>
      <option value="tit">Título A–Z</option>
      <option value="peso">Más pesados</option>
      <option value="rel">Relevancia</option>
    </select>
    <select class="ctrl" id="agrupar" aria-label="Agrupar">
      <option value="">Sin agrupar</option>
      <option value="categoria">Por categoría</option>
      <option value="tipo">Por tipo</option>
      <option value="mes">Por mes</option>
    </select>
    <div class="seg" role="group" aria-label="Vista">
      <button data-vista="grid" class="on" title="Tarjetas"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg><span class="lbl">Tarjetas</span></button>
      <button data-vista="list" title="Lista"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg><span class="lbl">Lista</span></button>
    </div>
  </div>

  <div class="layout">
    <aside id="aside" aria-label="Filtros"></aside>
    <main>
      <div class="status" id="status"></div>
      <div id="results"></div>
    </main>
  </div>
  <p class="foot-note" id="footnote"></p>
</div>

<div class="scrim" id="scrim"></div>
<section class="sheet modal" id="modal" aria-modal="true" role="dialog">
  <div class="sheet-h">
    <h3 id="mTitle"></h3>
    <a class="act primary" id="mOpen" target="_blank" rel="noopener">Abrir ↗</a>
    <button class="icon-btn" data-close aria-label="Cerrar">✕</button>
  </div>
  <div class="modal-body">
    <div class="info" id="mInfo"></div>
    <div class="frame"><div class="loading">Cargando vista previa…</div><iframe id="mFrame" title="Vista previa" loading="lazy"></iframe></div>
  </div>
</section>
<section class="sheet drawer" id="drawer" aria-modal="true" role="dialog">
  <div class="sheet-h"><h3>Posibles duplicados y versiones</h3><button class="icon-btn" data-close aria-label="Cerrar">✕</button></div>
  <div class="drawer-body" id="dBody"></div>
</section>
<div class="toast" id="toast"></div>

<script id="datos" type="application/json">__DATOS__</script>
<script>
(() => {
const D = JSON.parse(document.getElementById('datos').textContent);
const ITEMS = D.informes;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
const color = c => D.colores[c] || '#64748b';
const HOY = Date.now();
const DIA = 864e5;
const rtf = new Intl.RelativeTimeFormat('es', {numeric:'auto'});
const fmtF = new Intl.DateTimeFormat('es-SV', {day:'numeric', month:'short', year:'numeric'});
const fmtMes = new Intl.DateTimeFormat('es-SV', {month:'long', year:'numeric'});
const dias = iso => (HOY - new Date(iso)) / DIA;
function relativo(iso){
  const d = Math.round(-dias(iso));
  if (d > -1) return 'hoy';
  if (d > -30) return rtf.format(d, 'day');
  if (d > -365) return rtf.format(Math.round(d/30), 'month');
  return rtf.format(Math.round(d/365), 'year');
}
const fecha = iso => iso ? fmtF.format(new Date(iso.length === 10 ? iso + 'T12:00' : iso)) : '—';
const peso = b => b > 1048576 ? (b/1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b/1024)) + ' KB';
const porRuta = Object.fromEntries(ITEMS.map(i => [i.ruta, i]));
ITEMS.forEach(i => {
  i._busq = norm([i.titulo, i.archivo, i.descripcion, i.categoria, i.tipo, ...(i.tags||[]), ...(i.territorio||[]),
    ...(i.secciones||[]), ...(i.tecnologia||[]), ...(i.anios||[]), i.nota].join(' '));
  i._nuevo = dias(i.creado) <= 7;
  i._reciente = dias(i.actualizado) <= 7;
  i._estado = i.estado === 'anterior' ? 'Versión anterior' : i.estado === 'obsoleto' ? 'Obsoleto' : i.estado === 'borrador' ? 'Borrador' : 'Vigente';
});

/* ── Portadas generadas (cuando no hay screenshot) ── */
const PICT = {
  'Mapa': '<path d="M60 52 L100 40 L140 52 L180 40 L180 100 L140 112 L100 100 L60 112Z" fill="none" stroke="#fff" stroke-width="3" opacity=".9"/><path d="M100 40v60M140 52v60" stroke="#fff" stroke-width="2" opacity=".5"/><circle cx="122" cy="70" r="7" fill="#fff"/>',
  'Tablero': '<rect x="58" y="40" width="54" height="30" rx="4" fill="#fff" opacity=".9"/><rect x="118" y="40" width="64" height="30" rx="4" fill="#fff" opacity=".55"/><rect x="58" y="76" width="124" height="38" rx="4" fill="#fff" opacity=".35"/><path d="M66 106l18-14 16 8 22-20 20 12 30-18" stroke="#fff" stroke-width="3" fill="none"/>',
  'Informe': '<rect x="82" y="32" width="76" height="90" rx="5" fill="#fff" opacity=".92"/><path d="M94 50h52M94 62h52M94 74h36M94 90h52M94 102h44" stroke="COLOR" stroke-width="3" stroke-linecap="round" opacity=".55"/>',
  'Herramienta': '<circle cx="120" cy="76" r="30" fill="none" stroke="#fff" stroke-width="3" opacity=".9"/><path d="M120 76l18-14" stroke="#fff" stroke-width="4" stroke-linecap="round"/><circle cx="120" cy="76" r="5" fill="#fff"/><path d="M96 112h48" stroke="#fff" stroke-width="3" opacity=".6"/>',
  'Guía': '<path d="M120 46c-14-8-32-10-50-6v66c18-4 36-2 50 6 14-8 32-10 50-6V40c-18-4-36-2-50 6z" fill="#fff" opacity=".9"/><path d="M120 46v66" stroke="COLOR" stroke-width="2" opacity=".5"/>',
  'Menú': '<rect x="66" y="40" width="48" height="32" rx="4" fill="#fff" opacity=".9"/><rect x="126" y="40" width="48" height="32" rx="4" fill="#fff" opacity=".6"/><rect x="66" y="80" width="48" height="32" rx="4" fill="#fff" opacity=".6"/><rect x="126" y="80" width="48" height="32" rx="4" fill="#fff" opacity=".9"/>'
};
function hashNum(s){ let h = 0; for (const ch of s) h = (h*31 + ch.charCodeAt(0)) >>> 0; return h; }
function portada(i){
  const c = color(i.categoria), h = hashNum(i.hash || i.ruta);
  let fondo = '';
  for (let k = 0; k < 7; k++){
    const x = (h >>> (k*3)) % 240, y = (h >>> (k*2+1)) % 138, r = 18 + (h >>> k) % 40;
    fondo += `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" opacity="${(0.04 + (k%3)*0.03).toFixed(2)}"/>`;
  }
  const ini = (i.titulo.match(/[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]+/g) || ['?']).filter(w => w.length > 2).slice(0,2).map(w => w[0].toUpperCase()).join('');
  return `<svg class="cover" viewBox="0 0 240 138" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <defs><linearGradient id="g${h}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c}"/><stop offset="1" stop-color="${c}" stop-opacity=".72"/></linearGradient></defs>
    <rect width="240" height="138" fill="url(#g${h})"/>${fondo}
    <g transform="translate(-20,-6)">${(PICT[i.tipo] || PICT['Tablero']).replaceAll('COLOR', c)}</g>
    <text x="226" y="128" text-anchor="end" font-family="Playfair Display,Georgia,serif" font-weight="800" font-size="30" fill="#fff" opacity=".3">${esc(ini)}</text></svg>`;
}
const imagen = (i, cls='') => i.miniatura ? `<img src="${esc(i.miniatura)}" alt="" loading="lazy" decoding="async" class="${cls}" onerror="this.replaceWith(document.createRange().createContextualFragment(window.__portada('${esc(i.ruta)}')))">` : portada(i);
window.__portada = r => portada(porRuta[r]);

/* ── Estado ── */
const FACETAS = [
  {k:'categoria', t:'Categoría', get: i => [i.categoria], dot: true},
  {k:'tipo', t:'Tipo', get: i => [i.tipo]},
  {k:'territorio', t:'Territorio', get: i => i.territorio?.length ? i.territorio : ['Sin especificar']},
  {k:'anio', t:'Año', get: i => i.anios?.length ? i.anios : ['Sin año']},
  {k:'estado', t:'Estado', get: i => [i._estado]},
  {k:'tecnologia', t:'Tecnología', get: i => i.tecnologia?.length ? i.tecnologia : ['HTML/JS puro']},
  {k:'tag', t:'Etiquetas', get: i => i.tags || [], top: 14},
];
const S = {q:'', f:{}, orden:'act', agrupar:'', vista:'grid', ocultarAnt:false, recientes:false};
function leerHash(){
  const p = new URLSearchParams(location.hash.slice(1));
  S.q = p.get('q') || '';
  S.orden = p.get('orden') || 'act';
  S.agrupar = p.get('agrupar') || '';
  S.ocultarAnt = p.get('vigentes') === '1';
  S.recientes = p.get('recientes') === '1';
  S.f = {};
  FACETAS.forEach(F => { const v = p.get(F.k); if (v) S.f[F.k] = new Set(v.split('|')); });
  try { S.vista = p.get('vista') || localStorage.getItem('catalogo.vista') || 'grid'; } catch(e) { S.vista = p.get('vista') || 'grid'; }
}
function escribirHash(){
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  if (S.orden !== 'act') p.set('orden', S.orden);
  if (S.agrupar) p.set('agrupar', S.agrupar);
  if (S.ocultarAnt) p.set('vigentes', '1');
  if (S.recientes) p.set('recientes', '1');
  for (const [k, v] of Object.entries(S.f)) if (v.size) p.set(k, [...v].join('|'));
  const h = p.toString();
  history.replaceState(null, '', h ? '#' + h : location.pathname + location.search);
}

function puntaje(i, terms){
  let s = 0; const t = norm(i.titulo), a = norm(i.archivo), tg = norm((i.tags||[]).join(' '));
  for (const w of terms){ if (t.includes(w)) s += 5; if (a.includes(w)) s += 3; if (tg.includes(w)) s += 2; if (i._busq.includes(w)) s += 1; }
  return s;
}
function pasa(i, terms, salvo){
  if (S.ocultarAnt && (i.estado === 'anterior' || i.estado === 'obsoleto')) return false;
  if (S.recientes && dias(i.actualizado) > 30) return false;
  if (terms.length && !terms.every(w => i._busq.includes(w))) return false;
  for (const F of FACETAS){
    if (F.k === salvo) continue;
    const sel = S.f[F.k];
    if (sel && sel.size && !F.get(i).some(v => sel.has(v))) return false;
  }
  return true;
}

/* ── Render ── */
function render(){
  const terms = norm(S.q).split(/\s+/).filter(Boolean);
  let lista = ITEMS.filter(i => pasa(i, terms));
  const ord = {
    act: (a,b) => b.actualizado.localeCompare(a.actualizado),
    cre: (a,b) => b.creado.localeCompare(a.creado),
    tit: (a,b) => a.titulo.localeCompare(b.titulo, 'es'),
    peso: (a,b) => b.bytes - a.bytes,
    rel: (a,b) => puntaje(b, terms) - puntaje(a, terms) || b.actualizado.localeCompare(a.actualizado),
  }[S.orden];
  lista.sort(ord);
  renderFacetas(terms);
  renderStatus(lista.length);
  const R = $('#results');
  if (!lista.length){
    R.innerHTML = `<div class="empty"><b>Nada coincide con esos filtros</b>Probá con otras palabras o <button class="clear" data-limpiar>limpiá los filtros</button>.</div>`;
    return;
  }
  let grupos = [[null, lista]];
  if (S.agrupar){
    const m = new Map();
    for (const i of lista){
      const k = S.agrupar === 'mes' ? i.actualizado.slice(0,7) : i[S.agrupar];
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(i);
    }
    grupos = [...m.entries()];
    if (S.agrupar === 'mes') grupos.sort((a,b) => b[0].localeCompare(a[0]));
    else grupos.sort((a,b) => b[1].length - a[1].length);
  }
  R.innerHTML = grupos.map(([k, its]) => {
    let h = '';
    if (k !== null){
      const nom = S.agrupar === 'mes' ? fmtMes.format(new Date(k + '-15')) : k;
      const dot = S.agrupar === 'categoria' ? `<span class="dot" style="background:${color(k)}"></span>` : '';
      h = `<div class="group-h">${dot}<span style="${S.agrupar === 'mes' ? 'text-transform:capitalize' : ''}">${esc(nom)}</span><small>${its.length}</small></div>`;
    }
    return h + (S.vista === 'grid' ? `<div class="grid">${its.map(tarjeta).join('')}</div>`
      : `<div class="list"><div class="row head"><span></span><span>Informe</span><span class="hide-sm">Categoría</span><span class="hide-md">Tipo</span><span class="hide-sm">Actualizado</span><span class="hide-md">Peso</span><span></span></div>${its.map(fila).join('')}</div>`);
  }).join('');
  escribirHash();
}

const IC = {
  cal: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  db: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  w: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>',
  pin: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6.3-7-12a7 7 0 0 1 14 0c0 5.7-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/></svg>',
  link: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>',
  eye: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  warn: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex:none;margin-top:1px"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5M12 18h.01"/></svg>',
};
function pills(i){
  let izq = `<span class="pill">${esc(i.tipo)}</span>`, der = '';
  if (i.estado === 'anterior') der = `<span class="pill old">Versión anterior</span>`;
  else if (i.estado === 'obsoleto') der = `<span class="pill obs">Obsoleto</span>`;
  else if (i.estado === 'borrador') der = `<span class="pill old">Borrador</span>`;
  else if (i._nuevo) der = `<span class="pill new">Nuevo</span>`;
  else if (i._reciente) der = `<span class="pill new">Actualizado</span>`;
  return `<div class="badges">${izq}${der}</div>`;
}
function tarjeta(i){
  const c = color(i.categoria);
  const dup = i.duplicados?.length ? (() => {
    const otros = i.grupo ? ITEMS.filter(x => x.grupo === i.grupo && x !== i) : [];
    const txt = i.estado === 'anterior'
      ? `Hay una versión más reciente: <b>${esc(porRuta[i.grupo_principal]?.archivo || '')}</b>`
      : `${otros.length} archivo${otros.length>1?'s':''} parecido${otros.length>1?'s':''}: ${esc([...new Set(i.duplicados.flatMap(d => d.motivos))].slice(0,2).join(', '))}`;
    return `<button class="dup" data-grupo="${esc(i.grupo)}">${IC.warn}<span>${txt}</span></button>`;
  })() : '';
  const fd = i.fecha_datos ? `<span title="Fecha de corte o generación mencionada en el archivo">${IC.db}Datos ${fecha(i.fecha_datos)}</span>` : '';
  const terr = (i.territorio||[]).slice(0,2).map(t => `<button class="tag terr" data-f="territorio" data-v="${esc(t)}">${IC.pin} ${esc(t)}</button>`).join('');
  const tags = (i.tags||[]).slice(0,4).map(t => `<button class="tag" data-f="tag" data-v="${esc(t)}">${esc(t)}</button>`).join('');
  return `<article class="card ${i.estado !== 'vigente' ? 'dim' : ''}" style="--c:${c}">
    <div style="position:relative"><a class="thumb" href="${esc(i.ruta)}" target="_blank" rel="noopener" tabindex="-1">${pills(i)}${imagen(i)}</a>
    <button class="peek" data-ver="${esc(i.ruta)}">Vista rápida</button></div>
    <div class="body">
      <div class="cat"><button data-f="categoria" data-v="${esc(i.categoria)}">${esc(i.categoria)}</button></div>
      <h3 class="title"><a href="${esc(i.ruta)}" target="_blank" rel="noopener" title="${esc(i.titulo)}">${esc(i.titulo)}</a></h3>
      <div class="file">${esc(i.ruta)}</div>
      ${i.descripcion ? `<p class="desc">${esc(i.descripcion)}</p>` : ''}
      <div class="meta">
        <span title="Actualizado: ${fecha(i.actualizado)} · Creado: ${fecha(i.creado)}${i.commits ? ' · ' + i.commits + ' cambio(s) en git' : ''}">${IC.cal}${relativo(i.actualizado)}</span>
        ${fd}<span>${IC.w}${peso(i.bytes)}</span>
      </div>
      ${tags || terr ? `<div class="tags">${terr}${tags}</div>` : ''}
      ${dup}
      <div class="foot">
        <span class="tech" title="${esc((i.tecnologia||[]).join(', '))}">${esc((i.tecnologia||[]).join(' · '))}</span>
        <button class="act" data-ver="${esc(i.ruta)}" title="Detalle y vista rápida">${IC.eye}</button>
        <button class="act" data-copiar="${esc(i.ruta)}" title="Copiar enlace">${IC.link}</button>
        <a class="act primary" href="${esc(i.ruta)}" target="_blank" rel="noopener">Abrir ↗</a>
      </div>
    </div>
  </article>`;
}
function fila(i){
  return `<div class="row">
    <a class="mini" href="${esc(i.ruta)}" target="_blank" rel="noopener" tabindex="-1">${imagen(i)}</a>
    <div style="min-width:0"><a class="t" href="${esc(i.ruta)}" target="_blank" rel="noopener" title="${esc(i.titulo)}">${esc(i.titulo)}</a>
      <div class="sub">${esc(i.ruta)}${i.estado !== 'vigente' ? ' · <b style="color:var(--warn)">' + esc(i._estado) + '</b>' : ''}${i.duplicados?.length && i.estado === 'vigente' ? ' · <span style="color:var(--warn)">tiene duplicados</span>' : ''}</div></div>
    <div class="c hide-sm"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:${color(i.categoria)};flex:none"></span>${esc(i.categoria)}</div>
    <div class="c hide-md">${esc(i.tipo)}</div>
    <div class="num hide-sm" title="${fecha(i.actualizado)}">${relativo(i.actualizado)}</div>
    <div class="num hide-md">${peso(i.bytes)}</div>
    <div class="acts"><button class="act hide-sm" data-ver="${esc(i.ruta)}" title="Detalle">${IC.eye}</button><button class="act hide-sm" data-copiar="${esc(i.ruta)}" title="Copiar enlace">${IC.link}</button><a class="act primary" href="${esc(i.ruta)}" target="_blank" rel="noopener">↗</a></div>
  </div>`;
}
function renderFacetas(terms){
  let h = `<div class="facet"><h4>Mostrar</h4>
    <label class="switch"><input type="checkbox" id="swVig" ${S.ocultarAnt?'checked':''}> Solo versiones vigentes</label>
    <label class="switch"><input type="checkbox" id="swRec" ${S.recientes?'checked':''}> Actualizados en 30 días</label></div>`;
  for (const F of FACETAS){
    const base = ITEMS.filter(i => pasa(i, terms, F.k));
    const cnt = new Map();
    ITEMS.forEach(i => F.get(i).forEach(v => { if (!cnt.has(v)) cnt.set(v, 0); }));
    base.forEach(i => F.get(i).forEach(v => cnt.set(v, cnt.get(v) + 1)));
    let vals = [...cnt.entries()].sort((a,b) => b[1] - a[1] || String(a[0]).localeCompare(b[0], 'es'));
    if (F.k === 'anio') vals.sort((a,b) => String(b[0]).localeCompare(a[0]));
    const sel = S.f[F.k] || new Set();
    if (F.top) vals = vals.filter(([v,n]) => n > 0 || sel.has(v)).slice(0, F.top);
    if (vals.length < 2 && !sel.size) continue;
    h += `<div class="facet"><h4>${F.t}</h4>` + vals.map(([v,n]) =>
      `<button class="opt ${sel.has(v)?'on':''} ${n===0&&!sel.has(v)?'zero':''}" data-f="${F.k}" data-v="${esc(v)}">${F.dot ? `<span class="dot" style="background:${color(v)}"></span>` : ''}<span>${esc(v)}</span><span class="n">${n}</span></button>`
    ).join('') + `</div>`;
  }
  $('#aside').innerHTML = h;
}
function renderStatus(n){
  const chips = [];
  if (S.q) chips.push(`<span class="chip">“${esc(S.q)}”<button data-quitar="q" aria-label="Quitar">✕</button></span>`);
  if (S.ocultarAnt) chips.push(`<span class="chip">Solo vigentes<button data-quitar="vig">✕</button></span>`);
  if (S.recientes) chips.push(`<span class="chip">Últimos 30 días<button data-quitar="rec">✕</button></span>`);
  for (const [k, set] of Object.entries(S.f)) for (const v of set)
    chips.push(`<span class="chip">${esc(v)}<button data-f="${k}" data-v="${esc(v)}" aria-label="Quitar">✕</button></span>`);
  $('#status').innerHTML = `<span class="count"><b>${n}</b> de ${ITEMS.length}</span>${chips.join('')}${chips.length ? '<button class="clear" data-limpiar>Limpiar todo</button>' : ''}`;
}
function renderStats(){
  const rec = ITEMS.filter(i => dias(i.actualizado) <= 30).length;
  const dupArch = ITEMS.filter(i => i.estado === 'anterior').length;
  const cats = new Set(ITEMS.map(i => i.categoria)).size;
  const total = ITEMS.reduce((s,i) => s + i.bytes, 0);
  const ult = ITEMS.reduce((m,i) => i.actualizado > m ? i.actualizado : m, '');
  $('#stats').innerHTML = `
    <div class="stat"><b>${ITEMS.length}</b><span>Archivos publicados</span></div>
    <button class="stat" data-stat="rec"><b>${rec}</b><span>Actualizados en 30 días</span></button>
    <button class="stat ${D.grupos.length ? 'alert' : ''}" data-stat="dup"><b>${D.grupos.length}</b><span>${D.grupos.length === 1 ? 'Grupo' : 'Grupos'} de duplicados${dupArch ? ' · ' + dupArch + (dupArch === 1 ? ' versión vieja' : ' versiones viejas') : ''}</span></button>
    <div class="stat"><b>${cats}</b><span>Categorías</span></div>
    <div class="stat"><b>${peso(total)}</b><span>Peso total publicado</span></div>`;
  $('#lead').textContent = `Última publicación ${relativo(ult)} · catálogo generado el ${fecha(D.generado)}`;
  $('#footnote').innerHTML = `Generado automáticamente por <code>generar_indice.py</code> · ${esc(D.dominio)} · <a href="catalogo.json">catalogo.json</a>`;
}

/* ── Detalle / vista rápida ── */
function abrirDetalle(ruta){
  const i = porRuta[ruta]; if (!i) return;
  $('#mTitle').textContent = i.titulo;
  $('#mOpen').href = i.ruta;
  const otros = i.grupo ? ITEMS.filter(x => x.grupo === i.grupo && x !== i) : [];
  $('#mInfo').innerHTML = `
    <div><div class="cat" style="--c:${color(i.categoria)};color:${color(i.categoria)}">${esc(i.categoria)} · ${esc(i.tipo)}</div>
      ${i.descripcion ? `<p style="margin-top:.4rem;font-size:.86rem">${esc(i.descripcion)}</p>` : ''}
      ${i.nota ? `<p class="hint" style="margin-top:.5rem">${esc(i.nota)}</p>` : ''}</div>
    <div><h5>Ficha</h5><dl>
      <dt>Archivo</dt><dd style="word-break:break-all">${esc(i.ruta)}</dd>
      <dt>Actualizado</dt><dd>${fecha(i.actualizado)} (${relativo(i.actualizado)})</dd>
      <dt>Creado</dt><dd>${fecha(i.creado)}</dd>
      ${i.fecha_datos ? `<dt>Datos al</dt><dd>${fecha(i.fecha_datos)}</dd>` : ''}
      ${i.commits ? `<dt>Cambios</dt><dd>${i.commits} commit(s)</dd>` : ''}
      <dt>Estado</dt><dd>${esc(i._estado)}</dd>
      <dt>Peso</dt><dd>${peso(i.bytes)}${i.palabras ? ' · ' + i.palabras.toLocaleString('es') + ' palabras' : ''}</dd>
      ${i.territorio?.length ? `<dt>Territorio</dt><dd>${esc(i.territorio.join(', '))}</dd>` : ''}
      ${i.tecnologia?.length ? `<dt>Tecnología</dt><dd>${esc(i.tecnologia.join(', '))}</dd>` : ''}
    </dl></div>
    ${i.secciones?.length ? `<div><h5>Contenido</h5><ol>${i.secciones.map(s => `<li>${esc(s)}</li>`).join('')}</ol></div>` : ''}
    ${otros.length ? `<div><h5>Parecidos</h5>${otros.map(o => `<button class="dup" style="width:100%;margin-bottom:.35rem" data-ver="${esc(o.ruta)}">${IC.warn}<span><b>${esc(o.archivo)}</b> · ${relativo(o.actualizado)}${o.ruta === i.grupo_principal ? ' · vigente' : ''}</span></button>`).join('')}</div>` : ''}
    <div style="display:flex;gap:.4rem;flex-wrap:wrap"><button class="act" data-copiar="${esc(i.ruta)}">${IC.link} Copiar enlace</button></div>`;
  const fr = $('#mFrame');
  fr.parentElement.querySelector('.loading').style.display = 'grid';
  fr.onload = () => fr.parentElement.querySelector('.loading').style.display = 'none';
  fr.src = 'about:blank';
  setTimeout(() => fr.src = i.ruta, 30);
  abrir('#modal');
}
function abrirDuplicados(gid){
  const gs = gid ? D.grupos.filter(g => g.id === gid) : D.grupos;
  $('#dBody').innerHTML = (gs.length ? `<p class="hint">El primero de cada grupo (en verde) es el más reciente y se toma como vigente. Si alguno es distinto a propósito, agregá el par en <code>"no_duplicados"</code> de <code>catalogo.config.json</code>; para retirar uno, borralo de <code>public/</code> o marcá <code>&lt;meta name="catalogo:estado" content="obsoleto"&gt;</code>.</p>` : '<p class="hint">No se detectaron duplicados. 🎉</p>') +
    gs.map(g => `<div class="dgroup">${g.miembros.map((r, k) => {
      const i = porRuta[r]; if (!i) return '';
      const mot = [...new Set(i.duplicados.flatMap(d => d.motivos))].join(' · ');
      return `<div class="it ${k===0?'main':''}"><div class="mini">${imagen(i)}</div>
        <div class="tx"><b>${esc(i.titulo)}</b>${esc(i.ruta)} · ${relativo(i.actualizado)} · ${peso(i.bytes)}${k ? `<div class="why">${esc(mot)}</div>` : '<div style="color:var(--ok);font-size:.72rem;font-weight:600">Vigente</div>'}</div>
        <button class="act" data-ver="${esc(r)}">${IC.eye}</button><a class="act" href="${esc(r)}" target="_blank" rel="noopener">↗</a></div>`;
    }).join('')}</div>`).join('') +
    (gid ? `<button class="clear" data-stat="dup">Ver todos los grupos</button>` : '');
  abrir('#drawer');
}
function abrir(sel){ document.querySelectorAll('.sheet.on').forEach(x => { if ('#' + x.id !== sel) x.classList.remove('on'); }); $(sel).classList.add('on'); $('#scrim').classList.add('on'); document.body.style.overflow = 'hidden'; }
function cerrar(){ document.querySelectorAll('.sheet.on,#aside.on').forEach(x => x.classList.remove('on')); $('#scrim').classList.remove('on'); document.body.style.overflow = ''; $('#mFrame').src = 'about:blank'; }
function toast(t){ const el = $('#toast'); el.textContent = t; el.classList.add('on'); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('on'), 1800); }

/* ── Eventos ── */
document.addEventListener('click', e => {
  const b = e.target.closest('button,[data-close]'); if (!b) { if (e.target.id === 'scrim') cerrar(); return; }
  if (b.dataset.close !== undefined) return cerrar();
  if (b.dataset.f && b.dataset.v !== undefined){
    const set = S.f[b.dataset.f] || (S.f[b.dataset.f] = new Set());
    set.has(b.dataset.v) ? set.delete(b.dataset.v) : set.add(b.dataset.v);
    if (!set.size) delete S.f[b.dataset.f];
    if (b.closest('.card')) window.scrollTo({top: $('#toolbar').offsetTop, behavior: 'smooth'});
    return render();
  }
  if (b.dataset.quitar){ if (b.dataset.quitar === 'q'){ S.q = ''; $('#q').value = ''; } if (b.dataset.quitar === 'vig') S.ocultarAnt = false; if (b.dataset.quitar === 'rec') S.recientes = false; return render(); }
  if (b.dataset.limpiar !== undefined){ S.q = ''; $('#q').value = ''; S.f = {}; S.ocultarAnt = false; S.recientes = false; return render(); }
  if (b.dataset.ver) { e.preventDefault(); return abrirDetalle(b.dataset.ver); }
  if (b.dataset.grupo) return abrirDuplicados(b.dataset.grupo);
  if (b.dataset.stat === 'dup') return abrirDuplicados();
  if (b.dataset.stat === 'rec'){ S.recientes = !S.recientes; S.orden = 'act'; $('#orden').value = 'act'; return render(); }
  if (b.dataset.copiar){
    const url = D.dominio.replace(/\/$/, '') + '/' + encodeURI(b.dataset.copiar);
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => toast('Enlace copiado'), () => { prompt('Copiá el enlace:', url); });
    return;
  }
  if (b.dataset.vista){ S.vista = b.dataset.vista; try { localStorage.setItem('catalogo.vista', S.vista); } catch(e){} sincronizarCtrls(); return render(); }
  if (b.id === 'abrirFiltros'){ $('#aside').classList.add('on'); $('#scrim').classList.add('on'); return; }
  if (b.id === 'tema'){
    const r = document.documentElement, oscuro = getComputedStyle(r).getPropertyValue('--bg').trim() === '#0e1416';
    r.dataset.theme = oscuro ? 'light' : 'dark'; try { localStorage.setItem('catalogo.tema', r.dataset.theme); } catch(e){}
    return;
  }
});
$('#scrim').addEventListener('click', cerrar);
document.addEventListener('change', e => {
  if (e.target.id === 'swVig'){ S.ocultarAnt = e.target.checked; render(); }
  if (e.target.id === 'swRec'){ S.recientes = e.target.checked; render(); }
});
let tq; $('#q').addEventListener('input', e => { clearTimeout(tq); tq = setTimeout(() => { S.q = e.target.value.trim(); if (S.q && S.orden === 'act') { S.orden = 'rel'; $('#orden').value = 'rel'; } if (!S.q && S.orden === 'rel') { S.orden = 'act'; $('#orden').value = 'act'; } render(); }, 120); });
$('#orden').addEventListener('change', e => { S.orden = e.target.value; render(); });
$('#agrupar').addEventListener('change', e => { S.agrupar = e.target.value; render(); });
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT'){ e.preventDefault(); $('#q').focus(); }
  if (e.key === 'Escape'){ if (document.querySelector('.sheet.on,#aside.on')) cerrar(); else if (document.activeElement === $('#q')){ $('#q').value = ''; S.q = ''; render(); } }
});
new IntersectionObserver(([en]) => $('#toolbar').classList.toggle('stuck', !en.isIntersecting), {rootMargin: '-1px 0px 0px 0px'}).observe($('#stats'));
function sincronizarCtrls(){
  $('#q').value = S.q; $('#orden').value = S.orden; $('#agrupar').value = S.agrupar;
  document.querySelectorAll('[data-vista]').forEach(b => b.classList.toggle('on', b.dataset.vista === S.vista));
}
try { const t = localStorage.getItem('catalogo.tema'); if (t) document.documentElement.dataset.theme = t; } catch(e){}
leerHash(); sincronizarCtrls(); renderStats(); render();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Genera el catálogo index.html de la carpeta public/")
    ap.add_argument("--sin-capturas", action="store_true", help="No tomar screenshots; usar portadas generadas")
    ap.add_argument("--forzar", action="store_true", help="Recapturar todas las miniaturas")
    args = ap.parse_args()
    generar_indice(capturas=not args.sin_capturas, forzar=args.forzar)
