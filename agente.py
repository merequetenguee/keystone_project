"""
agente.py

Representa a un trabajador de aseo. No recibe una ronda asignada por un
supervisor: en cada ciclo, si está disponible, evalúa las zonas cercanas y
se autoasigna a una según la regla de decisión de Ant Colony Optimization
(ver simulador.py -> elegir_zona).

Estados del agente:
  - "libre":      disponible para autoasignarse.
  - "en_ruta":    camina por los caminos del campus hacia la zona elegida
                  (solo si tiene velocidad; si velocidad=None se salta este
                  estado y limpia "a distancia", como en el prototipo original).
  - "limpiando":  está en la zona; tarda tiempo_atencion ticks en terminar.
"""

import math


class Agente:
    def __init__(self, nombre, posicion, tiempo_atencion=4, velocidad=None, id=None):
        self.nombre = nombre
        self.id = id if id is not None else nombre
        self.posicion = tuple(posicion)   # (x, y) en el mapa del campus
        self.tiempo_atencion = tiempo_atencion  # ticks que tarda en limpiar una zona
        self.velocidad = velocidad        # unidades de mapa por tick (None = sin desplazamiento)
        self.disponible = True
        self.estado = "libre"
        self.zona_actual = None
        self.ticks_restantes = 0
        self.duracion_limpieza = 0

        # ruta que sigue mientras camina (lista de puntos (x, y))
        self.ruta = []                    # puntos que le faltan por recorrer
        self.ruta_completa = []           # ruta entera, para dibujarla en la escena

        # métricas simples para la sustentación
        self.zonas_atendidas = 0
        self.ticks_totales = 0
        self.ticks_ociosos = 0
        self.ticks_viaje = 0
        self.ticks_limpieza = 0
        self.distancia_recorrida = 0.0

    def iniciar_atencion(self, zona, ruta=None):
        self.disponible = False
        self.zona_actual = zona
        zona.asignada_a = self
        if self.velocidad and ruta and len(ruta) > 1:
            self.estado = "en_ruta"
            self.ruta_completa = [tuple(p) for p in ruta]
            self.ruta = self.ruta_completa[1:]
        else:
            self._empezar_limpieza()

    def _empezar_limpieza(self):
        self.estado = "limpiando"
        self.ruta = []
        zona = self.zona_actual
        # la zona puede definir su propio tiempo de limpieza; si no, el del agente
        self.duracion_limpieza = (zona.tiempo_atencion if zona.tiempo_atencion is not None
                                  else self.tiempo_atencion)
        self.ticks_restantes = self.duracion_limpieza
        zona.iniciar_limpieza()

    def _avanzar(self):
        """Camina 'velocidad' unidades sobre la ruta; al llegar empieza a limpiar."""
        restante = self.velocidad
        x, y = self.posicion
        while restante > 1e-9 and self.ruta:
            dx, dy = self.ruta[0][0] - x, self.ruta[0][1] - y
            d = math.hypot(dx, dy)
            if d <= restante:
                x, y = self.ruta.pop(0)
                restante -= d
                self.distancia_recorrida += d
            else:
                x += dx / d * restante
                y += dy / d * restante
                self.distancia_recorrida += restante
                restante = 0.0
        self.posicion = (x, y)
        if not self.ruta:
            self._empezar_limpieza()
            return True
        return False

    def tick(self):
        """
        Si está atendiendo una zona, avanza su progreso.
        Devuelve un evento ("llegada" o "terminada") o None.
        """
        if self.disponible:
            return None
        if self.estado == "en_ruta":
            self.ticks_viaje += 1
            return "llegada" if self._avanzar() else None

        self.ticks_limpieza += 1
        self.ticks_restantes -= 1
        if self.ticks_restantes <= 0:
            self.zona_actual.atender()
            self.zonas_atendidas += 1
            self.zona_actual = None
            self.disponible = True
            self.estado = "libre"
            self.ruta_completa = []
            return "terminada"
        return None

    def cancelar(self):
        """Abandona la tarea actual (p. ej. porque quitaron la zona)."""
        if self.zona_actual is not None and self.zona_actual.asignada_a is self:
            self.zona_actual.liberar()
        self.zona_actual = None
        self.disponible = True
        self.estado = "libre"
        self.ruta = []
        self.ruta_completa = []
        self.ticks_restantes = 0

    @property
    def progreso(self):
        """Fracción de la limpieza completada (0..1), útil para la interfaz."""
        if self.estado != "limpiando" or not self.duracion_limpieza:
            return 0.0
        return 1.0 - self.ticks_restantes / self.duracion_limpieza

    def __repr__(self):
        estado = "libre" if self.disponible else f"limpiando {self.zona_actual.nombre}"
        return f"Agente({self.nombre}, {estado})"
