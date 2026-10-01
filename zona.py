"""
zona.py

Representa un espacio del campus (baño, salón, cafetería, pasillo...) que
necesita aseo. Cada zona lleva su propia señal de "urgencia", compuesta por
dos partes independientes (ver senal_urgencia_zona.png para la intuición):

  1. urgencia_base: crece de forma constante mientras nadie la atiende. Es el
     "qué tan sucio está objetivamente". Se reinicia a 0 cuando se limpia.

  2. boost_reporte: un pico de prioridad que aparece cuando alguien reporta
     la zona (p. ej. un QR escaneado por un estudiante). Ese pico decae
     (evapora) con el tiempo, igual que la feromona en Ant Colony Optimization.

La señal total (lo que realmente ven los agentes para decidir) es la suma de
las dos: senal_total = urgencia_base + boost_reporte.

Además de la señal, la zona lleva unas métricas sencillas que NO influyen en
la decisión de los agentes (solo sirven para comparar estrategias y para el
panel de ODS):

  - ticks_en_espera: cuántos ticks lleva la zona "necesitando atención"
    (señal >= umbral_atencion o con un reporte pendiente) sin que nadie haya
    empezado a limpiarla. Es None si la zona no necesita atención.
  - esperas: lista con el tiempo de espera de cada atención ya iniciada.
  - reportes_pendientes / tiempos_respuesta_reportes: edad de los reportes QR
    que aún no se atienden y tiempos de respuesta de los ya atendidos.
"""

from collections import deque


class Zona:
    def __init__(self, nombre, posicion, k_urgencia=0.9, rho_evaporacion=0.25,
                 id=None, tipo="salon", tiempo_objetivo=None, tiempo_atencion=None,
                 umbral_atencion=5.0, edificio=None, factor_k=1.0, max_historial=None):
        self.nombre = nombre
        self.posicion = tuple(posicion)   # (x, y) en un mapa simplificado del campus
        self.k = k_urgencia               # velocidad de crecimiento de la urgencia base
        self.rho = rho_evaporacion        # tasa de evaporación del boost por reporte

        # datos descriptivos (opcionales; el prototipo original no los usa)
        self.id = id if id is not None else nombre
        self.tipo = tipo                  # baño, salón, cafetería, pasillo...
        self.edificio = edificio          # id del edificio que la contiene (o None)
        self.factor_k = factor_k          # multiplicador de k según el tipo de zona
        self.tiempo_objetivo = tiempo_objetivo  # ticks máximos de espera aceptables
        self.tiempo_atencion = tiempo_atencion  # ticks de limpieza (None = el del agente)
        self.umbral_atencion = umbral_atencion  # señal a partir de la cual "necesita atención"
        self.acceso = self.posicion       # punto donde el agente se para a limpiar

        self.urgencia_base = 0.0
        self.boost_reporte = 0.0
        self.ticks_desde_limpieza = 0

        # huella estigmérgica de ocupación: qué agente ya viene en camino o
        # está limpiando (la usa el simulador si excluir_ocupadas=True)
        self.asignada_a = None
        self.en_limpieza = False

        # historial para graficar al final (max_historial=None -> sin límite)
        self.historial_senal = deque(maxlen=max_historial)

        # métricas (no afectan la decisión de los agentes)
        self.ticks_en_espera = None
        self.esperas = []
        self.atenciones_a_tiempo = 0
        self.atenciones_tarde = 0
        self.veces_atendida = 0
        self.reportes_recibidos = 0
        self.reportes_pendientes = []
        self.tiempos_respuesta_reportes = []
        self.ultimo_reporte_tick = None

    @property
    def senal_total(self):
        return self.urgencia_base + self.boost_reporte

    @property
    def necesita_atencion(self):
        return self.senal_total >= self.umbral_atencion or bool(self.reportes_pendientes)

    @property
    def vencida(self):
        """True si lleva esperando más que su tiempo objetivo."""
        return (self.tiempo_objetivo is not None and self.ticks_en_espera is not None
                and self.ticks_en_espera > self.tiempo_objetivo)

    def tick(self):
        """Avanza un ciclo de tiempo: la urgencia base crece, el boost decae."""
        self.urgencia_base += self.k
        self.boost_reporte *= (1 - self.rho)
        self.ticks_desde_limpieza += 1
        self.historial_senal.append(self.senal_total)

        # métricas de espera (solo cuentan mientras nadie ha empezado a limpiar)
        if not self.en_limpieza:
            if self.ticks_en_espera is not None:
                self.ticks_en_espera += 1
            elif self.necesita_atencion:
                self.ticks_en_espera = 0
        self.reportes_pendientes = [edad + 1 for edad in self.reportes_pendientes]

    def reportar(self, intensidad=22.0):
        """Simula un reporte externo (QR / sensor): añade un pico de prioridad."""
        self.boost_reporte += intensidad
        self.reportes_recibidos += 1
        self.reportes_pendientes.append(0)
        if self.ticks_en_espera is None and not self.en_limpieza:
            self.ticks_en_espera = 0

    def _resolver_reportes(self):
        self.tiempos_respuesta_reportes.extend(self.reportes_pendientes)
        self.reportes_pendientes = []

    def iniciar_limpieza(self):
        """
        Un agente llegó y empezó a limpiar. Solo registra métricas (cuánto
        esperó la zona); la señal no cambia hasta que termine (atender()).
        """
        self.en_limpieza = True
        espera = self.ticks_en_espera
        if espera is not None:
            self.esperas.append(espera)
            if self.tiempo_objetivo is not None:
                if espera <= self.tiempo_objetivo:
                    self.atenciones_a_tiempo += 1
                else:
                    self.atenciones_tarde += 1
        self.ticks_en_espera = None
        self._resolver_reportes()
        return espera

    def atender(self):
        """Un agente limpia la zona: se reinician ambas señales."""
        self.urgencia_base = 0.0
        self.boost_reporte = 0.0
        self.ticks_desde_limpieza = 0
        self.en_limpieza = False
        self.asignada_a = None
        self.ticks_en_espera = None
        self.veces_atendida += 1
        self._resolver_reportes()

    def liberar(self):
        """El agente asignado se retiró (p. ej. lo quitaron): la zona queda libre."""
        self.asignada_a = None
        self.en_limpieza = False

    def __repr__(self):
        return f"Zona({self.nombre}, señal={self.senal_total:.1f})"
