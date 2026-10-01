"""
motor.py

"Motor" de la simulación en vivo para la app web (app.py). Mantiene un
Simulador corriendo en el bucle de asyncio, lo avanza a la velocidad elegida
y convierte su estado a diccionarios JSON para enviarlos por WebSocket.

Mensajes que envía a los navegadores:
  - {"tipo": "escena", ...}: geometría del campus (edificios, caminos,
    plazas, conectores de zonas, tipos de zona). Se reenvía cuando cambia
    (p. ej. al agregar una zona).
  - {"tipo": "estado", ...}: zonas, agentes, eventos nuevos, métricas, ODS
    y parámetros. Se envía en cada tick y después de cada comando.

Todas las operaciones sobre la simulación ocurren en el mismo hilo (el bucle
de eventos), así que no hacen falta bloqueos entre el tick y los comandos.
"""

import asyncio
import math
import random

from campus import (RUTA_CONFIG, cargar_config, construir_simulacion, crear_agente,
                    crear_zona, edificio_que_contiene, exportar_config)
from comparacion import comparar
from metricas import indicadores_ods, resumen

TICK_BASE_S = 0.5           # segundos por tick a velocidad 1x
MAX_HISTORIAL = 240         # ticks de historial que se guardan por zona

# Paleta categórica validada (skill dataviz), en orden fijo, un color por tipo
PALETA_TIPOS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def _r(v, n=2):
    return round(v, n) if isinstance(v, float) else v


class MotorSimulacion:
    def __init__(self, ruta_config=RUTA_CONFIG, semilla=None):
        self.config = cargar_config(ruta_config)
        self.semilla = semilla
        self.rng = random.Random(semilla)
        self.velocidad = 1.0
        self.corriendo = True
        self.clientes = set()
        self.version_escena = 0
        self.reiniciar()

    # ------------------------------------------------------------ ciclo de vida
    def reiniciar(self):
        self.sim = construir_simulacion(self.config, semilla=self.semilla,
                                        max_historial=MAX_HISTORIAL, max_log=500)
        self._ultimo_evento_enviado = 0
        self.version_escena += 1
        self.reinicios = getattr(self, "reinicios", -1) + 1

    @property
    def intervalo(self):
        return TICK_BASE_S / self.velocidad

    async def bucle(self):
        """Avanza la simulación mientras esté corriendo y difunde el estado."""
        while True:
            if self.corriendo:
                self.sim.paso()
                await self.difundir()
                await asyncio.sleep(self.intervalo)
            else:
                await asyncio.sleep(0.05)

    # ------------------------------------------------------------- difusión
    async def conectar(self, ws):
        self.clientes.add(ws)
        await ws.send_json(self.escena())
        await ws.send_json(self.estado(eventos=list(self.sim.eventos)[-25:], completo=True))

    def desconectar(self, ws):
        self.clientes.discard(ws)

    async def difundir(self, escena=False):
        nuevos = [e for e in self.sim.eventos if e["id"] > self._ultimo_evento_enviado]
        if self.sim.eventos:
            self._ultimo_evento_enviado = self.sim.eventos[-1]["id"]
        mensajes = ([self.escena()] if escena else []) + [self.estado(eventos=nuevos)]
        for ws in list(self.clientes):
            try:
                for m in mensajes:
                    await ws.send_json(m)
            except Exception:
                self.clientes.discard(ws)

    # -------------------------------------------------------- serialización
    def escena(self):
        cfg = self.config
        red = self.sim.red
        tipos = {}
        for i, (clave, t) in enumerate(cfg["tipos_zona"].items()):
            tipos[clave] = {"etiqueta": t.get("etiqueta", clave),
                            "color": PALETA_TIPOS[i % len(PALETA_TIPOS)],
                            "tiempo_objetivo": t.get("tiempo_objetivo")}
        return {
            "tipo": "escena",
            "version": self.version_escena,
            "nombre": cfg.get("nombre", "Campus"),
            "ancho": cfg["ancho"], "alto": cfg["alto"],
            "unidad_tiempo": cfg.get("unidad_tiempo", "tick"),
            "edificios": cfg.get("edificios", []),
            "plazas": cfg.get("plazas", []),
            "caminos": [[*red.nodos[a], *red.nodos[b]] for a, b in red.aristas],
            "conectores": {zid: [*a, *b] for zid, (a, b) in red.conectores.items()
                           if self.sim.buscar_zona(zid) is not None},
            "tipos_zona": tipos,
            "umbral_atencion": cfg.get("parametros", {}).get("umbral_atencion", 5.0),
            "tick_base_s": TICK_BASE_S,
        }

    def estado(self, eventos=(), completo=False):
        sim = self.sim
        r = resumen(sim)
        zonas = [{
            "id": z.id, "nombre": z.nombre, "tipo": z.tipo, "edificio": z.edificio,
            "x": z.posicion[0], "y": z.posicion[1],
            "acceso": [_r(z.acceso[0]), _r(z.acceso[1])],
            "senal": _r(z.senal_total), "base": _r(z.urgencia_base), "boost": _r(z.boost_reporte),
            "espera": z.ticks_en_espera, "vencida": z.vencida,
            "objetivo": z.tiempo_objetivo, "en_limpieza": z.en_limpieza,
            "asignada": z.asignada_a.id if z.asignada_a is not None else None,
            "reportes": len(z.reportes_pendientes), "atendida": z.veces_atendida,
            "k": _r(z.k, 3),
        } for z in sim.zonas]
        agentes = [{
            "id": a.id, "nombre": a.nombre, "x": _r(a.posicion[0], 3), "y": _r(a.posicion[1], 3),
            "estado": a.estado, "zona": a.zona_actual.id if a.zona_actual is not None else None,
            "ruta": [[_r(p[0]), _r(p[1])] for p in a.ruta_completa] if a.estado == "en_ruta" else [],
            "progreso": _r(a.progreso), "atendidas": a.zonas_atendidas,
            "tiempo_atencion": a.tiempo_atencion, "velocidad": a.velocidad,
            "ocio_pct": _r(100.0 * a.ticks_ociosos / a.ticks_totales if a.ticks_totales else 0.0, 1),
        } for a in sim.agentes]
        metricas = {k: _r(v) for k, v in r.items() if k != "carga_por_agente"}
        msg = {
            "tipo": "estado",
            "tick": sim.tick_actual,
            "reinicios": self.reinicios,
            "version_escena": self.version_escena,
            "corriendo": self.corriendo,
            "velocidad": self.velocidad,
            "intervalo_ms": round(self.intervalo * 1000),
            "parametros": sim.parametros(),
            "zonas": zonas,
            "agentes": agentes,
            "eventos": list(eventos),
            "metricas": metricas,
            "ods": indicadores_ods(sim, r),
            "senal_media": _r(sim.historial_senal_media[-1]) if sim.historial_senal_media else 0.0,
        }
        if completo:
            msg["historial_senal_media"] = [_r(v) for v in sim.historial_senal_media]
        return msg

    # ------------------------------------------------------------- comandos
    def _limitar(self, x, y):
        return (min(max(float(x), 0.5), self.config["ancho"] - 0.5),
                min(max(float(y), 0.5), self.config["alto"] - 0.5))

    def _nuevo_id(self, prefijo, existentes):
        n = 1
        while f"{prefijo}{n}" in existentes:
            n += 1
        return f"{prefijo}{n}", n

    def control(self, accion):
        if accion == "iniciar":
            self.corriendo = True
        elif accion == "pausar":
            self.corriendo = False
        elif accion == "alternar":
            self.corriendo = not self.corriendo
        elif accion == "paso":
            self.corriendo = False
            self.sim.paso()
        elif accion == "reiniciar":
            self.reiniciar()
            return True       # la escena cambió
        return False

    def fijar_velocidad(self, velocidad):
        self.velocidad = float(velocidad)

    def agregar_agente(self, nombre=None, x=None, y=None, tiempo_atencion=None, velocidad=None):
        ids = {a.id for a in self.sim.agentes} | {a.id for a in self.sim.agentes_retirados}
        nuevo_id, n = self._nuevo_id("t", ids)
        if x is None or y is None:
            pos = self.sim.red.punto_aleatorio(self.rng)
        else:
            pos = self._limitar(x, y)
        agente = crear_agente({"id": nuevo_id, "nombre": nombre or f"Trabajador {n}", "pos": pos,
                               "tiempo_atencion": tiempo_atencion, "velocidad": velocidad},
                              self.config)
        return self.sim.agregar_agente(agente)

    def quitar_agente(self, agente_id):
        return self.sim.quitar_agente(agente_id)

    def agregar_zona(self, tipo="salon", nombre=None, x=None, y=None,
                     tiempo_objetivo=None, tiempo_atencion=None):
        if tipo not in self.config["tipos_zona"]:
            raise ValueError(f"tipo de zona desconocido: '{tipo}'")
        ids = {z.id for z in self.sim.zonas} | {z.id for z in self.sim.zonas_retiradas}
        nuevo_id, n = self._nuevo_id("z", ids)
        if x is None or y is None:
            pos = self._posicion_libre()
        else:
            pos = self._limitar(x, y)
        etiqueta = self.config["tipos_zona"][tipo].get("etiqueta", tipo)
        datos = {"id": nuevo_id, "nombre": nombre or f"{etiqueta} nueva {n}", "tipo": tipo, "pos": pos}
        if tiempo_objetivo is not None:
            datos["tiempo_objetivo"] = tiempo_objetivo
        if tiempo_atencion is not None:
            datos["tiempo_atencion"] = tiempo_atencion
        zona = crear_zona(datos, self.config, k_urgencia=self.sim.k_urgencia,
                          rho=self.sim.rho, max_historial=MAX_HISTORIAL)
        self.sim.agregar_zona(zona)
        self.version_escena += 1
        return zona

    def _posicion_libre(self):
        """Un punto al azar del campus lejos de otras zonas (para zonas nuevas)."""
        mejor, mejor_d = None, -1.0
        for _ in range(60):
            p = (self.rng.uniform(3, self.config["ancho"] - 3), self.rng.uniform(3, self.config["alto"] - 3))
            d = min((math.dist(p, z.posicion) for z in self.sim.zonas), default=99)
            if edificio_que_contiene(p, self.config.get("edificios", [])) is None:
                d = min(d, self.sim.red.proyectar(p)[2] * 2)   # lejos de los caminos
            if d > mejor_d:
                mejor, mejor_d = p, d
        return (round(mejor[0], 2), round(mejor[1], 2))

    def quitar_zona(self, zona_id):
        zona = self.sim.quitar_zona(zona_id)
        self.sim.red.conectores.pop(zona_id, None)
        self.version_escena += 1
        return zona

    def reportar(self, zona_id=None, x=None, y=None, intensidad=None, en_ticks=0):
        if zona_id is None:
            if x is None or y is None:
                if not self.sim.zonas:
                    raise ValueError("no hay zonas para reportar")
                zona_id = self.rng.choice(self.sim.zonas).id
            else:
                if not self.sim.zonas:
                    raise ValueError("no hay zonas para reportar")
                p = (float(x), float(y))
                zona_id = min(self.sim.zonas, key=lambda z: math.dist(p, z.posicion)).id
        return self.sim.reportar(zona_id, intensidad=intensidad, en_ticks=en_ticks, origen="qr")

    def actualizar_parametros(self, **params):
        self.sim.actualizar_parametros(**params)

    async def comparar(self, ticks=600, semilla=7):
        """Corre enjambre vs. supervisor con una foto de la configuración actual."""
        foto = exportar_config(self.sim, self.config)
        return await asyncio.to_thread(comparar, foto, ticks, semilla)
