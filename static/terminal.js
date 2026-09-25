// Terminal del refugio: arranque del cerebro, situaciones de ejemplo y decisiones de Laya.
"use strict";

const $ = (id) => document.getElementById(id);
const ANCHO_BARRA = 24;

const ui = {
  ejemplos: [],
  actual: null,
  listo: false,
  ocupado: false,
  inicio: Date.now(),
};

// ------------------------------------------------------------------ utilidades
function escapar(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function bloques(p) {
  const llenos = Math.round(Math.max(0, Math.min(1, p)) * ANCHO_BARRA);
  return "█".repeat(llenos) + "░".repeat(ANCHO_BARRA - llenos);
}

const num = (v, d = 2) => Number(v).toFixed(d).replace(".", ",");
const pct = (v) => `${Math.round(v * 100)} %`;

async function api(ruta, cuerpo) {
  const opciones = cuerpo === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  };
  const r = await fetch(ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.detail || `HTTP ${r.status}`);
  return datos;
}

function avisar(texto, error = false) {
  const aviso = $("aviso");
  aviso.textContent = texto;
  aviso.classList.toggle("error", error);
}

// ------------------------------------------------------------------ arranque
const PASOS = [
  { id: "comprobando", texto: "buscar pesos en la caché local" },
  { id: "descargando", texto: "descargar pesos de Hugging Face" },
  { id: "cargando", texto: "montar el cerebro en memoria" },
  { id: "listo", texto: "calentar motores" },
];
const ORDEN_FASES = ["arrancando", "comprobando", "descargando", "cargando", "listo"];

let progresoCarga = 85;

function pintarArranque(s) {
  const fase = s.fase || "arrancando";
  const posicion = ORDEN_FASES.indexOf(fase);
  const bajado = (s.descargados || []).length > 0 || fase === "descargando";

  $("pasos").innerHTML = PASOS.map((paso) => {
    const indice = ORDEN_FASES.indexOf(paso.id);
    let texto = paso.texto;
    if (paso.id === "descargando") {
      if (fase === "descargando") texto += ` (${s.descargado_mb} / ${s.total_mb} MB)`;
      else if (posicion > indice && !bajado) texto = "descargar pesos: ya estaban aquí, sin tocar la red";
    }
    if (paso.id === "cargando" && s.dispositivo) texto += ` (${s.dispositivo})`;
    const hecho = fase === "listo" || posicion > indice;
    const enCurso = fase === paso.id && fase !== "listo";
    const casilla = hecho ? "[✓]" : enCurso ? "[»]" : "[ ]";
    return `<li class="${hecho || enCurso ? "" : "pendiente"}"><span class="casilla">${casilla}</span>${escapar(texto)}</li>`;
  }).join("");

  let porcentaje = 2;
  if (fase === "comprobando") porcentaje = 5;
  if (fase === "descargando") porcentaje = 5 + 75 * Math.min(1, s.descargado_mb / Math.max(1, s.total_mb));
  if (fase === "cargando") porcentaje = progresoCarga = Math.min(99, progresoCarga + 0.6);
  if (fase === "listo") porcentaje = 100;
  $("barra-arranque").style.width = `${porcentaje}%`;
  $("porcentaje").textContent = `${Math.floor(porcentaje)}%`;

  const fallo = $("fallo");
  fallo.hidden = fase !== "error";
  if (fase === "error") fallo.textContent = `CEREBRO: SIN RESPUESTA\n\n${s.error}`;
}

function pintarCabecera(s) {
  const estado = $("estado-cerebro");
  estado.classList.toggle("error", s.fase === "error");
  if (s.listo) {
    estado.textContent = `CEREBRO: LISTO · ${s.defecto} · ${s.dispositivo} · ${s.precision}`;
  } else {
    estado.textContent = `CEREBRO: ${(s.fase || "arrancando").toUpperCase()}`;
  }
}

async function vigilarCerebro() {
  const reloj = setInterval(() => {
    $("segundos").textContent = Math.round((Date.now() - ui.inicio) / 1000);
  }, 250);

  for (;;) {
    let s;
    try {
      s = await api("/api/status");
    } catch {
      s = { fase: "arrancando" };
    }
    pintarArranque(s);
    pintarCabecera(s);
    if (s.listo || s.fase === "error") {
      if (s.listo) {
        ui.listo = true;
        setTimeout(() => $("arranque").classList.add("fuera"), 700);
        actualizarBotones();
      }
      clearInterval(reloj);
      return;
    }
    await new Promise((ok) => setTimeout(ok, 700));
  }
}

// ------------------------------------------------------------------ situaciones
function pintarLista() {
  $("lista-ejemplos").innerHTML = ui.ejemplos.map((e, i) => `
    <li><button type="button" data-i="${i}" aria-current="${e === ui.actual}">
      ${String(i + 1).padStart(2, "0")} ${escapar(e.titulo)}
      <span class="modo">${escapar(e.etiqueta || e.modo)}</span>
    </button></li>`).join("");
}

function seleccionar(ejemplo) {
  ui.actual = ejemplo;
  pintarLista();
  $("titulo-ejemplo").textContent = ejemplo.titulo;
  $("resumen-ejemplo").textContent = ejemplo.resumen || "";
  const horda = ejemplo.modo === "horda";
  $("etiqueta-estado").textContent = horda ? "ESTADOS DE LA HORDA" : "ESTADO";
  $("evaluar").textContent = horda ? "soltarHorda()" : "evaluar()";

  const variantes = ejemplo.variantes || [];
  $("variantes").hidden = !variantes.length;
  $("variantes").innerHTML = variantes.length
    ? '<span class="pista">variantes:</span>' + variantes.map((v, i) =>
      `<button type="button" class="variante" data-v="${i}">${escapar(v.nombre)}</button>`).join("")
    : "";
  if (variantes.length) {
    elegirVariante(0);
  } else {
    cargarDatos(horda ? ejemplo.states : ejemplo.state, ejemplo.questions);
  }
}

function elegirVariante(i) {
  const v = ui.actual.variantes[i];
  document.querySelectorAll(".variante").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === String(i))));
  cargarDatos(v.state ?? ui.actual.state, v.questions ?? ui.actual.questions);
}

function cargarDatos(estado, preguntas) {
  $("estado").value = typeof estado === "string" ? estado : JSON.stringify(estado, null, 2);
  $("preguntas").value = JSON.stringify(preguntas, null, 2);
  pintarPreguntas();
  $("resultados").innerHTML = '<p class="vacio">&gt; esperando órdenes_</p>';
  $("meta").textContent = "";
  avisar("");
}

function leerPreguntas() {
  try {
    const preguntas = JSON.parse($("preguntas").value);
    if (!preguntas || typeof preguntas !== "object" || Array.isArray(preguntas)) throw new Error();
    return preguntas;
  } catch {
    throw new Error("Las preguntas no son un JSON válido (un objeto con una entrada por pregunta).");
  }
}

function leerEstado() {
  const texto = $("estado").value.trim();
  if (ui.actual?.modo === "horda") {
    let estados;
    try { estados = JSON.parse(texto); } catch { estados = null; }
    if (!Array.isArray(estados) || !estados.length) {
      throw new Error("La horda tiene que ser una lista JSON con un estado por zombi.");
    }
    return estados;
  }
  if (texto.startsWith("{") || texto.startsWith("[")) {
    try { return JSON.parse(texto); } catch { /* texto libre que empieza por llave: se envía tal cual */ }
  }
  return texto;
}

function preguntaBarajable(preguntas) {
  const preferida = ui.actual?.question_id;
  if (preferida && preguntas[preferida]?.type === "choice") return preferida;
  return Object.keys(preguntas).find((id) => preguntas[id].type === "choice");
}

function pintarPreguntas() {
  let preguntas;
  try {
    preguntas = leerPreguntas();
  } catch (e) {
    $("preguntas-vista").innerHTML = `<p class="aviso error">${escapar(e.message)}</p>`;
    actualizarBotones();
    return;
  }
  $("preguntas-vista").innerHTML = Object.entries(preguntas).map(([id, q]) => {
    let opciones = "";
    const c = q.criteria;
    if (q.type === "choice" && c) {
      const lista = Array.isArray(c) ? c.map((k) => [k, ""]) : Object.entries(c);
      opciones = lista.map(([k, v]) => `<li><b>${escapar(k)}</b>${v ? `: ${escapar(v)}` : ""}</li>`).join("");
    } else if (q.type === "score" && Array.isArray(c)) {
      opciones = c.map((v, i) => `<li><b>${i}</b>: ${escapar(v)}</li>`).join("");
    } else if (q.type === "noul" && c) {
      opciones = ["true", "false"].filter((k) => c[k])
        .map((k) => `<li><b>${k === "true" ? "sí" : "no"}</b>: ${escapar(c[k])}</li>`).join("");
    }
    return `<div class="pregunta">
      <span class="id">${escapar(id)}</span><span class="tipo">${escapar(q.type)}</span>
      <p>${escapar(q.instructions)}</p>
      ${opciones ? `<ul>${opciones}</ul>` : ""}
    </div>`;
  }).join("");
  actualizarBotones();
}

function actualizarBotones() {
  let barajable = false;
  try { barajable = Boolean(preguntaBarajable(leerPreguntas())); } catch { /* JSON a medio escribir */ }
  const activo = ui.listo && !ui.ocupado && ui.actual;
  $("evaluar").disabled = !activo;
  $("barajar").disabled = !activo || !barajable || ui.actual?.modo === "horda";
}

// ------------------------------------------------------------------ resultados
function filaProbabilidad(nombre, p, elegida) {
  return `<div class="fila ${elegida ? "elegida" : ""}">
    <span class="nombre">${escapar(nombre)}</span>
    <span class="bloques">${bloques(p)}</span>
    <span class="valor">${num(p)}</span>
  </div>`;
}

function pintarRespuesta(id, r, pregunta) {
  let veredicto = "";
  let cuerpo = "";
  if (r.type === "choice") {
    veredicto = r.choice;
    cuerpo = Object.entries(r.probabilities).map(([k, p]) => filaProbabilidad(k, p, k === r.choice)).join("");
  } else if (r.type === "score") {
    const niveles = Object.keys(r.probabilities).length;
    veredicto = `${num(r.score)} de ${niveles - 1}`;
    cuerpo = Object.entries(r.probabilities).map(([k, p]) =>
      filaProbabilidad(`${k} · ${r.legend?.[k] ?? ""}`, p, Math.round(r.score) === Number(k))).join("");
    cuerpo += '<p class="detalle">valor esperado: la media de los niveles pesada por su probabilidad</p>';
  } else if (r.type === "noul") {
    veredicto = r.noul >= 0.5 ? "SÍ" : "NO";
    cuerpo = filaProbabilidad("P(verdadero)", r.noul, true);
  }

  let sello = "";
  const umbral = ui.actual?.umbral;
  if (umbral && umbral.question === id) {
    const automatico = r.answer_confidence >= umbral.min;
    sello = automatico
      ? `<span class="sello">DECIDE LA MÁQUINA (≥ ${num(umbral.min)})</span>`
      : `<span class="sello alerta">REVISIÓN HUMANA (&lt; ${num(umbral.min)})</span>`;
  }

  return `<section class="respuesta">
    <div class="titular">
      <span>${escapar(id)} <span class="pista">· ${escapar(pregunta?.instructions || "")}</span></span>
      <span class="pista">seguridad ${pct(r.answer_confidence ?? r.confidence)}</span>
    </div>
    <div class="veredicto">${escapar(veredicto)}</div>
    ${cuerpo}
    ${sello ? `<p>${sello}</p>` : ""}
  </section>`;
}

function pintarDecision(datos, preguntas) {
  $("resultados").innerHTML = Object.entries(datos.answers)
    .map(([id, r]) => pintarRespuesta(id, r, preguntas[id])).join("");
  const ruta = datos.routing || {};
  $("meta").textContent = `${datos.latency_ms} ms · ${ruta.model || "?"}`;
  $("meta").title = ruta.reason || "";
}

function pintarBarajado(datos, preguntas) {
  const primera = datos.resultados[0].eleccion;
  const filas = datos.resultados.map((r, i) => `
    <tr>
      <td>${i === 0 ? "original" : i === 1 ? "invertido" : `baraja ${i - 1}`}</td>
      <td>${escapar(r.orden.join(" · "))}</td>
      <td class="${r.eleccion !== primera ? "distinta" : ""}">${escapar(r.eleccion)}</td>
      <td>${num(r.probabilidad)}</td>
    </tr>`).join("");
  const total = datos.resultados.length;
  const sello = datos.estable
    ? `<span class="sello">ESTABLE: la misma respuesta en ${total} de ${total} órdenes</span>`
    : `<span class="sello alerta">CAMBIA DE OPINIÓN en ${datos.cambios} de ${total} órdenes</span>`;
  $("resultados").innerHTML = `
    <p>${sello}</p>
    <p class="detalle">Pregunta <b>${escapar(datos.pregunta)}</b>: ${escapar(preguntas[datos.pregunta]?.instructions || "")}</p>
    <table class="tabla">
      <thead><tr><th>ronda</th><th>orden de las opciones</th><th>elige</th><th>prob.</th></tr></thead>
      <tbody>${filas}</tbody>
    </table>`;
  $("meta").textContent = `${total} rondas`;
}

function pintarHorda(datos, preguntas, estados) {
  const id = preguntaBarajable(preguntas) || Object.keys(preguntas)[0];
  const recuento = {};
  const filas = datos.resultados.map((res, i) => {
    const r = res.answers[id];
    const valor = r.type === "choice" ? r.choice : r.type === "score" ? num(r.score) : (r.noul >= 0.5 ? "SÍ" : "NO");
    const p = r.type === "choice" ? r.probabilities[r.choice] : r.answer_confidence;
    recuento[valor] = (recuento[valor] || 0) + 1;
    const e = estados[i];
    const percibe = typeof e === "string" ? e : Object.values(e ?? {}).join(" · ");
    return `<tr><td>zombi ${String(i + 1).padStart(2, "0")}</td><td class="percibe" title="${escapar(percibe)}">${escapar(percibe)}</td><td>${escapar(valor)}</td><td>${num(p)}</td></tr>`;
  }).join("");
  const n = datos.resultados.length;
  const resumen = Object.entries(recuento).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => filaProbabilidad(`${k} (${v})`, v / n, false)).join("");

  let tiempos = "";
  if (datos.uno_a_uno_ms) {
    const max = Math.max(datos.lote_ms, datos.uno_a_uno_ms);
    tiempos = `<section class="respuesta">
      <div class="titular"><span>tiempo total para ${n} zombis</span></div>
      <div class="fila"><span class="nombre">en lote</span><span class="bloques">${bloques(datos.lote_ms / max)}</span><span class="valor">${Math.round(datos.lote_ms)} ms</span></div>
      <div class="fila"><span class="nombre">uno a uno</span><span class="bloques">${bloques(datos.uno_a_uno_ms / max)}</span><span class="valor">${Math.round(datos.uno_a_uno_ms)} ms</span></div>
      <p class="detalle">${num(datos.lote_ms_por_estado, 1)} ms por zombi en lote, ${num(datos.uno_a_uno_ms_por_estado, 1)} ms uno a uno</p>
    </section>`;
  }

  $("resultados").innerHTML = `
    <section class="respuesta">
      <div class="titular"><span>${escapar(id)} <span class="pista">· ${escapar(preguntas[id]?.instructions || "")}</span></span></div>
      ${resumen}
    </section>
    ${tiempos}
    <table class="tabla"><thead><tr><th>zombi</th><th>percibe</th><th>decisión</th><th>prob.</th></tr></thead><tbody>${filas}</tbody></table>`;
  $("meta").textContent = `${n} zombis · ${Math.round(datos.lote_ms)} ms`;
}

// ------------------------------------------------------------------ acciones
async function ejecutar(accion) {
  if (ui.ocupado) return;
  let preguntas, estado;
  try {
    preguntas = leerPreguntas();
    estado = leerEstado();
  } catch (e) {
    avisar(e.message, true);
    return;
  }

  ui.ocupado = true;
  actualizarBotones();
  avisar(accion === "barajar" ? "barajando opciones..." : "pensando (es un decir)...");
  try {
    if (accion === "barajar") {
      const datos = await api("/api/permute", {
        state: estado, questions: preguntas, question_id: preguntaBarajable(preguntas), rondas: 8,
      });
      pintarBarajado(datos, preguntas);
    } else if (ui.actual?.modo === "horda") {
      pintarHorda(await api("/api/horde", { states: estado, questions: preguntas }), preguntas, estado);
    } else {
      pintarDecision(await api("/api/predict", { state: estado, questions: preguntas }), preguntas);
    }
    avisar("");
  } catch (e) {
    avisar(e.message, true);
  } finally {
    ui.ocupado = false;
    actualizarBotones();
  }
}

// ------------------------------------------------------------------ arranque de la página
$("lista-ejemplos").addEventListener("click", (ev) => {
  const boton = ev.target.closest("button[data-i]");
  if (boton) seleccionar(ui.ejemplos[Number(boton.dataset.i)]);
});

$("variantes").addEventListener("click", (ev) => {
  const boton = ev.target.closest("button[data-v]");
  if (boton) elegirVariante(Number(boton.dataset.v));
});

$("alternar-json").addEventListener("click", () => {
  const editando = $("preguntas").hidden;
  $("preguntas").hidden = !editando;
  $("preguntas-vista").hidden = editando;
  $("alternar-json").textContent = editando ? "[ver resumen]" : "[editar JSON]";
  if (!editando) pintarPreguntas();
});

$("preguntas").addEventListener("input", () => actualizarBotones());
$("evaluar").addEventListener("click", () => ejecutar("evaluar"));
$("barajar").addEventListener("click", () => ejecutar("barajar"));
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) ejecutar("evaluar");
});

(async () => {
  vigilarCerebro();
  try {
    ui.ejemplos = await api("/api/examples");
    if (ui.ejemplos.length) seleccionar(ui.ejemplos[0]);
  } catch (e) {
    avisar(`No se pudieron cargar las situaciones: ${e.message}`, true);
  }
})();
