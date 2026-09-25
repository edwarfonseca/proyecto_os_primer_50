"""Gráficas SVG sin dependencias externas (sólo la biblioteca estándar).

Cada gráfica es un SVG autocontenido: modo claro y oscuro (prefers-color-scheme),
tooltips nativos (<title>) en cada punto o barra, leyenda cuando hay dos o más series y
etiqueta directa al final de cada línea. Paleta categórica validada para daltonismo
(orden fijo: azul, naranja, aguamarina, amarillo). Líneas de 2 px, marcadores de radio 4
con anillo del color de fondo, barras de 20 px con extremo redondeado y cuadrícula fina.
"""

import math
from xml.sax.saxutils import escape

ANCHO = 720
FUENTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'

CLARO = dict(fondo="#fcfcfb", tinta="#0b0b0b", tinta2="#52514e", tenue="#898781",
             rejilla="#e1e0d9", eje="#c3c2b7", s1="#2a78d6", s2="#eb6834", s3="#1baf7a",
             s4="#eda100")
OSCURO = dict(fondo="#1a1a19", tinta="#ffffff", tinta2="#c3c2b7", tenue="#898781",
              rejilla="#2c2c2a", eje="#383835", s1="#3987e5", s2="#d95926", s3="#199e70",
              s4="#c98500")


def _reglas(c: dict) -> str:
    # Colores directos por clase (sin variables CSS): librsvg, el motor de rsvg-convert y de
    # varios visores de imágenes, no entiende var(); los navegadores entienden ambas formas.
    return (f".fondo{{fill:{c['fondo']}}} .titulo{{fill:{c['tinta']}}} "
            f".subtitulo,.etiqueta{{fill:{c['tinta2']}}} .marca{{fill:{c['tenue']}}} "
            f".valor{{fill:{c['tinta']}}} .rejilla{{stroke:{c['rejilla']}}} "
            f".eje{{stroke:{c['eje']}}} .punto{{stroke:{c['fondo']}}} " +
            " ".join(f".l{i}{{stroke:{c[f's{i}']}}} .f{i}{{fill:{c[f's{i}']}}}" for i in range(1, 5)))


ESTILO = f"""<style>
  text {{ font-family: {FUENTE}; }}
  .titulo {{ font-size: 16px; font-weight: 600; }}
  .subtitulo {{ font-size: 12px; }}
  .marca {{ font-size: 11px; font-variant-numeric: tabular-nums; }}
  .etiqueta {{ font-size: 12px; }}
  .valor {{ font-size: 12px; font-weight: 600; }}
  .rejilla, .eje {{ stroke-width: 1; }}
  .linea {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
  .punto {{ stroke-width: 2; }}
  {_reglas(CLARO)}
  @media (prefers-color-scheme: dark) {{ {_reglas(OSCURO)} }}
</style>"""


def paso_limpio(maximo: float, marcas: int = 5) -> float:
    """Paso de 1, 2 o 5 x 10^k para que el eje tenga números redondos."""
    if maximo <= 0:
        return 1.0
    bruto = maximo / marcas
    base = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 5, 10):
        if bruto <= m * base:
            return m * base
    return 10 * base


def decimales_de(paso: float) -> int:
    """Decimales que necesita un paso de eje (0.5 -> 1, 0.25 -> 2, 5 -> 0)."""
    d = 0
    while abs(paso * 10 ** d - round(paso * 10 ** d)) > 1e-9 and d < 4:
        d += 1
    return d


def fmt(v: float, decimales: int | None = None) -> str:
    if decimales is None:
        decimales = 0 if float(v).is_integer() else (1 if abs(v) >= 10 else 2)
    return f"{v:,.{decimales}f}".replace(",", " ")


def _texto(x, y, contenido, clase, ancla="start", extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" class="{clase}" text-anchor="{ancla}" {extra}>'
            f"{escape(str(contenido))}</text>")


def _cabecera(alto, titulo, subtitulo):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" class="viz" viewBox="0 0 {ANCHO} {alto}" '
            f'width="{ANCHO}" height="{alto}" role="img" aria-label="{escape(titulo)}">',
            ESTILO, f'<rect class="fondo" width="{ANCHO}" height="{alto}" rx="8"/>',
            f"<title>{escape(titulo)}</title>",
            _texto(24, 30, titulo, "titulo"), _texto(24, 49, subtitulo, "subtitulo")]


def lineas(ruta, titulo, subtitulo, x, series, eje_x, eje_y, x_etiquetas=None,
           numerico=False, marcadores=True, decimales=None):
    """Gráfica de líneas.

    x: valores del eje x. series: [(nombre, [y o None por cada x])], máximo 4 (slots 1-4).
    numerico=False: x ordinal (posiciones equiespaciadas); True: escala lineal.
    """
    alto = 420
    izq, der, arr, aba = 70, 170, 96, 58
    ancho_p, alto_p = ANCHO - izq - der, alto - arr - aba
    ys = [v for _, vals in series for v in vals if v is not None]
    paso = paso_limpio(max(ys) * 1.05 if ys else 1)
    y_max = paso * math.ceil((max(ys) if ys else 1) / paso) or paso

    if numerico:
        x0, x1 = (0 if min(x) >= 0 else min(x)), max(x)   # el eje parte de 0
        px = lambda v: izq + (v - x0) / ((x1 - x0) or 1) * ancho_p
    else:
        px = lambda v: izq + (x.index(v) + 0.5) * ancho_p / len(x)
    py = lambda v: arr + alto_p - v / y_max * alto_p

    s = _cabecera(alto, titulo, subtitulo)
    if len(series) >= 2:                               # leyenda: identidad sin depender del color
        lx = 24
        for i, (nombre, _) in enumerate(series, 1):
            s.append(f'<line x1="{lx}" y1="68" x2="{lx + 16}" y2="68" class="linea l{i}"/>')
            s.append(_texto(lx + 22, 72, nombre, "etiqueta"))
            lx += 34 + 7 * len(nombre)
    v = 0.0
    while v <= y_max + 1e-9:                            # rejilla horizontal y marcas del eje y
        y = py(v)
        s.append(f'<line x1="{izq}" y1="{y:.1f}" x2="{izq + ancho_p}" y2="{y:.1f}" '
                 f'class="{"eje" if v == 0 else "rejilla"}"/>')
        s.append(_texto(izq - 8, y + 4, fmt(v, decimales_de(paso)), "marca", "end"))
        v += paso
    etiquetas_x = x_etiquetas or [fmt(v) for v in x]
    if numerico and len(x) > 12:                        # series de tiempo: pocas marcas limpias
        paso_x = paso_limpio(x1 - x0, 6)
        marcas = [x0 + k * paso_x for k in range(int((x1 - x0) / paso_x + 1e-9) + 1)]
        for v in marcas:
            s.append(_texto(px(v), alto - aba + 20, fmt(v, decimales_de(paso_x)), "marca",
                            "middle"))
    else:
        for v, etq in zip(x, etiquetas_x):
            s.append(_texto(px(v), alto - aba + 20, etq, "marca", "middle"))
    s.append(_texto(izq + ancho_p / 2, alto - 14, eje_x, "etiqueta", "middle"))
    s.append(_texto(18, arr + alto_p / 2, eje_y, "etiqueta", "middle",
                    f'transform="rotate(-90 18 {arr + alto_p / 2:.1f})"'))

    finales = []
    for i, (nombre, vals) in enumerate(series, 1):
        pts = [(px(xv), py(yv), xv, yv) for xv, yv in zip(x, vals) if yv is not None]
        if not pts:
            continue
        d = " ".join(f"{'M' if k == 0 else 'L'}{a:.1f},{b:.1f}" for k, (a, b, _, _) in enumerate(pts))
        s.append(f'<path d="{d}" class="linea l{i}"/>')
        visibles = pts if marcadores else pts[-1:]
        for a, b, xv, yv in visibles:
            s.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="4" class="punto f{i}">'
                     f"<title>{escape(nombre)} · {eje_x}: {fmt(xv)} · {eje_y}: "
                     f"{fmt(yv, decimales)}</title></circle>")
        finales.append((pts[-1][1], f"{nombre}: {fmt(pts[-1][3], decimales)}", pts[-1][0]))
    # Etiquetas directas al final de cada línea; si chocan, se deja sólo la leyenda.
    finales.sort()
    if all(b[0] - a[0] >= 15 for a, b in zip(finales, finales[1:])):
        for y, etq, xf in finales:
            s.append(_texto(xf + 10, y + 4, etq, "valor"))
    s.append("</svg>")
    ruta.write_text("\n".join(s), encoding="utf-8")


def barras(ruta, titulo, subtitulo, categorias, valores, eje, decimales=None, sufijo=""):
    """Barras horizontales de una sola serie (slot 1), con el valor en el extremo."""
    banda, grosor = 38, 20
    izq, der, arr, aba = 190, 90, 72, 50
    alto = arr + banda * len(categorias) + aba
    ancho_p = ANCHO - izq - der
    paso = paso_limpio(max(valores) * 1.05 if max(valores) > 0 else 1)
    x_max = paso * math.ceil(max(max(valores), paso) / paso)
    px = lambda v: izq + v / x_max * ancho_p

    s = _cabecera(alto, titulo, subtitulo)
    base_y = arr + banda * len(categorias)
    v = 0.0
    while v <= x_max + 1e-9:
        s.append(f'<line x1="{px(v):.1f}" y1="{arr - 6}" x2="{px(v):.1f}" y2="{base_y}" '
                 f'class="{"eje" if v == 0 else "rejilla"}"/>')
        s.append(_texto(px(v), base_y + 18, fmt(v, decimales_de(paso)), "marca", "middle"))
        v += paso
    s.append(_texto(izq + ancho_p / 2, alto - 12, eje, "etiqueta", "middle"))
    for k, (cat, val) in enumerate(zip(categorias, valores)):
        y0 = arr + k * banda + (banda - grosor) / 2
        y1 = y0 + grosor
        x0, x1 = px(0), px(val)
        s.append(_texto(izq - 10, y0 + grosor / 2 + 4, cat, "etiqueta", "end"))
        if val > 0:
            r = min(4, (x1 - x0) / 2)                  # extremo de datos redondeado, base recta
            d = (f"M{x0:.1f},{y0:.1f} H{x1 - r:.1f} Q{x1:.1f},{y0:.1f} {x1:.1f},{y0 + r:.1f} "
                 f"V{y1 - r:.1f} Q{x1:.1f},{y1:.1f} {x1 - r:.1f},{y1:.1f} H{x0:.1f} Z")
            s.append(f'<path d="{d}" class="f1"><title>{escape(cat)}: '
                     f"{fmt(val, decimales)}{sufijo}</title></path>")
        s.append(_texto(max(x1, x0) + 8, y0 + grosor / 2 + 4, f"{fmt(val, decimales)}{sufijo}",
                        "valor"))
    s.append("</svg>")
    ruta.write_text("\n".join(s), encoding="utf-8")
