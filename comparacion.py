"""
comparacion.py

Corre el enjambre (ACO) y la línea base de supervisor (round-robin) sobre el
mismo campus, con la misma semilla y EXACTAMENTE la misma secuencia de
reportes QR, y compara sus métricas.

Uso:
    python comparacion.py                 # 600 ticks, semilla 7
    python comparacion.py --ticks 1000 --semilla 3
"""

import argparse

from campus import cargar_config, construir_simulacion
from metricas import resumen

# (clave, etiqueta, formato, ¿menor es mejor?)
FILAS = [
    ("espera_media", "Tiempo medio de espera (min)", "{:.1f}", True),
    ("espera_max", "Espera máxima (min)", "{:.0f}", True),
    ("vencidas_promedio", "Zonas desatendidas (promedio)", "{:.2f}", True),
    ("zonas_vencidas", "Zonas desatendidas (al final)", "{:.0f}", True),
    ("banos_a_tiempo_pct", "Baños a tiempo (%)", "{:.1f}", False),
    ("cv_carga", "Balance de carga (CV)", "{:.2f}", True),
    ("ocio_pct", "Tiempo ocioso (%)", "{:.1f}", True),
    ("respuesta_reporte_media", "Respuesta a reportes QR (min)", "{:.1f}", True),
    ("atenciones_totales", "Zonas atendidas", "{:.0f}", False),
    ("senal_media", "Señal media final", "{:.1f}", True),
]


def comparar(config, ticks=600, semilla=7):
    resultados = {}
    for estrategia in ("enjambre", "supervisor"):
        sim = construir_simulacion(config, estrategia=estrategia, semilla=semilla,
                                   semilla_reportes=semilla + 1000, max_historial=1)
        sim.correr(ticks)
        resultados[estrategia] = resumen(sim)
    filas = []
    for clave, etiqueta, fmt, menor_mejor in FILAS:
        e, s = resultados["enjambre"][clave], resultados["supervisor"][clave]
        if e == s:
            mejor = "empate"
        else:
            mejor = "enjambre" if (e < s) == menor_mejor else "supervisor"
        filas.append({"clave": clave, "etiqueta": etiqueta, "enjambre": fmt.format(e),
                      "supervisor": fmt.format(s), "mejor": mejor})
    return {"ticks": ticks, "semilla": semilla, "filas": filas, "detalle": resultados}


def imprimir(comparacion):
    print(f"=== Enjambre vs. supervisor ({comparacion['ticks']} ticks, "
          f"semilla {comparacion['semilla']}) ===")
    print(f"{'Métrica':<34}{'Enjambre':>12}{'Supervisor':>12}   Mejor")
    for f in comparacion["filas"]:
        print(f"{f['etiqueta']:<34}{f['enjambre']:>12}{f['supervisor']:>12}   {f['mejor']}")
    for estrategia in ("enjambre", "supervisor"):
        carga = comparacion["detalle"][estrategia]["carga_por_agente"]
        print(f"\nCarga por trabajador ({estrategia}): " +
              ", ".join(f"{k.split()[-1]}={v}" for k, v in carga.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=600)
    parser.add_argument("--semilla", type=int, default=7)
    args = parser.parse_args()
    imprimir(comparar(cargar_config(), args.ticks, args.semilla))


if __name__ == "__main__":
    main()
