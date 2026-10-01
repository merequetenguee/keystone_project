"""
main.py

Versión de consola del prototipo: "Enjambre de Tareas por Estigmergia"
aplicado al personal de aseo universitario. Corre una simulación de N ticks
con el campus definido en campus.json (o con el mini-campus original) y al
final grafica cómo evolucionó la señal de cada zona y cuándo fue atendida.

Uso:
    python main.py            # campus completo (campus.json) -> resultado_campus.png
    python main.py --mini     # mini-campus original (5 zonas, 2 agentes)
                              # -> prototipo_aseo_resultado.png, igual que antes

Para la versión 3D interactiva: python app.py
"""

import argparse
import statistics

import matplotlib
matplotlib.use("Agg")  # cambiar a un backend interactivo si lo corren localmente
import matplotlib.pyplot as plt

from campus import cargar_config, construir_simulacion, mini_campus
from simulador import Simulador

# Paleta categórica validada (dataviz skill) - un color fijo por zona / tipo,
# asignado en orden fijo (nunca reciclado)
PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def construir_campus():
    """Mini-campus original (se mantiene por compatibilidad)."""
    return mini_campus()


def _estilo_ejes(ax, fig, titulo):
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color("#c9c8c0")
    ax.tick_params(colors="#5a5a56")
    ax.set_xlabel("Tick de simulación", color="#3a3a36")
    ax.set_ylabel("Señal total de urgencia", color="#3a3a36")
    ax.set_title(titulo, color="#1f1f1d", fontsize=13, pad=14)
    ax.grid(True, color="#e5e4de", linewidth=0.7)
    ax.legend(frameon=False, loc="upper left", fontsize=9)


def graficar(zonas, ruta_salida="prototipo_aseo_resultado.png"):
    fig, ax = plt.subplots(figsize=(9, 5.5), dpi=150)
    for i, zona in enumerate(zonas):
        color = PALETA[i % len(PALETA)]
        ax.plot(list(zona.historial_senal), color=color, linewidth=2, label=zona.nombre)
    _estilo_ejes(ax, fig, "Enjambre por estigmergia: señal de cada zona a lo largo del tiempo")
    plt.tight_layout()
    plt.savefig(ruta_salida, facecolor=fig.get_facecolor())
    print(f"\nGráfica guardada en: {ruta_salida}")


def graficar_por_tipo(zonas, tipos, ruta_salida="resultado_campus.png"):
    """Con 20-30 zonas no caben líneas individuales: se grafica la media por tipo."""
    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=150)
    orden = [t for t in tipos if any(z.tipo == t for z in zonas)]
    for i, tipo in enumerate(orden):
        series = [list(z.historial_senal) for z in zonas if z.tipo == tipo]
        media = [statistics.fmean(v) for v in zip(*series)]
        ax.plot(media, color=PALETA[i], linewidth=2,
                label=f"{tipos[tipo]['etiqueta']} ({len(series)})")
    _estilo_ejes(ax, fig, "Enjambre por estigmergia: señal media por tipo de zona")
    plt.tight_layout()
    plt.savefig(ruta_salida, facecolor=fig.get_facecolor())
    print(f"\nGráfica guardada en: {ruta_salida}")


def main():
    parser = argparse.ArgumentParser(description="Simulación de consola del enjambre de aseo")
    parser.add_argument("--mini", action="store_true", help="usar el mini-campus original")
    parser.add_argument("--ticks", type=int, default=None)
    args = parser.parse_args()

    if args.mini:
        zonas, agentes = construir_campus()
        sim = Simulador(zonas, agentes, prob_reporte=0.05, semilla=42)
        n_ticks = args.ticks or 120
    else:
        config = cargar_config()
        sim = construir_simulacion(config, semilla=42)
        zonas, agentes = sim.zonas, sim.agentes
        n_ticks = args.ticks or 300

    sim.correr(n_ticks)

    print("=== Log de la simulación (últimos 25 eventos) ===")
    for linea in list(sim.log)[-25:]:
        print(linea)

    print("\n=== Resumen ===")
    for agente in agentes:
        print(f"{agente.nombre}: {agente.zonas_atendidas} zonas atendidas")
    for zona in zonas:
        print(f"{zona.nombre}: señal final = {zona.senal_total:.1f}, "
              f"ticks sin limpiar = {zona.ticks_desde_limpieza}")

    if args.mini:
        graficar(zonas)
    else:
        graficar_por_tipo(zonas, config["tipos_zona"])
        print("Comparación contra el supervisor: python comparacion.py")


if __name__ == "__main__":
    main()
