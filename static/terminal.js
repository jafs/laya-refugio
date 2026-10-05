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
  modo: "predict",          // "predict" o "horda": cómo se evalúa lo que hay en pantalla
  confirmarBorrado: null,
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
const zombis = (n) => `${n} ${n === 1 ? "zombi" : "zombis"}`;

async function api(ruta, cuerpo, metodo) {
  const opciones = cuerpo === undefined && !metodo ? {} : {
    method: metodo || "POST",
    headers: { "Content-Type": "application/json" },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  };
  const r = await fetch(ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) {
    // FastAPI devuelve los errores de validación como lista; nos quedamos con los mensajes.
    const detalle = Array.isArray(datos.detail) ? datos.detail.map((d) => d.msg).join("; ") : datos.detail;
    throw new Error(detalle || `HTTP ${r.status}`);
  }
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
    const cerebro = s.cerebro && s.cerebro !== "original" ? s.cerebro : s.defecto;
    const cambio = s.cambio?.en_curso ? ` · cargando ${s.cambio.hacia}...` : "";
    estado.textContent = `CEREBRO: LISTO · ${cerebro}${s.calibracion ? " (calibrado)" : ""} · ${s.dispositivo} · ${s.precision}${cambio}`;
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
  const boton = (e, i, marca) => `
    <li><button type="button" data-i="${i}" aria-current="${e === ui.actual}">
      ${marca} ${escapar(e.titulo)}
      <span class="modo">${escapar(e.etiqueta || (e.modo === "horda" ? "horda" : "una situación"))}</span>
    </button></li>`;
  const fijos = [];
  const propias = [];
  ui.ejemplos.forEach((e, i) => (e.propio ? propias : fijos).push([e, i]));
  $("lista-ejemplos").innerHTML = fijos.map(([e, i], n) => boton(e, i, String(n + 1).padStart(2, "0"))).join("");
  $("lista-propias").innerHTML = propias.map(([e, i]) => boton(e, i, "◆")).join("");
  $("sin-propias").hidden = propias.length > 0;
}

function seleccionar(ejemplo) {
  ui.actual = ejemplo;
  pintarLista();
  $("titulo-ejemplo").textContent = ejemplo.titulo;
  $("resumen-ejemplo").textContent = ejemplo.resumen || "";
  const propia = Boolean(ejemplo.propio);
  $("marca-propia").hidden = !propia;
  $("caja-ejemplo").classList.toggle("es-propia", propia);
  $("guardar").hidden = !propia;
  $("borrar").hidden = !propia || Boolean(ejemplo.nuevo);
  cerrarFormulario();
  reiniciarBorrado();
  ui.modo = ejemplo.modo === "horda" ? "horda" : "predict";
  pintarModo();
  const horda = ui.modo === "horda";

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

function pintarModo() {
  const horda = ui.modo === "horda";
  $("modo-horda").checked = horda;
  $("etiqueta-estado").textContent = horda ? "ESTADOS DE LA HORDA" : "ESTADO";
  $("evaluar").textContent = horda ? "soltarHorda()" : "evaluar()";
  actualizarBotones();
}

// Al pasar a horda, el estado actual se convierte en el primer zombi de la lista; al volver, se
// queda solo el primero.
function cambiarModo(horda) {
  const texto = $("estado").value.trim();
  let valor;
  try { valor = JSON.parse(texto); } catch { valor = texto; }
  if (horda && !Array.isArray(valor)) valor = [valor];
  if (!horda && Array.isArray(valor)) valor = valor[0] ?? "";
  $("estado").value = typeof valor === "string" ? valor : JSON.stringify(valor, null, 2);
  ui.modo = horda ? "horda" : "predict";
  pintarModo();
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
  if (ui.modo === "horda") {
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
  $("barajar").disabled = !activo || !barajable || ui.modo === "horda";
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
      <div class="titular"><span>tiempo total para ${zombis(n)}</span></div>
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
  $("meta").textContent = `${zombis(n)} · ${Math.round(datos.lote_ms)} ms`;
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
    } else if (ui.modo === "horda") {
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

// ------------------------------------------------------------------ modo libre
const PLANTILLA = {
  titulo: "Prueba nueva",
  resumen: "Modo libre: describe lo que se percibe, define tus preguntas y pulsa evaluar(). "
    + "Si el resultado merece la pena, guárdala con guardar().",
  modo: "predict",
  propio: true,
  nuevo: true,
  state: { situacion: "un zombi olfatea la puerta del almacén de comida y empuja con el hombro" },
  questions: {
    decision: {
      type: "choice",
      instructions: "¿Qué hacemos con el almacén?",
      criteria: {
        reforzar: "la puerta aguanta, pero hay riesgo de que ceda",
        evacuar: "la puerta está a punto de ceder o hay muchos zombis",
        ignorar: "no hay peligro real para el almacén",
      },
    },
    peligro: { type: "noul", instructions: "¿Hay peligro inmediato para el refugio?" },
  },
};

function nuevaPrueba() {
  seleccionar(structuredClone(PLANTILLA));
  if ($("preguntas").hidden) $("alternar-json").click();
  $("estado").focus();
}

function abrirFormulario() {
  const a = ui.actual;
  $("campo-titulo").value = a.nuevo ? "" : `${a.titulo} (${a.propio ? "copia" : "mi versión"})`;
  $("campo-resumen").value = a.nuevo ? "" : a.resumen || "";
  $("form-guardar").hidden = false;
  $("campo-titulo").focus();
}

function cerrarFormulario() {
  $("form-guardar").hidden = true;
}

function datosActuales(titulo, resumen) {
  const datos = { titulo, resumen, modo: ui.modo, questions: leerPreguntas() };
  datos[ui.modo === "horda" ? "states" : "state"] = leerEstado();
  // Si partimos de un ejemplo con umbral o con pregunta preferida para barajar, se conservan.
  if (ui.actual?.umbral) datos.umbral = ui.actual.umbral;
  if (ui.actual?.question_id) datos.question_id = ui.actual.question_id;
  return datos;
}

async function guardarPrueba(titulo, resumen, id) {
  let datos;
  try {
    datos = datosActuales(titulo, resumen);
  } catch (e) {
    avisar(e.message, true);
    return;
  }
  try {
    const guardada = await api(id ? `/api/custom/${id}` : "/api/custom", datos, id ? "PUT" : "POST");
    await recargar(guardada.id);
    avisar(`guardada en mis pruebas: ${guardada.titulo}`);
  } catch (e) {
    avisar(`No se pudo guardar: ${e.message}`, true);
  }
}

async function recargar(idPropia) {
  ui.ejemplos = await api("/api/examples");
  const elegida = ui.ejemplos.find((e) => e.propio && e.id === idPropia);
  if (elegida) seleccionar(elegida);
  else pintarLista();
}

function reiniciarBorrado() {
  clearTimeout(ui.confirmarBorrado);
  ui.confirmarBorrado = null;
  $("borrar").textContent = "[borrar()]";
}

async function borrarPrueba() {
  if (!ui.confirmarBorrado) {
    $("borrar").textContent = "[¿seguro? pulsa otra vez]";
    ui.confirmarBorrado = setTimeout(reiniciarBorrado, 4000);
    return;
  }
  reiniciarBorrado();
  const { id, titulo } = ui.actual;
  try {
    await api(`/api/custom/${id}`, undefined, "DELETE");
    await recargar(null);
    seleccionar(ui.ejemplos[0]);
    avisar(`borrada: ${titulo}`);
  } catch (e) {
    avisar(`No se pudo borrar: ${e.message}`, true);
  }
}

// ------------------------------------------------------------------ entrenamiento
const NOMBRE_TRABAJO = { calibrar: "calibrar", lora: "entrenarLoRA", evaluar: "evaluar" };
const SELLOS = {
  en_curso: ["EN CURSO", ""], terminado: ["TERMINADO", ""], error: ["ERROR", "alerta"],
  cancelado: ["CANCELADO", "alerta"], interrumpido: ["INTERRUMPIDO", "alerta"],
};
const entreno = { cerebros: [], seleccionado: null, vigilando: false };

const porcentaje = (v, d = 1) => `${num(v * 100, d)} %`;
const millones = (n) => `${num(n / 1e6, n < 1e7 ? 2 : 0)} M`;

function mostrarVista(vista) {
  const entrenando = vista === "entreno";
  $("vista-pruebas").hidden = entrenando;
  $("vista-entreno").hidden = !entrenando;
  $("abrir-entreno").setAttribute("aria-current", String(entrenando));
  if (entrenando) {
    ui.actual = null;
    pintarLista();
    cargarCerebros();
    consultarEntreno();
  }
}

function nombreCerebro(id, calibrado) {
  return `${id}${calibrado ? " (calibrado)" : ""}`;
}

async function cargarCerebros() {
  let datos;
  try {
    datos = await api("/api/brains");
  } catch (e) {
    $("aviso-cerebro").textContent = e.message;
    return;
  }
  entreno.cerebros = datos.cerebros;
  if (!entreno.cerebros.some((c) => c.id === entreno.seleccionado)) {
    entreno.seleccionado = datos.activo;
    $("cerebro-calibrado").checked = Boolean(datos.calibracion);
  }
  $("cerebro-activo").textContent = `en uso: ${nombreCerebro(datos.activo, datos.calibracion)}`;
  $("lista-cerebros").innerHTML = entreno.cerebros.map((c) => `
    <button type="button" class="cerebro" data-c="${escapar(c.id)}" aria-pressed="${c.id === entreno.seleccionado}">
      <span class="nombre">${c.id === datos.activo ? "● " : ""}${escapar(c.id)}</span>
      <span class="pista">${escapar(c.descripcion)}${c.calibracion ? " · calibración disponible" : " · sin calibrar"}</span>
    </button>`).join("");
  for (const id of ["cal-cerebro", "eval-cerebro"]) {
    const previo = $(id).value;
    $(id).innerHTML = entreno.cerebros.map((c) => `<option value="${escapar(c.id)}">${escapar(c.id)}</option>`).join("");
    if (entreno.cerebros.some((c) => c.id === previo)) $(id).value = previo;
  }
  pintarSeleccionCerebro();
}

function pintarSeleccionCerebro() {
  const elegido = entreno.cerebros.find((c) => c.id === entreno.seleccionado);
  document.querySelectorAll(".cerebro").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.c === entreno.seleccionado)));
  $("cerebro-calibrado").disabled = !elegido?.calibracion;
  if (!elegido?.calibracion) $("cerebro-calibrado").checked = false;
}

async function usarCerebro() {
  const aviso = $("aviso-cerebro");
  aviso.classList.remove("error");
  aviso.textContent = "cambiando de cerebro...";
  $("usar-cerebro").disabled = true;
  try {
    await api("/api/brain", { cerebro: entreno.seleccionado, calibrado: $("cerebro-calibrado").checked });
    // Si cambia el modelo, se carga en segundo plano: la terminal sigue con el anterior mientras.
    for (;;) {
      const s = await api("/api/status");
      pintarCabecera(s);
      if (!s.cambio?.en_curso) {
        if (s.cambio?.error) throw new Error(s.cambio.error);
        aviso.textContent = `en uso: ${nombreCerebro(s.cerebro, s.calibracion)}`;
        break;
      }
      await new Promise((ok) => setTimeout(ok, 700));
    }
  } catch (e) {
    aviso.textContent = e.message;
    aviso.classList.add("error");
  } finally {
    $("usar-cerebro").disabled = false;
    cargarCerebros();
  }
}

function ordenDe(tipo) {
  if (tipo === "calibrar") return { tipo, modelo: $("cal-cerebro").value, dispositivo: $("cal-disp").value };
  if (tipo === "evaluar") {
    return { tipo, modelo: $("eval-cerebro").value, calibrado: $("eval-calibrado").checked, dispositivo: $("eval-disp").value };
  }
  const casos = $("lora-casos").value.trim();
  return {
    tipo, modelo: $("lora-nombre").value.trim(), epocas: Number($("lora-epocas").value),
    rango: Number($("lora-rango").value), max_casos: casos ? Number(casos) : null,
    barajar: $("lora-barajar").checked, dispositivo: $("lora-disp").value,
  };
}

async function lanzarEntreno(tipo) {
  try {
    pintarEntreno(await api("/api/training", ordenDe(tipo)));
    vigilarEntreno();
  } catch (e) {
    $("entreno-meta").textContent = e.message;
  }
}

async function cancelarEntreno() {
  try {
    pintarEntreno(await api("/api/training", undefined, "DELETE"));
  } catch (e) {
    $("entreno-meta").textContent = e.message;
  }
}

async function consultarEntreno() {
  try {
    const e = await api("/api/training");
    pintarEntreno(e);
    if (e.estado === "en_curso") vigilarEntreno();
  } catch { /* el servidor aún no responde: ya lo pintará el siguiente intento */ }
}

async function vigilarEntreno() {
  if (entreno.vigilando) return;
  entreno.vigilando = true;
  try {
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 1000));
      let e;
      try { e = await api("/api/training"); } catch { continue; }
      pintarEntreno(e);
      if (e.estado !== "en_curso") break;
    }
  } finally {
    entreno.vigilando = false;
  }
  // Una LoRA nueva o una calibración nueva aparecen como cerebros disponibles.
  cargarCerebros();
}

// Curva de pérdida en escala logarítmica: cae en picado al principio y luego se arrastra, y en
// escala lineal todo lo interesante quedaría aplastado contra el suelo.
function curva(valores) {
  const ancho = 600;
  const alto = 90;
  const logs = valores.map((v) => Math.log10(Math.max(v, 1e-4)));
  const min = Math.min(...logs);
  const max = Math.max(...logs);
  const rango = max - min || 1;
  const puntos = logs.map((v, i) => `${((i / (logs.length - 1)) * ancho).toFixed(1)},${(4 + (1 - (v - min) / rango) * (alto - 8)).toFixed(1)}`);
  const guias = [0.25, 0.5, 0.75].map((f) => `<line x1="0" x2="${ancho}" y1="${alto * f}" y2="${alto * f}" class="guia"/>`).join("");
  return `<svg class="curva" viewBox="0 0 ${ancho} ${alto}" preserveAspectRatio="none" role="img"
    aria-label="Curva de pérdida">${guias}<polyline points="${puntos.join(" ")}"/></svg>`;
}

function barra(etiqueta, hechas, total, valor) {
  return `<div class="fila"><span class="nombre">${escapar(etiqueta)}</span>
    <span class="bloques">${bloques(hechas / Math.max(1, total))}</span>
    <span class="valor">${escapar(valor ?? `${hechas} / ${total}`)}</span></div>`;
}

function tablaMetricas(m, titulo) {
  const filas = [["TOTAL", m.total], ...Object.entries(m.por_pregunta)].map(([nombre, r]) => `
    <tr class="${nombre === "TOTAL" ? "total" : ""}"><td>${escapar(nombre)}</td><td>${r.n}</td>
    <td>${porcentaje(r.aciertos)}</td><td>${porcentaje(r.seguridad_media)}</td><td>${num(r.ece, 3)}</td></tr>`).join("");
  return `<section class="respuesta"><div class="titular"><span>${escapar(titulo)}</span></div>
    <table class="tabla"><thead><tr><th>pregunta</th><th>n</th><th>aciertos</th><th>seguridad</th><th title="Error de calibración esperado: distancia entre lo seguro que dice estar y lo que acierta de verdad. 0 es perfecto.">ECE</th></tr></thead>
    <tbody>${filas}</tbody></table>
    <p class="detalle">ECE: distancia entre lo seguro que dice estar y lo que acierta (0 es perfecto).</p></section>`;
}

function pintarLora(e) {
  let html = "";
  const epocas = e.orden.epocas;
  if (e.modelo) {
    html += `<p class="detalle">${escapar(e.modelo.dispositivo)} · ${e.modelo.capas} capas con LoRA · `
      + `${millones(e.modelo.entrenables)} entrenables de ${millones(e.modelo.total)} `
      + `(${porcentaje(e.modelo.entrenables / e.modelo.total)}) · ${e.modelo.casos} situaciones</p>`;
  }
  if (e.lote) {
    const l = e.lote;
    const hechos = (l.epoca - 1) * l.lotes + l.lote;
    const restantes = epocas * l.lotes - hechos;
    const eta = e.estado === "en_curso" ? ` · quedan ~${Math.ceil((restantes * l.s_lote) / 60)} min` : "";
    html += barra(`época ${l.epoca} de ${epocas}`, l.lote, l.lotes);
    html += barra("total", hechos, epocas * l.lotes, `${Math.round((100 * hechos) / (epocas * l.lotes))} %`);
    html += `<p class="detalle">pérdida media ${num(l.media, 4)} · ${num(l.s_lote, 2)} s por lote${eta}</p>`;
  }
  if (e.curva.length > 1) {
    html += `<section class="respuesta"><div class="titular"><span>pérdida por lote</span>
      <span class="pista">${num(e.curva[0], 3)} → ${num(e.curva[e.curva.length - 1], 3)} · escala logarítmica</span></div>
      ${curva(e.curva)}</section>`;
  }
  const filas = [];
  if (e.validacion_inicial) filas.push(["antes", null, e.validacion_inicial, null]);
  for (const ep of e.epocas) filas.push([`época ${ep.epoca}`, ep.perdida, ep, ep.segundos]);
  if (filas.length) {
    html += `<table class="tabla"><thead><tr><th>validación</th><th>pérdida</th><th>aciertos</th><th title="Pérdida logarítmica: castiga dar la respuesta correcta con poca seguridad y, sobre todo, fallar muy seguro. Cuanto más baja, mejor.">NLL</th><th title="Error de calibración esperado: distancia entre lo seguro que dice estar y lo que acierta de verdad. 0 es perfecto.">ECE</th><th>tiempo</th></tr></thead><tbody>${
      filas.map(([n, perdida, v, s]) => `<tr><td>${n}</td><td>${perdida == null ? "—" : num(perdida, 4)}</td>
        <td>${porcentaje(v.aciertos)}</td><td>${num(v.nll, 3)}</td><td>${num(v.ece, 3)}</td><td>${s == null ? "—" : `${s} s`}</td></tr>`).join("")
    }</tbody></table><p class="detalle">NLL: pérdida logarítmica, castiga sobre todo fallar muy seguro (más baja, mejor). ECE: distancia entre lo seguro que dice estar y lo que acierta (0 es perfecto).</p><p class="detalle">La validación usa las mismas frases que el entrenamiento, así que un 99 % aquí no es la nota final. Para eso está evaluar().</p>`;
  }
  if (e.fin) {
    html += e.fin.exportado
      ? `<p><span class="sello">EXPORTADO en ${escapar(e.fin.exportado)} · mejor época ${e.fin.mejor_epoca}</span></p>`
      : '<p><span class="sello alerta">NINGUNA ÉPOCA MEJORÓ: no se exporta nada</span></p>';
    html += `<p class="detalle">${num(e.fin.minutos, 1)} min${e.fin.memoria_gpu_mb ? ` · memoria de GPU máxima ${e.fin.memoria_gpu_mb} MB` : ""}. `
      + "Siguiente paso: calibrarlo con frases que no ha visto.</p>";
  }
  return html;
}

function pintarCalibrar(r) {
  return tablaMetricas(r.antes, "prueba SIN calibrar") + tablaMetricas(r.despues, "prueba CALIBRADA")
    + `<p class="detalle">temperaturas (choice, score, noul): ${r.temperaturas.map((t) => num(t, 2)).join(" · ")}`
    + ` · guardado en ${escapar(r.salida)}. Los aciertos no cambian; lo que debe bajar es el ECE.</p>`;
}

function pintarEvaluar(r) {
  const articulo = r.articulo.map((f) => `<tr><td class="${f.ok ? "" : "distinta"}">${f.ok ? "ok" : "MAL"}</td>
    <td>${escapar(f.variante)}</td><td>${escapar(f.pregunta)}</td><td>${escapar(f.dice)}</td><td>${pct(f.seguridad)}</td>
    <td>${f.ok ? "" : escapar(`esperado: ${f.esperado}`)}</td></tr>`).join("");
  const aciertos = r.articulo.filter((f) => f.ok).length;
  const o = r.orden;
  return tablaMetricas(r.metricas, "prueba (frases que no se usan al entrenar)")
    + `<section class="respuesta"><div class="titular"><span>ejemplos del artículo</span><span class="pista">${aciertos} de ${r.articulo.length}</span></div>
      <table class="tabla"><tbody>${articulo}</tbody></table></section>`
    + `<p><span class="sello ${o.proporcion > 0.2 ? "alerta" : ""}">SESGO DE ORDEN: cambia en ${o.cambian} de ${o.preguntas} (${porcentaje(o.proporcion)}) al invertir las opciones</span></p>`;
}

function pintarEntreno(e) {
  const enCurso = e.estado === "en_curso";
  for (const id of ["lanzar-calibrar", "lanzar-lora", "lanzar-evaluar"]) $(id).disabled = enCurso;
  $("cancelar-entreno").hidden = !enCurso;
  if (e.estado === "nada") return;

  const o = e.orden;
  const args = o.tipo === "evaluar" ? `${o.modelo}${o.calibrado ? ", calibrado" : ""}` : o.modelo;
  $("entreno-titulo").textContent = `PROGRESO · ${NOMBRE_TRABAJO[o.tipo]}(${args})`;
  const segundos = e.lanzado ? Math.max(0, Math.round(Date.now() / 1000 - e.lanzado)) : null;
  $("entreno-meta").textContent = enCurso && segundos != null ? `${Math.floor(segundos / 60)} min ${segundos % 60} s` : e.id;

  const [texto, clase] = SELLOS[e.estado] || [e.estado.toUpperCase(), ""];
  let html = `<p><span class="sello ${clase}">${texto}</span>`;
  if (enCurso && e.fase) html += ` <span class="spinner" aria-hidden="true"></span> ${escapar(e.fase)}`;
  html += "</p>";
  if (enCurso && e.avance) html += barra(e.avance.etapa, e.avance.hechas, e.avance.total);
  if (o.tipo === "lora") html += pintarLora(e);
  if (e.resultado && o.tipo === "calibrar") html += pintarCalibrar(e.resultado);
  if (e.resultado && o.tipo === "evaluar") html += pintarEvaluar(e.resultado);
  if (e.registro) {
    html += `<details class="registro" ${e.estado === "error" ? "open" : ""}><summary>registro</summary><pre>${escapar(e.registro)}</pre></details>`;
  }
  $("entreno").innerHTML = html;
}

// ------------------------------------------------------------------ arranque de la página
for (const lista of ["lista-ejemplos", "lista-propias"]) {
  $(lista).addEventListener("click", (ev) => {
    const boton = ev.target.closest("button[data-i]");
    if (boton) {
      mostrarVista("pruebas");
      seleccionar(ui.ejemplos[Number(boton.dataset.i)]);
    }
  });
}

$("nueva").addEventListener("click", () => {
  mostrarVista("pruebas");
  nuevaPrueba();
});
$("abrir-entreno").addEventListener("click", () => mostrarVista("entreno"));
$("lista-cerebros").addEventListener("click", (ev) => {
  const boton = ev.target.closest("button[data-c]");
  if (!boton) return;
  entreno.seleccionado = boton.dataset.c;
  pintarSeleccionCerebro();
});
$("usar-cerebro").addEventListener("click", usarCerebro);
$("lanzar-calibrar").addEventListener("click", () => lanzarEntreno("calibrar"));
$("lanzar-lora").addEventListener("click", () => lanzarEntreno("lora"));
$("lanzar-evaluar").addEventListener("click", () => lanzarEntreno("evaluar"));
$("cancelar-entreno").addEventListener("click", cancelarEntreno);
$("guardar-como").addEventListener("click", abrirFormulario);
$("cancelar").addEventListener("click", cerrarFormulario);
$("borrar").addEventListener("click", borrarPrueba);
$("modo-horda").addEventListener("change", (ev) => cambiarModo(ev.target.checked));
$("guardar").addEventListener("click", () => {
  const a = ui.actual;
  if (a.nuevo) abrirFormulario();
  else guardarPrueba(a.titulo, a.resumen || "", a.id);
});
$("form-guardar").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const titulo = $("campo-titulo").value.trim();
  if (!titulo) return;
  guardarPrueba(titulo, $("campo-resumen").value.trim(), null);
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
  consultarEntreno();
  try {
    ui.ejemplos = await api("/api/examples");
    if (ui.ejemplos.length) seleccionar(ui.ejemplos[0]);
  } catch (e) {
    avisar(`No se pudieron cargar las situaciones: ${e.message}`, true);
  }
})();
