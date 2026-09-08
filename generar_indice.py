import os
import sys
from datetime import datetime

CARPETA_PUBLIC = "public"
ARCHIVO_SALIDA = os.path.join(CARPETA_PUBLIC, "index.html")
ARCHIVO_LOG = "generar_indice.log"
DOMINIO_BASE = "https://dashboard-datos.web.app"

def escribir_log(mensaje):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {mensaje}\n"
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f_log:
        f_log.write(linea)
    print(mensaje)

def generar_indice():
    # Inicializar log
    with open(ARCHIVO_LOG, "w", encoding="utf-8") as f_log:
        f_log.write(f"--- REGISTRO DE GENERACION DE INDICE HTML ---\n")
        f_log.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    escribir_log(f"Iniciando escaneo en carpeta: {CARPETA_PUBLIC}")

    if not os.path.exists(CARPETA_PUBLIC):
        escribir_log(f"ERROR: La carpeta '{CARPETA_PUBLIC}' no existe.")
        sys.exit(1)

    # Buscar archivos .html recursivamente, ignorando index.html
    archivos_encontrados = []
    for raiz, _, archivos in os.walk(CARPETA_PUBLIC):
        for arch in archivos:
            if arch.lower().endswith(".html") and arch.lower() != "index.html":
                ruta_completa = os.path.join(raiz, arch)
                ruta_relativa = os.path.relpath(ruta_completa, CARPETA_PUBLIC).replace("\\", "/")
                archivos_encontrados.append(ruta_relativa)

    escribir_log(f"Archivos encontrados para indexar: {len(archivos_encontrados)}")
    for item in archivos_encontrados:
        escribir_log(f" - Detectado: {item} -> {DOMINIO_BASE}/{item}")

    archivos_encontrados.sort()

    # Construir filas de enlaces HTML
    filas_html = ""
    for ruta in archivos_encontrados:
        nombre_legible = ruta.replace(".html", "").replace("_", " ").replace("-", " ").title()
        url_completa = f"{DOMINIO_BASE}/{ruta}"
        filas_html += f"""
        <li class="item-informe">
            <a href="{ruta}" target="_blank" class="titulo">{nombre_legible}</a>
            <div class="meta">
                <span class="archivo">{ruta}</span>
                <a href="{url_completa}" target="_blank" class="link-web">{url_completa}</a>
            </div>
        </li>"""

    # Plantilla HTML con diseno limpio y buscador interactivo
    html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Directorio de Informes</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2.5rem 1rem; margin: 0; }}
        .contenedor {{ max-width: 800px; margin: auto; }}
        header {{ margin-bottom: 2rem; border-bottom: 1px solid #334155; padding-bottom: 1rem; }}
        h1 {{ margin: 0 0 0.5rem 0; font-size: 1.75rem; color: #38bdf8; }}
        p {{ margin: 0; color: #94a3b8; font-size: 0.95rem; }}
        #buscador {{ width: 100%; box-sizing: border-box; padding: 0.75rem 1rem; font-size: 1rem; border-radius: 8px; border: 1px solid #334155; background: #1e293b; color: #fff; margin-bottom: 1.5rem; }}
        #buscador:focus {{ outline: 2px solid #38bdf8; }}
        ul {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.75rem; }}
        .item-informe {{ background: #1e293b; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #334155; transition: border-color 0.2s; }}
        .item-informe:hover {{ border-color: #38bdf8; }}
        .titulo {{ color: #f1f5f9; text-decoration: none; font-size: 1.1rem; font-weight: 600; display: block; margin-bottom: 0.35rem; }}
        .titulo:hover {{ color: #38bdf8; }}
        .meta {{ display: flex; flex-wrap: wrap; gap: 1rem; font-size: 0.82rem; color: #64748b; }}
        .link-web {{ color: #0ea5e9; text-decoration: none; }}
        .link-web:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="contenedor">
        <header>
            <h1>Directorio de Informes</h1>
            <p>Repositorio de análisis y tableros publicados en Firebase Hosting</p>
        </header>

        <input type="text" id="buscador" placeholder="Buscar informe..." onkeyup="filtrarInformes()">

        <ul id="lista">
            {filas_html}
        </ul>
    </div>

    <script>
        function filtrarInformes() {{
            const input = document.getElementById('buscador').value.toLowerCase();
            const items = document.querySelectorAll('.item-informe');
            items.forEach(item => {{
                const texto = item.innerText.toLowerCase();
                item.style.display = texto.includes(input) ? '' : 'none';
            }});
        }}
    </script>
</body>
</html>"""

    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f_out:
        f_out.write(html_contenido)

    escribir_log(f"Archivo generado exitosamente: {ARCHIVO_SALIDA}")
    escribir_log(f"Log registrado en: {ARCHIVO_LOG}")

if __name__ == "__main__":
    generar_indice()