"""Genera situaciones etiquetadas del refugio para calibrar y entrenar a Laya.

Cada situación se construye a partir de la respuesta correcta: primero se elige qué debería
decidirse (atacar, cuarentena...) y después se redacta un estado coherente con esa decisión,
sacando las frases de unas listas. Así las clases quedan equilibradas y la etiqueta nunca
depende de la opinión de nadie.

Las listas de frases se reparten en dos mitades. Con las posiciones pares se escriben el
entrenamiento y la validación de la LoRA; con las impares, la calibración y la prueba (con
situaciones distintas). Así la prueba mide si el modelo ha aprendido la regla o solo las frases,
y la calibración se hace con frases que el modelo no ha visto al entrenar: con las de
entrenamiento, una LoRA que las acierta todas «aprendería» a estar aún más segura.

Las preguntas se leen de `ejemplos/`, las mismas que usa la terminal, para que no se desincronicen.

Uso:
    python -m entrenamiento.generar_datos            # escribe entrenamiento/datos/*.jsonl
"""
import argparse
import json
import random
from pathlib import Path
from typing import Any, Callable, Dict, List

RAIZ = Path(__file__).resolve().parent.parent
DATOS = Path(__file__).resolve().parent / "datos"


def preguntas_de(fichero: str) -> Dict[str, Any]:
    with open(RAIZ / "ejemplos" / fichero, encoding="utf-8") as f:
        return json.load(f)["questions"]


# ------------------------------------------------------------------ frases
# Al menos cuatro por lista, para que las dos mitades tengan variedad.

LADOS = ["a la izquierda", "a la derecha", "detrás", "delante", "junto a los coches", "cerca de la rampa"]

RUIDOS = [
    "chapa golpeada con fuerza", "una botella rueda por la acera", "cristales rotos",
    "una alarma de coche", "un portazo", "una persiana que cae de golpe",
    "un contenedor volcado", "un neumático que revienta",
]
SIN_RUIDO = [
    "ninguno", "silencio total", "no se oye nada", "calma absoluta",
    "nada, solo silencio", "ningún sonido",
]
OLOR_INTENSO = [
    "sudor humano, fresco e intenso", "olor fuerte a persona viva, muy reciente",
    "sangre fresca de una persona herida, muy intensa", "colonia barata y sudor, recién dejados",
    "olor penetrante a humano vivo", "sudor de miedo, fresco y fuerte",
]
OLOR_DEBIL = [
    "rastro débil de sudor humano, de hace horas", "un leve olor a persona, casi disipado",
    "restos de olor humano, viejos y difusos", "olor tenue a humano, arrastrado por el viento",
    "rastro antiguo de alguien que pasó por aquí", "un olor humano muy flojo y lejano",
]
OLOR_NO_HUMANO = [
    "carne podrida", "humo de un incendio lejano", "gasolina derramada", "basura acumulada",
    "perro muerto", "goma quemada",
]
SIN_OLOR = ["ninguno", "nada en particular", "aire limpio", "no huele a nada", "ningún olor", "nada"]
LUCES = [
    "atardecer, se ve poco", "pleno día, buena visibilidad", "noche cerrada",
    "amanecer con niebla", "nublado, luz gris", "farolas rotas, casi a oscuras",
]
PRESA_LEJOS = [
    "unos {n} metros", "al otro lado de la calle, a unos {n} metros", "a {n} metros, tras una valla",
    "lejos, a unos {n} metros", "en el edificio de enfrente, a {n} metros", "a unos {n} metros, alejándose",
]
PRESA_CERCA = [
    "unos {n} metros", "a {n} metros, sin obstáculos", "muy cerca, a {n} metros",
    "a apenas {n} metros", "a {n} metros, de espaldas", "pegado al coche, a {n} metros",
]
SIN_PRESA = [
    "no hay nadie cerca", "nadie a la vista", "ninguna presa visible",
    "no se ve a nadie", "nada que perseguir", "ni rastro de presas",
]

ASPECTO_SANO = [
    "mujer adulta, ropa limpia, camina con normalidad", "hombre joven, agotado, con una mochila",
    "pareja de mediana edad, con buen color de cara", "anciano con bastón, lúcido y despierto",
    "chica de unos veinte años, sucia pero ágil", "hombre corpulento, sudoroso tras la caminata",
]
ASPECTO_INFECTADO = [
    "hombre mayor, piel gris y mirada vidriosa", "mujer con la piel amarillenta y la mirada perdida",
    "chico con venas oscuras en el cuello", "hombre con la piel cenicienta y los labios negros",
    "mujer que se tambalea, con los ojos en blanco", "adolescente pálido, con espasmos",
]
SIN_HERIDAS = [
    "ninguna visible", "sin heridas", "ninguna, solo cansancio", "una cicatriz antigua ya curada",
    "nada, salvo algún moratón viejo", "ninguna herida a la vista",
]
HERIDA_SIN_EXPLICAR = [
    "arañazo reciente en la mejilla, no sabe decir cómo se lo hizo",
    "sangre en la manga que no quiere explicar",
    "herida tapada con un trapo, cambia de tema al preguntarle",
    "venda con sangre seca en el antebrazo, no dice de qué es",
    "corte reciente en la mano, da versiones distintas",
    "rasguños en el cuello que dice no recordar",
]
MORDEDURA = [
    "dentellada en el cuello", "mordisco en el antebrazo, con los bordes amoratados",
    "mordedura reciente en la pantorrilla", "media luna de dientes en el hombro",
    "mordisco en la mano, todavía sangrando", "marca de dientes humanos en la muñeca",
]
HABLA_NORMAL = [
    "conversa con soltura y pide algo de comer", "trae un salvoconducto del refugio del instituto",
    "responde a todas las preguntas con calma", "está nerviosa pero contesta a todo",
    "bromea con la guardia y pregunta por comida", "explica de dónde viene con todo detalle",
]
COMPORTAMIENTO_INFECTADO = [
    "no dice nada, gruñe y aporrea la reja", "emite sonidos guturales y no reacciona a su nombre",
    "se lanza contra la reja sin decir nada", "babea y no parece entender las preguntas",
    "chilla de forma inconexa y araña la puerta", "mira al vacío y solo gruñe",
]
COMPANIA = [
    "sin compañía", "nadie más", "con un perro", "con su hermano, sin heridas",
    "con su madre, que está ilesa", "con dos niños pequeños",
]


def elige(azar: random.Random, frases: List[str], parte: str) -> str:
    """Una frase de la mitad que toca: pares para entrenar, impares para calibrar y probar."""
    mitad = frases[1::2] if parte == "no-vistas" else frases[0::2]
    return azar.choice(mitad)


# ------------------------------------------------------------------ dominios

def zombi(azar: random.Random, parte: str) -> Dict[str, Any]:
    """El zombi del parking: accion (choice), hambre (score) y humano_cerca (noul)."""
    accion = azar.choice(["atacar", "seguir", "ignorar", "vagar"])
    # «ignorar» exige algún ruido y «vagar» ninguno; en el resto, a veces sí y a veces no.
    hay_ruido = accion == "ignorar" or (accion != "vagar" and azar.random() < 0.5)
    if hay_ruido:
        ruido = "%s a unos %d metros, %s" % (elige(azar, RUIDOS, parte), azar.randint(5, 40),
                                             elige(azar, LADOS, parte))
    else:
        ruido = elige(azar, SIN_RUIDO, parte)

    if accion == "atacar":
        olor = elige(azar, OLOR_INTENSO, parte)
        presa = elige(azar, PRESA_CERCA, parte).format(n=azar.randint(2, 8))
    elif accion == "seguir":
        # Hay rastro humano, pero lejos o poco claro.
        if azar.random() < 0.5:
            olor = elige(azar, OLOR_DEBIL, parte)
            presa = azar.choice([elige(azar, SIN_PRESA, parte),
                                 elige(azar, PRESA_LEJOS, parte).format(n=azar.randint(25, 90))])
        else:
            olor = elige(azar, OLOR_INTENSO, parte)
            presa = elige(azar, PRESA_LEJOS, parte).format(n=azar.randint(25, 90))
    else:
        olor = elige(azar, azar.choice([SIN_OLOR, OLOR_NO_HUMANO]), parte)
        presa = elige(azar, SIN_PRESA, parte)

    estado = {"ruido": ruido, "olor": olor, "luz": elige(azar, LUCES, parte), "distancia_presa": presa}
    return {
        "dominio": "zombi",
        "state": estado,
        "questions": preguntas_de("01-zombi-parking.json"),
        "respuestas": {
            "accion": accion,
            "hambre": {"atacar": 2, "seguir": 1}.get(accion, 0),
            "humano_cerca": accion in ("atacar", "seguir"),
        },
    }


def puerta(azar: random.Random, parte: str) -> Dict[str, Any]:
    """La puerta norte: decision (choice) y mordedura (noul)."""
    decision = azar.choice(["admitir", "cuarentena", "rechazar"])
    mordedura = False
    if decision == "admitir":
        aspecto, heridas, conducta = ASPECTO_SANO, SIN_HERIDAS, HABLA_NORMAL
    elif decision == "cuarentena":
        aspecto, heridas, conducta = ASPECTO_SANO, HERIDA_SIN_EXPLICAR, HABLA_NORMAL
    else:
        # Rechazo por mordedura visible, por conducta de infectado o por las dos cosas.
        mordedura = azar.random() < 0.5
        heridas = MORDEDURA if mordedura else azar.choice([SIN_HERIDAS, HERIDA_SIN_EXPLICAR])
        if mordedura and azar.random() < 0.5:
            aspecto, conducta = ASPECTO_SANO, HABLA_NORMAL
        else:
            aspecto, conducta = ASPECTO_INFECTADO, COMPORTAMIENTO_INFECTADO

    estado = {
        "aspecto": elige(azar, aspecto, parte),
        "heridas": elige(azar, heridas, parte),
        "comportamiento": elige(azar, conducta, parte),
        "compania": elige(azar, COMPANIA, parte),
    }
    return {
        "dominio": "puerta",
        "state": estado,
        "questions": preguntas_de("04-puerta-norte.json"),
        "respuestas": {"decision": decision, "mordedura": mordedura},
    }


DOMINIOS: List[Callable[[random.Random, str], Dict[str, Any]]] = [zombi, puerta]

# Las variantes de los ejemplos del artículo, etiquetadas a mano. Nunca se entrena con ellas.
ETIQUETAS_ARTICULO = {
    ("01-zombi-parking.json", "sudor a 8 metros"): {"accion": "atacar", "hambre": 2, "humano_cerca": True},
    ("01-zombi-parking.json", "solo una lata"): {"accion": "ignorar", "hambre": 0, "humano_cerca": False},
    ("04-puerta-norte.json", "la de la venda"): {"decision": "cuarentena", "mordedura": False},
    ("04-puerta-norte.json", "el de la carta"): {"decision": "admitir", "mordedura": False},
    ("04-puerta-norte.json", "el que gruñe"): {"decision": "rechazar", "mordedura": True},
    ("04-puerta-norte.json", "la niña del arañazo"): {"decision": "cuarentena", "mordedura": False},
}


def casos_articulo() -> List[Dict[str, Any]]:
    casos = []
    for (fichero, variante), respuestas in ETIQUETAS_ARTICULO.items():
        with open(RAIZ / "ejemplos" / fichero, encoding="utf-8") as f:
            ejemplo = json.load(f)
        estado = next(v["state"] for v in ejemplo["variantes"] if v["nombre"] == variante)
        casos.append({"dominio": Path(fichero).stem, "variante": variante, "state": estado,
                      "questions": ejemplo["questions"], "respuestas": respuestas})
    return casos


def generar(n: int, parte: str, semilla: int) -> List[Dict[str, Any]]:
    azar = random.Random(semilla)
    return [DOMINIOS[i % len(DOMINIOS)](azar, parte) for i in range(n)]


def escribir(ruta: Path, casos: List[Dict[str, Any]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        for caso in casos:
            f.write(json.dumps(caso, ensure_ascii=False) + "\n")
    print(f"{ruta.relative_to(RAIZ)}: {len(casos)} situaciones")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--entrenamiento", type=int, default=800)
    p.add_argument("--validacion", type=int, default=300)
    p.add_argument("--calibracion", type=int, default=300)
    p.add_argument("--prueba", type=int, default=300)
    p.add_argument("--semilla", type=int, default=1)
    a = p.parse_args()

    escribir(DATOS / "entrenamiento.jsonl", generar(a.entrenamiento, "entrenamiento", a.semilla))
    escribir(DATOS / "validacion.jsonl", generar(a.validacion, "entrenamiento", a.semilla + 1000))
    escribir(DATOS / "calibracion.jsonl", generar(a.calibracion, "no-vistas", a.semilla + 3000))
    escribir(DATOS / "prueba.jsonl", generar(a.prueba, "no-vistas", a.semilla + 2000))
    escribir(DATOS / "articulo.jsonl", casos_articulo())


if __name__ == "__main__":
    main()
