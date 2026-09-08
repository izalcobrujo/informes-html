import os
import re
import sys
from datetime import datetime

CARPETA_PUBLIC = "public"
ARCHIVO_SALIDA = os.path.join(CARPETA_PUBLIC, "index.html")
ARCHIVO_LOG = "generar_indice.log"
DOMINIO_BASE = "https://dashboard-datos.web.app"

ARCHIVOS_IGNORADOS = {"index.html", "404.html"}

def escribir_log(mensaje):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensaje}\n"
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f_log:
        f_log.write(linea)
    print(mensaje)

def generar_svg_preview(tipo):
    """Genera una ilustración SVG abstracta según el tipo de visualización detectado."""
    if tipo == "mapa":
        badge = "Mapa / GIS"
        svg = """
        <svg width="100%" height="100%" viewBox="0 0 260 130" xmlns="http://www.w3.org/2000/svg">
            <rect width="260" height="130" fill="#f0fdf4"/>
            <path d="M20 70 Q 60 40 100 65 T 180 50 T 240 80" fill="none" stroke="#bbf7d0" stroke-width="8" stroke-linecap="round"/>
            <polygon points="50,40 85,30 110,60 70,75" fill="#86efac" opacity="0.6"/>
            <polygon points="120,45 170,35 185,75 130,80" fill="#4ade80" opacity="0.5"/>
            <polygon points="175,70 220,60 235,95 190,105" fill="#22c55e" opacity="0.4"/>
            <!-- Pines de ubicación -->
            <circle cx="85" cy="45" r="4" fill="#0f766e"/>
            <circle cx="150" cy="55" r="5" fill="#0f766e"/>
            <circle cx="205" cy="80" r="4" fill="#0f766e"/>
        </svg>"""
    elif tipo == "lineas":
        badge = "Tendencia / Serie"
        svg = """
        <svg width="100%" height="100%" viewBox="0 0 260 130" xmlns="http://www.w3.org/2000/svg">
            <rect width="260" height="130" fill="#f8fafc"/>
            <line x1="30" y1="105" x2="230" y2="105" stroke="#e2e8f0" stroke-width="1.5"/>
            <line x1="30" y1="70" x2="230" y2="70" stroke="#f1f5f9" stroke-width="1.5"/>
            <line x1="30" y1="35" x2="230" y2="35" stroke="#f1f5f9" stroke-width="1.5"/>
            <path d="M 35 90 Q 70 40 110 75 T 170 30 T 225 45" fill="none" stroke="#0284c7" stroke-width="3" stroke-linecap="round"/>
            <circle cx="110" cy="75" r="4" fill="#0284c7"/>
            <circle cx="170" cy="30" r="4" fill="#0284c7"/>
            <circle cx="225" cy="45" r="4" fill="#0284c7"/>
        </svg>"""
    elif tipo == "dona":
        badge = "Distribución"
        svg = """
        <svg width="100%" height="100%" viewBox="0 0 260 130" xmlns="http://www.w3.org/2000/svg">
            <rect width="260" height="130" fill="#fffbeb"/>
            <circle cx="130" cy="65" r="40" fill="none" stroke="#fef3c7" stroke-width="16"/>
            <circle cx="130" cy="65" r="40" fill="none" stroke="#f59e0b" stroke-width="16" stroke-dasharray="90 200" stroke-dashoffset="0"/>
            <circle cx="130" cy="65" r="40" fill="none" stroke="#d97706" stroke-width="16" stroke-dasharray="60 200" stroke-dashoffset="-95"/>
            <circle cx="130" cy="65" r="40" fill="none" stroke="#b45309" stroke-width="16" stroke-dasharray="40 200" stroke-dashoffset="-160"/>
        </svg>"""
    elif tipo == "tabla":
        badge = "Matriz / Datos"
        svg = """
        <svg width="100%" height="100%" viewBox="0 0 260 130" xmlns="http://www.w3.org/2000/svg">
            <rect width="260" height="130" fill="#f8fafc"/>
            <rect x="35" y="25" width="190" height="18" rx="4" fill="#cbd5e1"/>
            <rect x="35" y="50" width="190" height="12" rx="3" fill="#e2e8f0"/>
            <rect x="35" y="68" width="190" height="12" rx="3" fill="#e2e8f0"/>
            <rect x="35" y="86" width="190" height="12" rx="3" fill="#e2e8f0"/>
            <circle cx="50" cy="56" r="3" fill="#94a3b8"/>
            <circle cx="50" cy="74" r="3" fill="#94a3b8"/>
            <circle cx="50" cy="92" r="3" fill="#94a3b8"/>
        </svg>"""
    else:  # tipo == "barras" (predeterminado para análisis)
        badge = "Métricas / Barras"
        svg = """
        <svg width="100%" height="100%" viewBox="0 0 260 130" xmlns="http://www.w3.org/2000/svg">
            <rect width="260" height="130" fill="#f0fdfa"/>
            <line x1="30" y1="105" x2="230" y2="105" stroke="#ccfbf1" stroke-width="1.5"/>
            <rect x="45" y="65" width="22" height="40" rx="3" fill="#5eead4"/>
            <rect x="78" y="40" width="22" height="65" rx="3" fill="#14b8a6"/>
            <rect x="111" y="50" width="22" height="55" rx="3" fill="#0d9488"/>
            <rect x="144" y="30" width="22" height="75" rx="3" fill="#0f766e"/>
            <rect x="177" y="55" width="22" height="50" rx="3" fill="#14b8a6"/>
            <rect x="210" y="35" width="22" height="70" rx="3" fill="#5eead4"/>
        </svg>"""
    return svg, badge

def extraer_metadatos_y_tipo(ruta_completa, ruta_relativa):
    """Extrae título, etiquetas e infiere el tipo de visualización del archivo HTML."""
    titulo = ""
    tipo_grafico = "barras"  # Valor por defecto
    try:
        with open(ruta_completa, "r", encoding="utf-8", errors="ignore") as f:
            contenido = f.read(50000)  # Lee los primeros 50KB para detectar scripts y estructura
            
            # Buscar <title>
            match_title = re.search(r"<title>(.*?)</title>", contenido, re.IGNORECASE | re.DOTALL)
            if match_title:
                titulo = match_title.group(1).strip()
            
            if not titulo:
                match_h1 = re.search(r"<h1[^>]*>(.*?)</h1>", contenido, re.IGNORECASE | re.DOTALL)
                if match_h1:
                    titulo = re.sub(r"<[^>]+>", "", match_h1.group(1)).strip()

            c_lower = contenido.lower()

            # Detección de mapas
            if any(k in c_lower for k in ["leaflet", "mapbox", "maplibre", "arcgis", "ol.map", "geojson", "id=\"map\""]):
                tipo_grafico = "mapa"
            # Detección de gráficos circulares o dona
            elif any(k in c_lower for k in ["type: 'doughnut'", "type: 'pie'", "type:\"pie\"", "piechart"]):
                tipo_grafico = "dona"
            # Detección de gráficos de líneas / tendencias
            elif any(k in c_lower for k in ["type: 'line'", "type:\"line\"", "linechart", "sparkline"]):
                tipo_grafico = "lineas"
            # Detección de tablas de datos estructuradas
            elif "<table" in c_lower and ("datatable" in c_lower or "grid" in c_lower):
                tipo_grafico = "tabla"
            # Predeterminado a barras/métricas
            else:
                tipo_grafico = "barras"

    except Exception as e:
        escribir_log(f"Aviso al leer metadatos de {ruta_relativa}: {e}")

    if not titulo:
        nombre_base = os.path.splitext(os.path.basename(ruta_relativa))[0]
        titulo = nombre_base.replace("_", " ").replace("-", " ").title()

    tags = [p for p in re.split(r"[-_]", os.path.splitext(os.path.basename(ruta_relativa))[0]) if len(p) > 2]
    if not tags:
        tags = ["Reporte"]

    return titulo, tags, tipo_grafico

def generar_indice():
    with open(ARCHIVO_LOG, "w", encoding="utf-8") as f_log:
        f_log.write("--- REGISTRO DE GENERACION DE CATALOGO VISUAL CON GRAFICOS ---\n")
        f_log.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    escribir_log(f"Iniciando escaneo en carpeta: {CARPETA_PUBLIC}")

    if not os.path.exists(CARPETA_PUBLIC):
        escribir_log(f"ERROR: La carpeta '{CARPETA_PUBLIC}' no existe.")
        sys.exit(1)

    informes = []
    for raiz, _, archivos in os.walk(CARPETA_PUBLIC):
        for arch in archivos:
            nombre_lower = arch.lower()
            if nombre_lower.endswith(".html") and nombre_lower not in ARCHIVOS_IGNORADOS:
                ruta_completa = os.path.join(raiz, arch)
                ruta_rel = os.path.relpath(ruta_completa, CARPETA_PUBLIC).replace("\\", "/")
                titulo, tags, tipo_grafico = extraer_metadatos_y_tipo(ruta_completa, ruta_rel)
                informes.append({
                    "ruta": ruta_rel,
                    "titulo": titulo,
                    "tags": tags,
                    "tipo": tipo_grafico,
                    "url": f"{DOMINIO_BASE}/{ruta_rel}"
                })
            elif nombre_lower in ARCHIVOS_IGNORADOS:
                escribir_log(f" - Archivo omitido por regla de exclusión: {arch}")

    total_informes = len(informes)
    escribir_log(f"Total de informes procesados: {total_informes}")
    informes.sort(key=lambda x: x["titulo"])

    tarjetas_html = ""
    for inf in informes:
        svg_preview, badge_tipo = generar_svg_preview(inf["tipo"])
        tags_spans = "".join([f'<span class="tag">{t.capitalize()}</span>' for t in inf["tags"][:3]])
        
        tarjetas_html += f"""
        <article class="card-item" data-busqueda="{inf['titulo'].lower()} {inf['ruta'].lower()} {' '.join(inf['tags']).lower()}">
            <div class="card-preview">
                <div class="card-badge">{badge_tipo}</div>
                {svg_preview}
            </div>
            <div class="card-content">
                <h3 class="card-title">
                    <a href="{inf['ruta']}" target="_blank">{inf['titulo']}</a>
                </h3>
                <p class="card-path">{inf['ruta']}</p>
                <div class="card-footer">
                    <div class="tags-container">
                        {tags_spans}
                    </div>
                    <a href="{inf['ruta']}" target="_blank" class="btn-abrir">Abrir ↗</a>
                </div>
            </div>
        </article>"""

    plantilla_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repositorio de Análisis y Reportes</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700&family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-body: #fcfcfc;
            --bg-card: #ffffff;
            --color-title: #0f2d2e;
            --color-text: #475569;
            --color-border: #e2e8f0;
            --accent-gold: #c59b27;
            --accent-teal: #0d4a4d;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-body);
            color: var(--color-text);
            font-family: 'Inter', sans-serif;
            padding: 3rem 1.5rem;
            min-height: 100vh;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}

        .sub-header {{
            text-transform: uppercase;
            letter-spacing: 0.15em;
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--accent-gold);
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .sub-header::before {{
            content: "";
            display: inline-block;
            width: 3px;
            height: 14px;
            background-color: var(--accent-gold);
        }}
        h1.main-title {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 2.8rem;
            line-height: 1.1;
            font-weight: 800;
            color: var(--color-title);
            letter-spacing: -0.02em;
            margin-bottom: 1.25rem;
        }}
        .description {{
            font-size: 1.05rem;
            line-height: 1.6;
            color: #64748b;
            max-width: 650px;
            margin-bottom: 2.5rem;
        }}

        .stats-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 2.5rem;
        }}
        .stat-item {{
            background: #ffffff;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            padding: 0.85rem 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.85rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        }}
        .stat-number {{
            font-size: 1.35rem;
            font-weight: 700;
            color: var(--color-title);
        }}
        .stat-label {{
            font-size: 0.8rem;
            color: #64748b;
            line-height: 1.2;
        }}

        .search-container {{
            margin-bottom: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}
        .search-box {{
            width: 100%;
            background: #ffffff;
            border: 1px solid var(--color-border);
            border-radius: 8px;
            padding: 0.85rem 1rem 0.85rem 2.75rem;
            font-size: 0.95rem;
            color: #1e293b;
            position: relative;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2394a3b8" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>');
            background-repeat: no-repeat;
            background-position: 12px center;
            box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        }}
        .search-box:focus {{ outline: 2px solid var(--accent-teal); }}
        .results-count {{
            font-size: 0.85rem;
            color: #64748b;
            font-weight: 500;
        }}

        .grid-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }}
        .card-item {{
            background: var(--bg-card);
            border: 1px solid var(--color-border);
            border-radius: 10px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }}
        .card-item:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 16px rgba(0,0,0,0.06);
            border-color: #cbd5e1;
        }}
        .card-preview {{
            height: 130px;
            position: relative;
            border-bottom: 1px solid var(--color-border);
            overflow: hidden;
            background: #f8fafc;
        }}
        .card-badge {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(255, 255, 255, 0.95);
            font-size: 0.7rem;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid var(--color-border);
            color: #334155;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            z-index: 2;
        }}
        .card-content {{
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
        }}
        .card-title {{
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 0.4rem;
            line-height: 1.3;
        }}
        .card-title a {{
            color: #0f172a;
            text-decoration: none;
        }}
        .card-title a:hover {{
            color: var(--accent-teal);
        }}
        .card-path {{
            font-size: 0.78rem;
            color: #94a3b8;
            margin-bottom: 1.25rem;
            word-break: break-all;
        }}
        .card-footer {{
            margin-top: auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            padding-top: 0.75rem;
            border-top: 1px solid #f1f5f9;
        }}
        .tags-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
        }}
        .tag {{
            background: #f1f5f9;
            color: #475569;
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }}
        .btn-abrir {{
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--accent-teal);
            text-decoration: none;
            white-space: nowrap;
        }}
        .btn-abrir:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="sub-header">Repositorio de Análisis y Reportes</div>
            <h1 class="main-title">ANÁLISIS Y DATOS</h1>
            <p class="description">Repositorio centralizado de tableros interactivos, reportes metodológicos y análisis documentados.</p>
        </header>

        <section class="stats-bar">
            <div class="stat-item">
                <span class="stat-number" id="total-stat">{total_informes}</span>
                <span class="stat-label">Informes<br>Publicados</span>
            </div>
            <div class="stat-item">
                <span class="stat-number">Hosting</span>
                <span class="stat-label">Plataforma<br>Firebase</span>
            </div>
            <div class="stat-item">
                <span class="stat-number">Activo</span>
                <span class="stat-label">Estado de<br>Sincronización</span>
            </div>
        </section>

        <section class="search-container">
            <input type="text" id="buscador" class="search-box" placeholder="Buscar por título, archivo o palabras clave..." onkeyup="filtrarTarjetas()">
            <div class="results-count" id="contador-resultados">{total_informes} de {total_informes} informes</div>
        </section>

        <main class="grid-cards" id="grid">
            {tarjetas_html}
        </main>
    </div>

    <script>
        const totalOriginal = {total_informes};
        function filtrarTarjetas() {{
            const query = document.getElementById('buscador').value.toLowerCase().trim();
            const tarjetas = document.querySelectorAll('.card-item');
            let visibles = 0;

            tarjetas.forEach(t => {{
                const datos = t.getAttribute('data-busqueda');
                if (datos.includes(query)) {{
                    t.style.display = 'flex';
                    visibles++;
                }} else {{
                    t.style.display = 'none';
                }}
            }});

            document.getElementById('contador-resultados').innerText = `${{visibles}} de ${{totalOriginal}} informes`;
        }}
    </script>
</body>
</html>"""

    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f_out:
        f_out.write(plantilla_html)

    escribir_log(f"Catálogo generado con éxito en: {ARCHIVO_SALIDA}")
    escribir_log(f"Log registrado en: {ARCHIVO_LOG}")

if __name__ == "__main__":
    generar_indice()