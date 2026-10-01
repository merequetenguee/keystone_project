"""
simulador.py

El ciclo de simulación del enjambre por estigmergia. En cada tick:

  1. Todas las zonas actualizan su señal (urgencia_base sube, boost decae).
  2. Cada agente disponible evalúa las zonas y se autoasigna a una, usando
     la regla de transición de Ant Colony Optimization:

        p_ij = (tau_ij^alpha * eta_ij^beta) / sum_k (tau_ik^alpha * eta_ik^beta)

     donde tau_ij es la señal de la zona j (qué tan urgente está) y eta_ij
     es un valor heurístico (aquí: el inverso de la distancia del agente a
     la zona, para preferir zonas cercanas).
  3. Los agentes ocupados avanzan su progreso de limpieza.
  4. Con una probabilidad pequeña, una zona recibe un "reporte" aleatorio
     (simulando el QR que cualquier estudiante podría escanear).

No hay ningún supervisor decidiendo esto: cada agente decide solo, con la
información visible (la señal de cada zona) y su propia posición.

Extensiones (todas opcionales; con los valores por defecto el simulador se
comporta exactamente como el prototipo original):

  - excluir_ocupadas: una zona a la que ya va otro agente deja de atraer
    (otra huella estigmérgica en el entorno: "aquí ya viene alguien").
  - red: red de caminos del campus (campus.RedCaminos). Si existe y el agente
    tiene velocidad, el agente camina por la ruta antes de limpiar.
  - Agregar/quitar zonas, agentes y reportes QR mientras corre.
  - Métricas acumuladas para comparar contra la línea base de supervisor
    (ver supervisor.py y metricas.py).
"""

import math
import random
from collections import deque


def distancia(p1, p2):
    return math.dist(p1, p2)


def elegir_zona(agente, zonas, alpha=1.0, beta=1.0, rng=random):
    """
    Aplica la regla de transición de ACO para que el agente elija una zona
    entre las que tienen señal > 0. Devuelve la zona elegida (o None si no
    hay ninguna zona que necesite atención).
    """
    candidatas = [z for z in zonas if z.senal_total > 0.1]
    if not candidatas:
        return None

    pesos = []
    for z in candidatas:
        tau = z.senal_total
        eta = 1.0 / (1.0 + distancia(agente.posicion, z.posicion))
        pesos.append((tau ** alpha) * (eta ** beta))

    total = sum(pesos)
    if total <= 0:
        return None

    probabilidades = [w / total for w in pesos]
    return rng.choices(candidatas, weights=probabilidades, k=1)[0]


class Simulador:
    estrategia = "enjambre"

    def __init__(self, zonas, agentes, prob_reporte=0.06, semilla=None,
                 alpha=1.0, beta=1.0, excluir_ocupadas=False, red=None,
                 intensidad_reporte=22.0, k_urgencia=None, rho=None,
                 semilla_reportes=None, max_log=None):
        self.zonas = list(zonas)
        self.agentes = list(agentes)
        self.prob_reporte = prob_reporte
        self.alpha = alpha
        self.beta = beta
        self.excluir_ocupadas = excluir_ocupadas
        self.red = red
        self.intensidad_reporte = intensidad_reporte
        self.tick_actual = 0
        # lista simple como en el original; con max_log se limita (app en vivo)
        self.log = deque(maxlen=max_log) if max_log else []

        # Generador de números aleatorios propio (misma secuencia que
        # random.seed(semilla) del prototipo original). Si se da
        # semilla_reportes, los reportes usan un generador aparte: así el
        # enjambre y el supervisor reciben exactamente los mismos reportes.
        self.rng = random.Random(semilla)
        self.rng_reportes = (random.Random(semilla_reportes)
                             if semilla_reportes is not None else self.rng)

        # parámetros globales opcionales (k y rho se aplican a todas las zonas)
        self.k_urgencia = k_urgencia
        self.rho = rho
        for zona in self.zonas:
            self._aplicar_parametros_zona(zona)

        # eventos estructurados (para la interfaz) y reportes programados
        self.eventos = deque(maxlen=300)
        self._id_evento = 0
        self.reportes_programados = []    # [(tick, zona_id, intensidad, origen)]

        # métricas acumuladas
        self.zonas_retiradas = []
        self.agentes_retirados = []
        self.asignaciones = 0
        self.suma_zonas_vencidas = 0
        self.historial_senal_media = deque(maxlen=600)

        for zona in self.zonas:
            self._preparar_zona(zona)
        self._estructura_cambiada()

    # ------------------------------------------------------------------ log
    def _registrar(self, mensaje, tipo=None, **datos):
        linea = f"[t={self.tick_actual:03d}] {mensaje}"
        self.log.append(linea)
        if tipo is not None:
            self._id_evento += 1
            self.eventos.append({"id": self._id_evento, "t": self.tick_actual,
                                 "tipo": tipo, "texto": mensaje, **datos})

    # --------------------------------------------------------------- ciclo
    def paso(self):
        self.tick_actual += 1

        # 1. Actualizar señales de todas las zonas
        for zona in self.zonas:
            zona.tick()

        # 2. Reportes aleatorios (simulan el QR de un estudiante)
        for zona in self.zonas:
            if self.rng_reportes.random() < self.prob_reporte:
                self._aplicar_reporte(zona, self.intensidad_reporte, "aleatorio")
        self._procesar_reportes_programados()

        # 3. Agentes ocupados avanzan su limpieza (o su camino)
        for agente in self.agentes:
            zona = agente.zona_actual
            evento = agente.tick()
            if evento == "llegada":
                self._registrar(f"{agente.nombre} llega a '{zona.nombre}' y empieza a limpiar",
                                "llegada", agente=agente.id, zona=zona.id)
            elif evento == "terminada" and agente.velocidad:
                self._registrar(f"{agente.nombre} terminó '{zona.nombre}'",
                                "terminada", agente=agente.id, zona=zona.id)

        # 4. Agentes libres se autoasignan
        self._asignar()

        # 5. Contabilidad de métricas
        self._contabilizar()

    def correr(self, n_ticks):
        for _ in range(n_ticks):
            self.paso()

    def _asignar(self):
        """Regla del enjambre: cada agente libre se autoasigna con ACO."""
        for agente in self.agentes:
            if agente.disponible:
                candidatas = self.zonas
                if self.excluir_ocupadas:
                    candidatas = [z for z in self.zonas if z.asignada_a is None]
                zona_elegida = elegir_zona(agente, candidatas, self.alpha, self.beta,
                                           rng=self.rng)
                if zona_elegida is not None:
                    self._despachar(agente, zona_elegida)
                    self._registrar(
                        f"{agente.nombre} se autoasigna a '{zona_elegida.nombre}' "
                        f"(señal={zona_elegida.senal_total:.1f})",
                        "asignacion", agente=agente.id, zona=zona_elegida.id)

    def _despachar(self, agente, zona):
        """Envía al agente a la zona (con ruta por los caminos si aplica)."""
        ruta = None
        if self.red is not None and agente.velocidad:
            ruta = self.red.ruta(agente.posicion, zona.acceso)
        agente.iniciar_atencion(zona, ruta)
        self.asignaciones += 1

    def _contabilizar(self):
        for agente in self.agentes:
            agente.ticks_totales += 1
            if agente.disponible:
                agente.ticks_ociosos += 1
        self.suma_zonas_vencidas += sum(1 for z in self.zonas if z.vencida)
        if self.zonas:
            self.historial_senal_media.append(
                sum(z.senal_total for z in self.zonas) / len(self.zonas))

    # ------------------------------------------------------------ reportes
    def _aplicar_reporte(self, zona, intensidad, origen):
        zona.reportar(intensidad)
        zona.ultimo_reporte_tick = self.tick_actual
        self._registrar(f"reporte recibido en '{zona.nombre}' (señal -> {zona.senal_total:.1f})",
                        "reporte", zona=zona.id, origen=origen)

    def reportar(self, zona_id, intensidad=None, en_ticks=0, origen="qr"):
        """Reporte QR manual. en_ticks > 0 lo programa para más adelante."""
        zona = self.buscar_zona(zona_id)
        if zona is None:
            raise KeyError(f"zona '{zona_id}' no existe")
        intensidad = self.intensidad_reporte if intensidad is None else intensidad
        if en_ticks and en_ticks > 0:
            self.reportes_programados.append(
                (self.tick_actual + int(en_ticks), zona.id, intensidad, origen))
            self._registrar(f"reporte QR programado en '{zona.nombre}' para t={self.tick_actual + int(en_ticks)}",
                            "programado", zona=zona.id)
        else:
            self._aplicar_reporte(zona, intensidad, origen)
        return zona

    def _procesar_reportes_programados(self):
        if not self.reportes_programados:
            return
        pendientes = []
        for (t, zona_id, intensidad, origen) in self.reportes_programados:
            if t <= self.tick_actual:
                zona = self.buscar_zona(zona_id)
                if zona is not None:
                    self._aplicar_reporte(zona, intensidad, origen)
            else:
                pendientes.append((t, zona_id, intensidad, origen))
        self.reportes_programados = pendientes

    # ------------------------------------------- actores en tiempo de ejecución
    def buscar_zona(self, zona_id):
        return next((z for z in self.zonas if z.id == zona_id), None)

    def buscar_agente(self, agente_id):
        return next((a for a in self.agentes if a.id == agente_id), None)

    def _aplicar_parametros_zona(self, zona):
        if self.k_urgencia is not None:
            zona.k = self.k_urgencia * zona.factor_k
        if self.rho is not None:
            zona.rho = self.rho

    def _preparar_zona(self, zona):
        if self.red is not None:
            self.red.preparar_zona(zona)

    def agregar_zona(self, zona):
        if self.buscar_zona(zona.id) is not None:
            raise ValueError(f"ya existe una zona con id '{zona.id}'")
        self._aplicar_parametros_zona(zona)
        self._preparar_zona(zona)
        self.zonas.append(zona)
        self._estructura_cambiada()
        self._registrar(f"nueva zona '{zona.nombre}' en {_fmt(zona.posicion)}",
                        "zona_agregada", zona=zona.id)
        return zona

    def quitar_zona(self, zona_id):
        zona = self.buscar_zona(zona_id)
        if zona is None:
            raise KeyError(f"zona '{zona_id}' no existe")
        for agente in self.agentes:
            if agente.zona_actual is zona:
                agente.cancelar()
        self.zonas.remove(zona)
        self.zonas_retiradas.append(zona)
        self._estructura_cambiada()
        self._registrar(f"zona '{zona.nombre}' retirada", "zona_quitada", zona=zona.id)
        return zona

    def agregar_agente(self, agente):
        if self.buscar_agente(agente.id) is not None:
            raise ValueError(f"ya existe un agente con id '{agente.id}'")
        self.agentes.append(agente)
        self._estructura_cambiada()
        self._registrar(f"{agente.nombre} se une al turno en {_fmt(agente.posicion)}",
                        "agente_agregado", agente=agente.id)
        return agente

    def quitar_agente(self, agente_id):
        agente = self.buscar_agente(agente_id)
        if agente is None:
            raise KeyError(f"agente '{agente_id}' no existe")
        agente.cancelar()
        self.agentes.remove(agente)
        self.agentes_retirados.append(agente)
        self._estructura_cambiada()
        self._registrar(f"{agente.nombre} sale del turno", "agente_quitado", agente=agente.id)
        return agente

    def actualizar_parametros(self, **params):
        """Cambia alpha, beta, rho, k_urgencia, prob_reporte o excluir_ocupadas."""
        for clave in ("alpha", "beta", "prob_reporte", "excluir_ocupadas", "intensidad_reporte"):
            if params.get(clave) is not None:
                setattr(self, clave, params[clave])
        if params.get("k_urgencia") is not None:
            self.k_urgencia = params["k_urgencia"]
        if params.get("rho") is not None:
            self.rho = params["rho"]
        for zona in self.zonas:
            self._aplicar_parametros_zona(zona)

    def parametros(self):
        return {"alpha": self.alpha, "beta": self.beta, "rho": self.rho,
                "k_urgencia": self.k_urgencia, "prob_reporte": self.prob_reporte,
                "excluir_ocupadas": self.excluir_ocupadas,
                "intensidad_reporte": self.intensidad_reporte}

    def _estructura_cambiada(self):
        """Gancho para estrategias que dependen de la lista de zonas/agentes."""
        pass


def _fmt(p):
    return f"({p[0]:.1f}, {p[1]:.1f})"
