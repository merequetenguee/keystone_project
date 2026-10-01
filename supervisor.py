"""
supervisor.py

Línea base "tipo supervisor" para comparar contra el enjambre.

Un supervisor reparte las zonas entre los trabajadores en rondas fijas
(round-robin): la zona j queda a cargo del trabajador j mod n, y cada
trabajador recorre sus zonas siempre en el mismo orden, una tras otra. No
mira la señal de urgencia ni los reportes QR: así es como se organiza una
ronda tradicional planificada de antemano.

Todo lo demás (señales, reportes, caminos, tiempos de limpieza, métricas) es
idéntico al Simulador del enjambre, de modo que la comparación es justa.
"""

from simulador import Simulador


class SimuladorSupervisor(Simulador):
    estrategia = "supervisor"

    def _estructura_cambiada(self):
        """Rehace el reparto round-robin cuando cambian zonas o trabajadores."""
        indices_previos = getattr(self, "_indices", {})
        self._rondas = {a.id: [] for a in self.agentes}
        if self.agentes:
            for j, zona in enumerate(self.zonas):
                self._rondas[self.agentes[j % len(self.agentes)].id].append(zona)
        self._indices = {aid: indices_previos.get(aid, 0) for aid in self._rondas}

    def _asignar(self):
        for agente in self.agentes:
            if not agente.disponible:
                continue
            ronda = self._rondas.get(agente.id)
            if not ronda:
                continue
            i = self._indices[agente.id] % len(ronda)
            zona = ronda[i]
            self._indices[agente.id] = i + 1
            self._despachar(agente, zona)
            self._registrar(
                f"Supervisor envía a {agente.nombre} a '{zona.nombre}' "
                f"(ronda fija, señal={zona.senal_total:.1f})",
                "asignacion", agente=agente.id, zona=zona.id)

    def ronda_de(self, agente_id):
        return [z.id for z in self._rondas.get(agente_id, [])]
