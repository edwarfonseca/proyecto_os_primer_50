// Demostración gráfica del centro de despacho: consulta /api/estado periódicamente y
// dibuja cada panel. Sin dependencias externas (funciona sin conexión a internet).
"use strict";

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v) => (v === "" || v == null ? null : Number(v));
const fmt = (v, dec = 0) => (v == null || Number.isNaN(v) ? "—" :
  Number(v).toLocaleString("es-CO", { minimumFractionDigits: dec, maximumFractionDigits: dec }));

// Preferencias del visitante (tema, notas): sólo comodidad, el almacenamiento puede fallar.
const pref = {
  leer(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  guardar(k, v) { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } },
};

let PASOS = [];
let ultimo = null;          // último /api/estado
let vista = "vivo";
let congelarArbol = false;  // no redibujar el árbol mientras se presiona un botón de señal
const cache = {};           // último HTML de cada panel (evita redibujar si no cambió)

// --- API -----------------------------------------------------------------------------

async function api(url, cuerpo) {
  const r = await fetch(url, cuerpo === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
  });
  const datos = await r.json();
  if (!r.ok) throw new Error(datos.error || `error ${r.status}`);
  return datos;
}

function avisar(texto) {
  const a = $("#aviso");
  a.textContent = texto;
  a.hidden = false;
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => { a.hidden = true; }, 6000);
}

async function ejecutar(escenario, params) {
  try {
    await api("/api/ejecutar", { escenario, params });
    mostrarVista("vivo");
    refrescar();
  } catch (e) { avisar(e.message); }
}

async function senal(pid, nombre) {
  try { await api("/api/senal", { pid, senal: nombre }); refrescar(); } catch (e) { avisar(e.message); }
}

// --- guion y formulario ----------------------------------------------------------------

function dibujarPasos() {
  $("#pasos").innerHTML = PASOS.map((p) => `
    <li class="paso" data-paso="${p.paso}">
      <h3>${p.paso}. ${esc(p.titulo)}</h3>
      <div class="req">Requisitos: ${esc(p.requisitos)}</div>
      <div class="botones">${p.escenarios.map((e) =>
        `<button data-escenario="${e.id}" title="python3 main.py ${esc(e.args.join(" "))}">
           ${esc(e.nombre)}</button>`).join("")}</div>
      <div class="notas">
        <p><b>Qué observar:</b> ${esc(p.observar)}</p>
        <p><b>Qué decir:</b> ${esc(p.decir)}</p>
      </div>
    </li>`).join("");
}

const ETIQUETAS = {
  "-w": "Trabajadores", "-t": "Hilos por trabajador", "-g": "Generadores",
  "-n": "Solicitudes (0 = continuo)", "--tam-rafaga": "Tamaño de ráfaga",
  "--intervalo": "Entre ráfagas (s)", "-k": "Capacidad de la cola", "-v": "Vehículos",
  "--ventana": "Ventana (s)", "-a": "Andenes", "-i": "Inspectores", "-p": "Puntos por ruta",
  "--traza-kb": "Traza (KB)", "--historial": "Historial (0 = sin límite)", "-s": "Semilla",
  "--reintento": "Reintento (s)", "--modo": "Modo", "--espera": "Espera",
  "--interbloqueo": "Interbloqueo", "--cola": "Cola", "--seccion": "Sección crítica",
};
const DEFECTOS = {
  "-w": 2, "-t": 3, "-g": 2, "-n": 20, "--tam-rafaga": 0, "--intervalo": 1, "-k": 10, "-v": 3,
  "--ventana": 0.01, "-a": 2, "-i": 1, "-p": 7, "--traza-kb": 64, "--historial": 50, "-s": 42,
  "--reintento": 0.005,
};

function dibujarFormulario(permitidos) {
  const campos = Object.entries(permitidos).map(([bandera, def]) => {
    const etq = ETIQUETAS[bandera] || bandera;
    if (def.tipo === "opcion") {
      return `<label>${esc(etq)}<select name="${bandera}">${def.rango[0].map((o) =>
        `<option>${esc(o)}</option>`).join("")}</select></label>`;
    }
    const paso = def.tipo === "float" ? "any" : "1";
    return `<label>${esc(etq)}<input type="number" name="${bandera}" min="${def.rango[0]}"
      max="${def.rango[1]}" step="${paso}" value="${DEFECTOS[bandera] ?? ""}"></label>`;
  });
  $("#form-personalizado").innerHTML = campos.join("") + `<button type="submit">Ejecutar</button>`;
}

// --- actualización periódica -------------------------------------------------------------

async function refrescar() {
  clearTimeout(refrescar.t);
  try {
    ultimo = await api("/api/estado");
    dibujar(ultimo);
  } catch (e) {
    $("#ejecucion").innerHTML = `<span class="estado critico">Sin conexión con el servidor</span>`;
  }
  const activa = ultimo?.ejecucion?.activa;
  refrescar.t = setTimeout(refrescar, activa ? 700 : 2000);
}

function dibujar(d) {
  const ej = d.ejecucion;
  dibujarCabecera(ej);
  document.querySelectorAll("#pasos button").forEach((b) => { b.disabled = !!ej?.activa; });
  $("#form-personalizado button").disabled = !!ej?.activa;
  document.querySelectorAll(".paso").forEach((li) =>
    li.classList.toggle("actual", !!ej && Number(li.dataset.paso) === ej.paso));
  $("#n-historial").textContent = d.historial.filter((h) => h.exit != null).length || "";
  if (vista === "comparar") { dibujarComparacion(d.historial); return; }
  if (!ej) return;
  dibujarTiles(d.monitor);
  dibujarResumen(ej);
  if (!congelarArbol) dibujarArbol(d.procesos, ej, d.ciclos);
  dibujarFlota(d.monitor, d.conflictos);
  dibujarCiclo(d.ciclos, ej);
  dibujarEventos(d);
  dibujarGraficas(d.series);
  const err = d.stderr.length ? d.stderr.join("\n") : "—";
  if ($("#stderr").textContent !== err) $("#stderr").textContent = err;
}

function poner(id, html) {
  if (cache[id] === html) return;
  cache[id] = html;
  $(id).innerHTML = html;
}

// --- cabecera --------------------------------------------------------------------------

function dibujarCabecera(ej) {
  $("#btn-detener").disabled = $("#btn-forzar").disabled = !ej?.activa;
  if (!ej) { poner("#ejecucion", `<span class="estado">Sin ejecución</span>`); return; }
  const estado = ej.activa ? `<span class="estado activa">En ejecución</span>`
    : `<span class="estado ${ej.exit === 0 ? "bien" : "critico"}">Terminó · código ${ej.exit}</span>`;
  poner("#ejecucion", `${estado}<span class="detalle"><b>${esc(ej.nombre)}</b> · ${ej.duracion} s ·
    PID ${ej.pid}</span><code title="${esc(ej.args)}">${esc(ej.log)}</code>`);
}

// --- indicadores del monitor -------------------------------------------------------------

function dibujarTiles(m) {
  const t = (etq, valor, sub = "") =>
    `<div class="tile"><div class="etiqueta">${etq}</div><div class="valor">${valor}</div>
     <div class="sub">${sub}</div></div>`;
  if (!m) { poner("#tiles", t("Monitor", "—", "esperando la primera muestra")); return; }
  poner("#tiles", [
    t("Recibidas", fmt(m.recibidas)),
    t("En cola", fmt(m.en_cola), "pendientes"),
    t("En proceso", fmt(m.en_proceso), `esperando vehículo: ${m.esperando_vehiculo}`),
    t("Vehículos asignados", `${m.asignados} / ${m.asignados + m.disponibles}`,
      `${m.disponibles} disponibles`),
    t("Finalizadas", fmt(m.finalizadas), `${m.entregadas} entregadas · ${m.canceladas} canceladas`),
    t("Rendimiento", fmt(m.rendimiento, 1), "solicitudes/s"),
  ].join(""));
}

// --- resultado final -------------------------------------------------------------------

const METRICAS = [
  ["tiempo_total_s", "Tiempo total", (v) => `${fmt(v, 2)} s`],
  ["rendimiento", "Rendimiento", (v) => `${fmt(v, 2)} sol/s`],
  ["entregadas", "Entregadas", (v, m) => `${fmt(v)} de ${fmt(num(m.generadas))}`],
  ["dobles_sonda", "Dobles asignaciones", (v) => fmt(v), (v) => v > 0],
  ["inconsistencias", "Registros inconsistentes", (v) => fmt(v), (v) => v > 0],
  ["en_ruta_max", "Entregas simultáneas máx.", (v, m) =>
    `${fmt(v)} con ${fmt(num(m.vehiculos))} vehículos`, (v, m) => v > num(m.vehiculos)],
  ["espera_vehiculo_ms", "Espera por vehículo", (v) => `${fmt(v)} ms`],
  ["cpu_trabajadores_s", "CPU de los trabajadores", (v, m) =>
    `${fmt(v, 2)} s (${fmt(num(m.cpu_trabajadores_pct), 1)} %)`],
  ["real_cpu_rutas", "Real / CPU por ruta", (v) => fmt(v, 2)],
  ["interbloqueos", "Interbloqueos detectados", (v, m) =>
    `${fmt(v)} (${fmt(num(m.recuperaciones))} recuperados)`, (v, m) => m.interbloqueo_sin_resolver],
  ["reintentos_timeout", "Reintentos por tiempo límite", (v) => fmt(v)],
  ["reintentos_sondeo", "Reintentos de sondeo", (v) => fmt(v)],
  ["ctx_voluntarios", "Cambios de contexto", (v, m) =>
    `${fmt(v)} vol. · ${fmt(num(m.ctx_involuntarios))} invol.`],
  ["pss_total_mb", "Memoria PSS total", (v) => `${fmt(v, 1)} MB`],
  ["alertas_sin_progreso", "Alertas sin progreso", (v) => fmt(v), (v) => v > 0],
];

function dibujarResumen(ej) {
  const panel = $("#panel-resumen");
  panel.hidden = ej.activa || !ej.metricas;
  if (panel.hidden) return;
  const m = ej.metricas;
  const veredicto = ej.exit === 0
    ? `<span class="insignia bien">✔ Correcto</span> El sistema terminó sin detectar resultados incorrectos.`
    : `<span class="insignia critico">✖ Con fallos</span> El sistema detectó un resultado incorrecto
       (código de salida ${ej.exit}).`;
  const tarjetas = METRICAS.filter(([k]) => num(m[k]) != null).map(([k, etq, f, alarma]) => {
    const v = num(m[k]);
    const mal = alarma && alarma(v, m);
    return `<div class="metrica"><div class="etiqueta">${etq}</div>
      <div class="valor">${f(v, m)}</div>${mal ? `<span class="insignia critico">✖ problema</span>` : ""}</div>`;
  });
  poner("#resumen", `<div class="veredicto">${veredicto}</div><div class="metricas">${tarjetas.join("")}</div>`);
}

// --- procesos e hilos (vista del SO) -----------------------------------------------------

const ESTADOS = { R: "ejecutando", S: "dormido", D: "E/S", T: "detenido", Z: "zombi", I: "inactivo" };

function espera(wchan) {
  if (wchan === "-") return "en CPU";
  if (wchan.startsWith("futex")) return "espera lock/semáforo";
  if (wchan.startsWith("hrtimer_nanosleep")) return "duerme (tiempo)";
  if (wchan.startsWith("poll_schedule")) return "espera datos (pipe)";
  if (wchan.startsWith("do_signal_stop")) return "detenido (SIGSTOP)";
  if (wchan.startsWith("pipe_")) return "espera pipe";
  if (wchan.startsWith("do_wait")) return "espera a un hijo";
  return wchan;
}

function dibujarArbol(procesos, ej, ciclos) {
  // Hilos del último interbloqueo sin resolver: se resaltan también en el árbol.
  const c = ciclos[ciclos.length - 1];
  const enCiclo = new Set(c && !c.victima ? c.nodos.map((n) => n.hilo) : []);
  if (!ej.activa) {
    poner("#arbol", `<p class="vacio">La ejecución terminó: no quedan procesos (ni zombis) en /proc.</p>`);
    return;
  }
  poner("#arbol", procesos.map((p, i) => {
    const st = p.estado[0];
    const insignia = st === "T" ? `<span class="insignia aviso">⏸ detenido</span>`
      : st === "Z" ? `<span class="insignia critico">✖ zombi</span>` : "";
    const hilos = p.hilos.map((h) => `
      <span class="hilo ${h.estado} ${enCiclo.has(h.nombre) ? "en-ciclo" : ""}" title="TID ${h.tid} · ${ESTADOS[h.estado] || h.estado} · wchan ${esc(h.wchan)}">
        <span class="st">${h.estado}</span>${esc(h.nombre)}
        <span class="espera">${esc(espera(h.wchan))}${h.cpu > 0 ? ` · ${fmt(h.cpu)} %` : ""}</span>
      </span>`).join("");
    const senales = i === 0 ? "" : `<div class="senales">
      <button data-pid="${p.pid}" data-senal="STOP" title="kill -STOP ${p.pid}">⏸ Detener</button>
      <button data-pid="${p.pid}" data-senal="CONT" title="kill -CONT ${p.pid}">▶ Reanudar</button>
      <button data-pid="${p.pid}" data-senal="USR1" title="kill -USR1 ${p.pid}: pila de sus hilos">Pila</button>
      <button data-pid="${p.pid}" data-senal="KILL" title="kill -KILL ${p.pid}">✖ Matar</button></div>`;
    return `<div class="proceso ${i ? "hijo" : ""} ${st === "T" ? "detenido" : ""}">
      <div class="proceso-cab"><span class="nombre">${esc(p.nombre)}</span>
        <span class="ids">PID ${p.pid} · PPID ${p.ppid} · ${p.hilos.length} hilos</span>${insignia}
        <span class="recursos">CPU ${fmt(p.cpu)} % · RSS ${fmt(p.rss_mb, 1)} MB · PSS ${fmt(p.pss_mb, 1)} MB</span>
      </div>${senales}<div class="hilos">${hilos}</div></div>`;
  }).join("") || `<p class="vacio">Arrancando…</p>`);
}

// --- flota -------------------------------------------------------------------------------

const MAX_TARJETAS = 12;   // con flotas grandes (escenarios aislados) sólo se muestran los ocupados

function dibujarFlota(m, conflictos) {
  if (!m) return;
  let flota = m.flota, nota = "";
  if (flota.length > MAX_TARJETAS) {
    const visibles = flota.filter((v) => v.solicitud || conflictos[v.vehiculo]).slice(0, MAX_TARJETAS);
    nota = `<p class="nota flota-nota">${flota.length} vehículos (flota amplia para aislar el fenómeno
      de este paso): ${m.asignados} asignados, ${m.disponibles} libres. Se muestran sólo los ocupados.</p>`;
    flota = visibles;
  }
  poner("#flota", nota + flota.map((v) => {
    const c = conflictos[v.vehiculo];
    const reciente = c && c.hace < 3;
    return `<div class="vehiculo ${v.solicitud ? "ocupado" : ""} ${reciente ? "conflicto" : ""}">
      <div class="id">${v.vehiculo}</div>
      <div class="sol">${v.solicitud ? `Solicitud ${v.solicitud}` : "Libre"}</div>
      ${reciente ? `<span class="insignia critico">✖ Doble asignación</span>
        <div class="conflictos">sol. ${c.nueva} sobre ${c.previa} (${esc(c.ambito)})</div>` : ""}
      ${c ? `<div class="conflictos">${c.total} conflicto${c.total > 1 ? "s" : ""} en total</div>` : ""}
    </div>`;
  }).join(""));
}

// --- grafo de espera ---------------------------------------------------------------------

function dibujarCiclo(ciclos, ej) {
  if (!ciclos.length) {
    poner("#ciclo", `<p class="vacio">Sin interbloqueos detectados${ej.activa ? " (el vigilante revisa cada 0.5 s)" : ""}.</p>`);
    return;
  }
  const c = ciclos[ciclos.length - 1];
  // Nodos alternados en un círculo: hilo_0, recurso que espera, hilo_1, recurso que espera…
  const nodos = [];
  c.nodos.forEach((n) => { nodos.push({ tipo: "hilo", nombre: n.hilo }); nodos.push({ tipo: "recurso", nombre: n.espera }); });
  const W = 420, H = 300, cx = W / 2, cy = 150, R = 90, r = 26;
  const pos = nodos.map((_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / nodos.length;
    return [cx + R * Math.cos(a) * 1.5, cy + R * Math.sin(a)];
  });
  const aristas = nodos.map((n, i) => {
    const [x1, y1] = pos[i], [x2, y2] = pos[(i + 1) % nodos.length];
    const d = Math.hypot(x2 - x1, y2 - y1), ux = (x2 - x1) / d, uy = (y2 - y1) / d;
    const etq = n.tipo === "hilo" ? "espera" : "asignado a";
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    return `<line class="arista" x1="${x1 + ux * r}" y1="${y1 + uy * r}" x2="${x2 - ux * (r + 6)}"
      y2="${y2 - uy * (r + 6)}" marker-end="url(#punta)"/>
      <text class="etq" x="${mx + uy * 14}" y="${my - ux * 14}" text-anchor="middle">${etq}</text>`;
  }).join("");
  const figuras = nodos.map((n, i) => {
    const [x, y] = pos[i];
    const victima = n.tipo === "hilo" && n.nombre === c.victima ? " (víctima)" : "";
    return n.tipo === "hilo"
      // El nombre va por fuera del círculo: arriba en la mitad superior, abajo en la inferior.
      ? `<circle class="hilo-nodo" cx="${x}" cy="${y}" r="${r}"/><text x="${x}"
          y="${y < cy ? y - r - 8 : y + r + 16}" text-anchor="middle">${esc(n.nombre)}${victima}</text>`
      : `<rect class="recurso-nodo" x="${x - r}" y="${y - 18}" width="${2 * r}" height="36" rx="6"/>
         <text x="${x}" y="${y + 4}" text-anchor="middle">${esc(n.nombre)}</text>`;
  }).join("");
  const texto = c.nodos.map((n) => `<b>${esc(n.hilo)}</b> tiene ${esc(n.tiene)} y espera ${esc(n.espera)}`).join("; ");
  const estado = c.victima
    ? `<span class="insignia bien">✔ Recuperado</span> la víctima ${esc(c.victima)} soltó lo que retenía.`
    : `<span class="insignia critico">✖ Espera circular</span> ninguno puede avanzar; con esta
       estrategia el sistema se detiene.`;
  poner("#ciclo", `<svg class="grafo ${c.victima ? "resuelto" : ""}" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="Grafo de espera: ${esc(texto)}">
      <defs><marker id="punta" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7"
        orient="auto-start-reverse"><path class="punta" d="M0,0 L10,5 L0,10 z"/></marker></defs>
      ${aristas}${figuras}</svg>
    <div class="ciclo-texto">${esc(c.hora)} · ${texto}.<br>${estado}</div>`);
}

// --- eventos -----------------------------------------------------------------------------

const SEVERIDAD = { critico: "✖", serio: "▲", aviso: "!", bien: "✔" };

function dibujarEventos(d) {
  const lista = ($("#chk-todos").checked ? d.eventos : d.importantes).slice(-80).reverse();
  poner("#eventos", lista.map((e) => `<li>
      <span class="hora">${esc(e.hora.slice(0, 11))}</span>
      <span class="quien" title="${esc(e.proceso)} · PID ${e.pid} · TID ${e.tid}">${esc(e.hilo === "MainThread" ? e.proceso : e.hilo)}</span>
      <span class="msg">${SEVERIDAD[e.severidad] ? `<span class="insignia ${e.severidad}">${SEVERIDAD[e.severidad]} ${esc(e.categoria)}</span> ` : ""}${esc(e.msg)}</span>
    </li>`).join("") || `<li class="vacio">Sin eventos todavía.</li>`);
}

// --- gráficas ----------------------------------------------------------------------------

function pasoLimpio(maximo, marcas = 4) {
  if (maximo <= 0) return 1;
  const bruto = maximo / marcas, base = 10 ** Math.floor(Math.log10(bruto));
  return [1, 2, 5, 10].map((m) => m * base).find((p) => bruto <= p);
}

// series: [{nombre, clase (1-4), corto, puntos: [[x, y], ...]}]
function graficaLineas(cont, { series, ejeX, ejeY, dec = 0 }) {
  const con = series.filter((s) => s.puntos.length);
  if (!con.length) { cont.innerHTML = `<p class="vacio">Esperando datos…</p>`; return; }
  const W = Math.max(cont.clientWidth, 300), H = 220, m = { i: 46, d: 92, a: 8, b: 34 };
  const xs = con.flatMap((s) => s.puntos.map((p) => p[0]));
  const ys = con.flatMap((s) => s.puntos.map((p) => p[1]));
  const x0 = 0, x1 = Math.max(...xs, 1);
  const pasoY = pasoLimpio(Math.max(...ys, 1) * 1.05), y1 = pasoY * Math.ceil(Math.max(...ys, pasoY) / pasoY);
  const px = (x) => m.i + ((x - x0) / (x1 - x0)) * (W - m.i - m.d);
  const py = (y) => m.a + (1 - y / y1) * (H - m.a - m.b);
  let svg = "";
  for (let y = 0; y <= y1 + 1e-9; y += pasoY) {
    svg += `<line class="${y === 0 ? "eje-l" : "rejilla-l"}" x1="${m.i}" x2="${W - m.d}" y1="${py(y)}" y2="${py(y)}"/>
      <text x="${m.i - 6}" y="${py(y) + 4}" text-anchor="end">${fmt(y, pasoY < 1 ? 1 : 0)}</text>`;
  }
  const pasoX = pasoLimpio(x1 - x0, 5);
  for (let x = 0; x <= x1 + 1e-9; x += pasoX) {
    svg += `<text x="${px(x)}" y="${H - m.b + 16}" text-anchor="middle">${fmt(x, pasoX < 1 ? 1 : 0)}</text>`;
  }
  svg += `<text class="titulo-eje" x="${m.i + (W - m.i - m.d) / 2}" y="${H - 4}" text-anchor="middle">${esc(ejeX)}</text>
    <text class="titulo-eje" transform="translate(11 ${m.a + (H - m.a - m.b) / 2}) rotate(-90)" text-anchor="middle">${esc(ejeY)}</text>`;
  const finales = [];
  con.forEach((s) => {
    svg += `<path class="linea c${s.clase}" d="${s.puntos.map((p, i) => `${i ? "L" : "M"}${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join("")}"/>`;
    const u = s.puntos[s.puntos.length - 1];
    finales.push({ y: py(u[1]), x: px(u[0]), s });
  });
  // Etiqueta directa al final de cada línea; si dos chocan, se omiten y queda la leyenda.
  finales.sort((a, b) => a.y - b.y);
  const separadas = finales.every((f, i) => i === 0 || f.y - finales[i - 1].y >= 13);
  finales.forEach((f) => {
    svg += `<circle class="punto f${f.s.clase}" cx="${f.x}" cy="${f.y}" r="4"/>`;
    if (separadas) svg += `<text class="etq-final" x="${f.x + 8}" y="${f.y + 4}">${esc(f.s.corto || f.s.nombre)}</text>`;
  });
  svg += `<g class="cursor" visibility="hidden"><line class="cruz" y1="${m.a}" y2="${H - m.b}"/>
    ${con.map((s) => `<circle class="punto f${s.clase}" r="4" data-serie="${s.clase}"/>`).join("")}</g>
    <rect class="zona" x="${m.i}" y="${m.a}" width="${W - m.i - m.d}" height="${H - m.a - m.b}" fill="transparent"/>`;
  const leyenda = con.length > 1 ? `<div class="leyenda">${con.map((s) =>
    `<span><i class="f${s.clase}"></i>${esc(s.nombre)}</span>`).join("")}</div>` : "";
  cont.innerHTML = `${leyenda}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(ejeY)} según ${esc(ejeX)}">${svg}</svg>`;

  // Cruz y tooltip: el punto más cercano en x de cada serie.
  const zona = $(".zona", cont), cursor = $(".cursor", cont), tip = $("#tooltip");
  const mover = (clientX) => {
    const caja = cont.querySelector("svg").getBoundingClientRect();
    const x = x0 + (((clientX - caja.left) * (W / caja.width)) - m.i) / (W - m.i - m.d) * (x1 - x0);
    let filas = "", xr = null;
    con.forEach((s) => {
      const p = s.puntos.reduce((a, b) => (Math.abs(b[0] - x) < Math.abs(a[0] - x) ? b : a));
      xr = xr ?? p[0];
      const c = $(`circle[data-serie="${s.clase}"]`, cursor);
      c.setAttribute("cx", px(p[0])); c.setAttribute("cy", py(p[1]));
      filas += `<div class="fila"><i class="f${s.clase}"></i>${esc(s.nombre)}<b>${fmt(p[1], dec)}</b></div>`;
    });
    $(".cruz", cursor).setAttribute("x1", px(xr)); $(".cruz", cursor).setAttribute("x2", px(xr));
    cursor.setAttribute("visibility", "visible");
    tip.innerHTML = `<div>${esc(ejeX)}: <b>${fmt(xr, 1)}</b></div>${filas}`;
    tip.hidden = false;
    const t = tip.getBoundingClientRect();
    tip.style.left = `${Math.min(clientX + 14, innerWidth - t.width - 8)}px`;
    tip.style.top = `${caja.top + 10}px`;
  };
  zona.addEventListener("pointermove", (e) => { cont.dataset.hover = e.clientX; mover(e.clientX); });
  zona.addEventListener("pointerleave", () => { delete cont.dataset.hover; cursor.setAttribute("visibility", "hidden"); tip.hidden = true; });
  if (cont.dataset.hover) mover(Number(cont.dataset.hover));   // conserva el tooltip al actualizar
}

function agrupar(recursos, campo, promedio) {
  const trab = Object.entries(recursos).filter(([n]) => n.startsWith("trabajador"));
  const porT = new Map();
  trab.forEach(([, pts]) => pts.forEach((p) => {
    const a = porT.get(p.t) || [0, 0];
    porT.set(p.t, [a[0] + p[campo], a[1] + 1]);
  }));
  const puntos = [...porT.entries()].sort((a, b) => a[0] - b[0])
    .map(([t, [s, n]]) => [t, promedio ? s / n : s]);
  const serie = (n) => (recursos[n] || []).map((p) => [p.t, p[campo]]);
  return [
    { nombre: promedio ? "Trabajadores (promedio)" : "Trabajadores (suma)", corto: "Trabajadores", clase: 1, puntos },
    { nombre: "Principal (centro_despacho)", corto: "Principal", clase: 2, puntos: serie("centro_despacho") },
    { nombre: "Taller", corto: "Taller", clase: 3, puntos: serie("taller") },
  ];
}

function dibujarGraficas(s) {
  const mon = s.monitor;
  graficaLineas($("#graf-monitor"), {
    ejeX: "tiempo (s)", ejeY: "solicitudes", series: [
      { nombre: "Finalizadas (acumulado)", corto: "Finalizadas", clase: 1, puntos: mon.map((r) => [r.t_s, r.finalizadas]) },
      { nombre: "En cola", corto: "En cola", clase: 2, puntos: mon.map((r) => [r.t_s, r.en_cola]) },
      { nombre: "En proceso", corto: "En proceso", clase: 3, puntos: mon.map((r) => [r.t_s, r.en_proceso]) },
    ],
  });
  graficaLineas($("#graf-cpu"), { ejeX: "tiempo (s)", ejeY: "CPU (%)", series: agrupar(s.recursos, "cpu", false) });
  graficaLineas($("#graf-mem"), { ejeX: "tiempo (s)", ejeY: "RSS (MB)", dec: 1, series: agrupar(s.recursos, "rss", true) });
}

// --- comparación -------------------------------------------------------------------------

const COMPARABLES = [
  ["dobles_sonda", "Dobles asignaciones", 0], ["tiempo_total_s", "Tiempo total (s)", 2],
  ["rendimiento", "Rendimiento (sol/s)", 2], ["en_ruta_max", "Entregas simultáneas máx.", 0],
  ["cpu_trabajadores_s", "CPU de los trabajadores (s)", 2], ["interbloqueos", "Interbloqueos detectados", 0],
  ["espera_vehiculo_ms", "Espera por vehículo (ms)", 0], ["ctx_voluntarios", "Cambios de contexto voluntarios", 0],
  ["pss_total_mb", "Memoria PSS total (MB)", 1], ["real_cpu_rutas", "Real / CPU por ruta", 2],
];

function graficaBarras(cont, categorias, valores, dec) {
  if (!categorias.length) { cont.innerHTML = `<p class="vacio">Aún no hay ejecuciones terminadas con esta métrica.</p>`; return; }
  const W = Math.max(cont.clientWidth, 320), banda = 34, grosor = 20, m = { i: 210, d: 70, a: 6, b: 26 };
  const H = m.a + banda * categorias.length + m.b;
  const paso = pasoLimpio(Math.max(...valores, 1) * 1.05), xmax = paso * Math.ceil(Math.max(...valores, paso) / paso);
  const px = (v) => m.i + (v / xmax) * (W - m.i - m.d);
  let svg = "";
  for (let v = 0; v <= xmax + 1e-9; v += paso) {
    svg += `<line class="${v === 0 ? "eje-l" : "rejilla-l"}" x1="${px(v)}" x2="${px(v)}" y1="${m.a}" y2="${H - m.b}"/>
      <text x="${px(v)}" y="${H - m.b + 16}" text-anchor="middle">${fmt(v, paso < 1 ? 1 : 0)}</text>`;
  }
  categorias.forEach((c, i) => {
    const y0 = m.a + i * banda + (banda - grosor) / 2, x1 = px(valores[i]), x0 = px(0), r = Math.min(4, (x1 - x0) / 2);
    svg += `<text x="${m.i - 8}" y="${y0 + grosor / 2 + 4}" text-anchor="end" class="titulo-eje">${esc(c)}</text>`;
    if (valores[i] > 0) {
      svg += `<path class="f1" d="M${x0},${y0} H${x1 - r} Q${x1},${y0} ${x1},${y0 + r} V${y0 + grosor - r} Q${x1},${y0 + grosor} ${x1 - r},${y0 + grosor} H${x0} Z"><title>${esc(c)}: ${fmt(valores[i], dec)}</title></path>`;
    }
    svg += `<text class="etq-final" x="${Math.max(x1, x0) + 6}" y="${y0 + grosor / 2 + 4}">${fmt(valores[i], dec)}</text>`;
  });
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">${svg}</svg>`;
}

function dibujarComparacion(historial) {
  const hechas = historial.filter((h) => h.exit != null && h.metricas);
  const sel = $("#sel-metrica");
  const [clave, , dec] = COMPARABLES.find(([k]) => k === sel.value) || COMPARABLES[0];
  const conValor = hechas.filter((h) => num(h.metricas[clave]) != null);
  const firma = JSON.stringify([clave, hechas.map((h) => h.numero)]);
  if (cache.comparar === firma) return;
  cache.comparar = firma;
  graficaBarras($("#graf-comparar"), conValor.map((h) => h.nombre), conValor.map((h) => num(h.metricas[clave])), dec);
  const col = (h, k, d = 0) => fmt(num(h.metricas[k]), d);
  $("#tabla-comparar").innerHTML = `<thead><tr><th>Ejecución</th><th>Resultado</th><th>Tiempo (s)</th>
    <th>Rendimiento</th><th>Dobles</th><th>En ruta máx. / vehículos</th><th>CPU trab. (s)</th>
    <th>Interbloqueos</th><th>PSS (MB)</th><th>Parámetros</th></tr></thead><tbody>${hechas.map((h) => `<tr>
      <td>${esc(h.nombre)}</td>
      <td>${h.exit === 0 ? `<span class="insignia bien">✔ correcto</span>` : `<span class="insignia critico">✖ código ${h.exit}</span>`}</td>
      <td class="num">${col(h, "tiempo_total_s", 2)}</td><td class="num">${col(h, "rendimiento", 2)}</td>
      <td class="num">${col(h, "dobles_sonda")}</td>
      <td class="num">${col(h, "en_ruta_max")} / ${col(h, "vehiculos")}</td>
      <td class="num">${col(h, "cpu_trabajadores_s", 2)}</td><td class="num">${col(h, "interbloqueos")}</td>
      <td class="num">${col(h, "pss_total_mb", 1)}</td><td><code>${esc(h.args)}</code></td></tr>`).join("")}</tbody>`;
}

function mostrarVista(v) {
  vista = v;
  history.replaceState(null, "", v === "comparar" ? "#comparar" : location.pathname);
  document.querySelectorAll(".pestanas button").forEach((b) => b.setAttribute("aria-selected", b.dataset.vista === v));
  $("#vista-vivo").hidden = v !== "vivo";
  $("#vista-comparar").hidden = v !== "comparar";
  delete cache.comparar;
  if (ultimo) dibujar(ultimo);
}

// --- inicio ------------------------------------------------------------------------------

async function iniciar() {
  const tema = new URLSearchParams(location.search).get("tema") || pref.leer("tema", null);
  if (tema) document.documentElement.dataset.tema = tema;
  const notas = pref.leer("notas", "1") === "1";
  $("#chk-notas").checked = notas;
  document.body.classList.toggle("con-notas", notas);

  const datos = await api("/api/escenarios");
  PASOS = datos.pasos;
  dibujarPasos();
  dibujarFormulario(datos.permitidos);
  $("#sel-metrica").innerHTML = COMPARABLES.map(([k, etq]) => `<option value="${k}">${etq}</option>`).join("");

  $("#pasos").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-escenario]");
    if (b) ejecutar(b.dataset.escenario);
  });
  $("#form-personalizado").addEventListener("submit", (e) => {
    e.preventDefault();
    ejecutar("personalizado", Object.fromEntries(new FormData(e.target)));
  });
  $("#arbol").addEventListener("pointerdown", () => { congelarArbol = true; });
  addEventListener("pointerup", () => setTimeout(() => { congelarArbol = false; }, 400));
  $("#arbol").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-senal]");
    if (!b) return;
    if (b.dataset.senal === "KILL" && !confirm(`¿Enviar SIGKILL al proceso ${b.dataset.pid}?`)) return;
    senal(Number(b.dataset.pid), b.dataset.senal);
  });
  $("#btn-detener").addEventListener("click", () => api("/api/detener", { forzar: false }).catch((e) => avisar(e.message)));
  $("#btn-forzar").addEventListener("click", () => api("/api/detener", { forzar: true }).catch((e) => avisar(e.message)));
  $("#chk-todos").addEventListener("change", () => ultimo?.ejecucion && dibujarEventos(ultimo));
  $("#chk-notas").addEventListener("change", (e) => {
    document.body.classList.toggle("con-notas", e.target.checked);
    pref.guardar("notas", e.target.checked ? "1" : "0");
  });
  $("#btn-tema").addEventListener("click", () => {
    const oscuro = getComputedStyle(document.documentElement).colorScheme === "dark";
    document.documentElement.dataset.tema = oscuro ? "claro" : "oscuro";
    pref.guardar("tema", document.documentElement.dataset.tema);
    Object.keys(cache).forEach((k) => delete cache[k]);
  });
  document.querySelectorAll(".pestanas button").forEach((b) => b.addEventListener("click", () => mostrarVista(b.dataset.vista)));
  $("#sel-metrica").addEventListener("change", () => { delete cache.comparar; ultimo && dibujarComparacion(ultimo.historial); });
  addEventListener("resize", () => ultimo && dibujar(ultimo));
  if (location.hash === "#comparar") mostrarVista("comparar");
  refrescar();
}

iniciar().catch((e) => avisar(`No se pudo iniciar: ${e.message}`));
