"""
campus.py

Carga el mapa del campus desde campus.json y construye la simulación.

Contiene:
  - RedCaminos: la red de senderos del campus (grafo de nodos y aristas).
    Calcula rutas más cortas (Dijkstra) entre dos puntos cualesquiera,
    proyectando cada punto sobre el segmento de camino más cercano. Las zonas
    que están dentro de un edificio se "conectan" por una puerta en la fachada.
  - Funciones fábrica para crear zonas y agentes a partir de diccionarios
    (las usa también la app web para agregar actores en tiempo de ejecución).
  - construir_simulacion(): arma un Simulador (enjambre) o un
    SimuladorSupervisor a partir de la configuración.
  - mini_campus(): el mapa original de 5 zonas y 2 agentes del prototipo.
"""

import heapq
import json
import math
import os
import random

from agente import Agente
from simulador import Simulador
from supervisor import SimuladorSupervisor
from zona import Zona

RUTA_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campus.json")


def cargar_config(ruta=RUTA_CONFIG):
    with open(ruta, encoding="utf-8") as f:
        config = json.load(f)
    validar_config(config)
    return config


def validar_config(config):
    """Comprobaciones básicas para dar mensajes claros si el JSON tiene errores."""
    for clave in ("ancho", "alto", "tipos_zona", "zonas", "agentes"):
        if clave not in config:
            raise ValueError(f"campus.json: falta la clave '{clave}'")
    ids = [z["id"] for z in config["zonas"]]
    if len(ids) != len(set(ids)):
        raise ValueError("campus.json: hay ids de zona repetidos")
    for z in config["zonas"]:
        if z["tipo"] not in config["tipos_zona"]:
            raise ValueError(f"campus.json: la zona '{z['id']}' usa un tipo desconocido '{z['tipo']}'")
    nodos = config.get("caminos", {}).get("nodos", {})
    for a, b in config.get("caminos", {}).get("aristas", []):
        if a not in nodos or b not in nodos:
            raise ValueError(f"campus.json: la arista {a}-{b} usa un nodo inexistente")


# ---------------------------------------------------------------- geometría
def _proyectar_en_segmento(p, a, b):
    """Punto más cercano a p sobre el segmento a-b y su distancia."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / largo2))
    q = (ax + t * dx, ay + t * dy)
    return q, math.dist(p, q)


def edificio_que_contiene(punto, edificios):
    for ed in edificios:
        if (abs(punto[0] - ed["x"]) <= ed["ancho"] / 2 and
                abs(punto[1] - ed["y"]) <= ed["largo"] / 2):
            return ed
    return None


class RedCaminos:
    """Grafo de senderos del campus con rutas más cortas."""

    def __init__(self, nodos, aristas, edificios=()):
        self.nodos = {k: tuple(v) for k, v in nodos.items()}
        self.aristas = [tuple(a) for a in aristas]
        self.edificios = list(edificios)
        self.vecinos = {k: [] for k in self.nodos}
        for a, b in self.aristas:
            d = math.dist(self.nodos[a], self.nodos[b])
            self.vecinos[a].append((b, d))
            self.vecinos[b].append((a, d))
        self.conectores = {}   # zona_id -> (acceso, punto en el camino)

    def proyectar(self, p):
        """Devuelve (indice_arista, punto_proyectado, distancia) más cercano."""
        mejor = None
        for i, (a, b) in enumerate(self.aristas):
            q, d = _proyectar_en_segmento(p, self.nodos[a], self.nodos[b])
            if mejor is None or d < mejor[2]:
                mejor = (i, q, d)
        return mejor

    def _dijkstra(self, semillas):
        dist = {k: math.inf for k in self.nodos}
        previo = {}
        cola = []
        for nodo, d in semillas.items():
            dist[nodo] = d
            heapq.heappush(cola, (d, nodo))
        while cola:
            d, u = heapq.heappop(cola)
            if d > dist[u]:
                continue
            for v, w in self.vecinos[u]:
                if d + w < dist[v]:
                    dist[v] = d + w
                    previo[v] = u
                    heapq.heappush(cola, (dist[v], v))
        return dist, previo

    def ruta(self, origen, destino):
        """Lista de puntos (x, y) desde origen hasta destino siguiendo los caminos."""
        origen, destino = tuple(origen), tuple(destino)
        if not self.aristas:
            return [origen, destino]
        io, po, _ = self.proyectar(origen)
        idd, pd, _ = self.proyectar(destino)
        if io == idd:
            puntos = [origen, po, pd, destino]
        else:
            a, b = self.aristas[io]
            dist, previo = self._dijkstra({a: math.dist(po, self.nodos[a]),
                                           b: math.dist(po, self.nodos[b])})
            c, d = self.aristas[idd]
            costo_c = dist[c] + math.dist(self.nodos[c], pd)
            costo_d = dist[d] + math.dist(self.nodos[d], pd)
            fin = c if costo_c <= costo_d else d
            camino = [fin]
            while camino[-1] in previo:
                camino.append(previo[camino[-1]])
            camino.reverse()
            puntos = [origen, po] + [self.nodos[n] for n in camino] + [pd, destino]
        # quitar puntos repetidos consecutivos
        limpia = [puntos[0]]
        for p in puntos[1:]:
            if math.dist(p, limpia[-1]) > 1e-6:
                limpia.append(p)
        if len(limpia) == 1:
            limpia.append(destino)
        return limpia

    def preparar_zona(self, zona):
        """
        Define el punto de acceso de la zona. Si la zona está dentro de un
        edificio, el acceso es una "puerta" en la fachada que queda más cerca
        de un camino; si está al aire libre, es la misma posición.
        """
        ed = None
        if zona.edificio:
            ed = next((e for e in self.edificios if e["id"] == zona.edificio), None)
        if ed is None:
            ed = edificio_que_contiene(zona.posicion, self.edificios)
            if ed is not None:
                zona.edificio = ed["id"]
        if ed is None:
            # al aire libre: el trabajador se para junto al marcador, del lado del camino
            zona.acceso = zona.posicion
            if self.aristas:
                _, q, d = self.proyectar(zona.posicion)
                x, y = zona.posicion
                if d > 1.0:
                    zona.acceso = (x + (q[0] - x) / d * 0.9, y + (q[1] - y) / d * 0.9)
                else:   # pegada al camino (o sobre él): a un costado
                    zona.acceso = (x + 0.65, y + 0.65)
        else:
            x, y = zona.posicion
            x0, x1 = ed["x"] - ed["ancho"] / 2, ed["x"] + ed["ancho"] / 2
            y0, y1 = ed["y"] - ed["largo"] / 2, ed["y"] + ed["largo"] / 2
            margen = 0.6
            candidatos = [(x0 - margen, y), (x1 + margen, y), (x, y0 - margen), (x, y1 + margen)]
            zona.acceso = min(candidatos, key=lambda c: (round(self.proyectar(c)[2], 3),
                                                         math.dist(c, zona.posicion)))
        if self.aristas:
            _, punto, _ = self.proyectar(zona.acceso)
            self.conectores[zona.id] = (zona.acceso, punto)

    def punto_aleatorio(self, rng=random):
        """Un punto al azar sobre los caminos (para ubicar nuevos trabajadores)."""
        a, b = rng.choice(self.aristas)
        t = rng.random()
        (ax, ay), (bx, by) = self.nodos[a], self.nodos[b]
        return (round(ax + t * (bx - ax), 2), round(ay + t * (by - ay), 2))


# ------------------------------------------------------------------ fábricas
def crear_zona(datos, config, k_urgencia=None, rho=None, max_historial=None):
    """Crea una Zona a partir de un diccionario {id, nombre, tipo, pos, ...}."""
    tipos = config["tipos_zona"]
    tipo = datos.get("tipo", "salon")
    plantilla = tipos.get(tipo, {})
    params = config.get("parametros", {})
    k = k_urgencia if k_urgencia is not None else params.get("k_urgencia", 0.9)
    factor_k = datos.get("factor_k", plantilla.get("factor_k", 1.0))
    return Zona(
        nombre=datos.get("nombre", datos.get("id")),
        posicion=tuple(datos["pos"]),
        k_urgencia=k * factor_k,
        rho_evaporacion=rho if rho is not None else params.get("rho", 0.25),
        id=datos.get("id"),
        tipo=tipo,
        tiempo_objetivo=datos.get("tiempo_objetivo", plantilla.get("tiempo_objetivo")),
        tiempo_atencion=datos.get("tiempo_atencion", plantilla.get("tiempo_atencion")),
        umbral_atencion=params.get("umbral_atencion", 5.0),
        edificio=datos.get("edificio"),
        factor_k=factor_k,
        max_historial=max_historial,
    )


def crear_agente(datos, config):
    """Crea un Agente a partir de un diccionario {id, nombre, pos, ...}."""
    defecto = config.get("agente_por_defecto", {})
    tiempo = datos.get("tiempo_atencion")
    velocidad = datos.get("velocidad")
    return Agente(
        nombre=datos.get("nombre", datos.get("id")),
        posicion=tuple(datos["pos"]),
        tiempo_atencion=tiempo if tiempo is not None else defecto.get("tiempo_atencion", 4),
        velocidad=velocidad if velocidad is not None else defecto.get("velocidad"),
        id=datos.get("id"),
    )


def construir_red(config):
    caminos = config.get("caminos", {})
    return RedCaminos(caminos.get("nodos", {}), caminos.get("aristas", []),
                      config.get("edificios", []))


def construir_simulacion(config, estrategia="enjambre", semilla=None,
                         semilla_reportes=None, max_historial=None, max_log=None):
    """Arma la simulación completa (zonas, agentes, red y parámetros)."""
    p = config.get("parametros", {})
    red = construir_red(config)
    zonas = [crear_zona(z, config, max_historial=max_historial) for z in config["zonas"]]
    agentes = [crear_agente(a, config) for a in config["agentes"]]
    clase = SimuladorSupervisor if estrategia == "supervisor" else Simulador
    return clase(
        zonas, agentes,
        prob_reporte=p.get("prob_reporte", 0.006),
        semilla=semilla,
        alpha=p.get("alpha", 1.0),
        beta=p.get("beta", 1.0),
        excluir_ocupadas=p.get("excluir_ocupadas", True),
        red=red,
        intensidad_reporte=p.get("intensidad_reporte", 22.0),
        k_urgencia=p.get("k_urgencia", 0.9),
        rho=p.get("rho", 0.25),
        semilla_reportes=semilla_reportes,
        max_log=max_log,
    )


def exportar_config(sim, config_base):
    """
    Foto de la simulación actual (zonas, agentes y parámetros vigentes) en el
    mismo formato de campus.json. Sirve para correr la comparación contra el
    supervisor con lo que hay en pantalla en ese momento.
    """
    config = json.loads(json.dumps(config_base))
    config["parametros"].update({k: v for k, v in sim.parametros().items() if v is not None})
    config["zonas"] = [{
        "id": z.id, "nombre": z.nombre, "tipo": z.tipo, "pos": list(z.posicion),
        "edificio": z.edificio, "factor_k": z.factor_k,
        "tiempo_objetivo": z.tiempo_objetivo, "tiempo_atencion": z.tiempo_atencion,
    } for z in sim.zonas]
    config["agentes"] = [{
        "id": a.id, "nombre": a.nombre, "pos": list(a.posicion),
        "tiempo_atencion": a.tiempo_atencion, "velocidad": a.velocidad,
    } for a in sim.agentes]
    return config


def mini_campus():
    """El mini-campus original del prototipo: 5 zonas y 2 agentes."""
    zonas = [
        Zona("Baño Edificio A", posicion=(0, 0)),
        Zona("Cafetería", posicion=(6, 1)),
        Zona("Baño Edificio B", posicion=(10, 4)),
        Zona("Salón 301", posicion=(3, 7)),
        Zona("Pasillo Biblioteca", posicion=(8, 8)),
    ]
    agentes = [
        Agente("Trabajador 1", posicion=(1, 1)),
        Agente("Trabajador 2", posicion=(9, 7)),
    ]
    return zonas, agentes
