"""
metricas.py

Métricas para comparar el enjambre contra la línea base de supervisor y para
alimentar el panel de ODS de la interfaz.

Todas se calculan con los datos de la simulación (no son mediciones reales).
La unidad de tiempo es el tick (en campus.json, 1 tick = 1 minuto simulado).

Definiciones:
  - Espera: ticks entre el momento en que una zona "necesita atención"
    (señal >= umbral o reporte QR pendiente) y el momento en que un
    trabajador empieza a limpiarla. Se incluyen las esperas aún en curso
    (si no, una estrategia que deja zonas olvidadas saldría favorecida).
  - Zona vencida (desatendida): lleva esperando más que su tiempo_objetivo.
  - Balance de carga: coeficiente de variación (desv. estándar / media) de
    las zonas atendidas por trabajador. 0 = carga perfectamente repartida.
  - Ocio: porcentaje de ticks en que el trabajador estaba libre sin tarea.
"""

import statistics


def _media(valores):
    return statistics.fmean(valores) if valores else 0.0


def _todas_las_zonas(sim):
    return list(sim.zonas) + list(sim.zonas_retiradas)


def _todos_los_agentes(sim):
    return list(sim.agentes) + list(sim.agentes_retirados)


def resumen(sim):
    zonas = _todas_las_zonas(sim)
    agentes = _todos_los_agentes(sim)

    esperas = [e for z in zonas for e in z.esperas]
    en_curso = [z.ticks_en_espera for z in sim.zonas if z.ticks_en_espera is not None]
    esperas_con_curso = esperas + en_curso

    carga = [a.zonas_atendidas for a in sim.agentes]
    media_carga = _media(carga)
    cv_carga = (statistics.pstdev(carga) / media_carga) if len(carga) > 1 and media_carga > 0 else 0.0
    ticks_tot = sum(a.ticks_totales for a in agentes)
    ociosos = sum(a.ticks_ociosos for a in agentes)

    reportes_recibidos = sum(z.reportes_recibidos for z in zonas)
    respuestas = [t for z in zonas for t in z.tiempos_respuesta_reportes]
    pendientes = sum(len(z.reportes_pendientes) for z in sim.zonas)

    banos = [z for z in zonas if z.tipo == "bano"]
    banos_a_tiempo = sum(z.atenciones_a_tiempo for z in banos)
    banos_tarde = sum(z.atenciones_tarde for z in banos)
    banos_vencidos_ahora = sum(1 for z in banos if z in sim.zonas and z.vencida)
    banos_total = banos_a_tiempo + banos_tarde + banos_vencidos_ahora

    ticks = max(sim.tick_actual, 1)
    return {
        "estrategia": sim.estrategia,
        "ticks": sim.tick_actual,
        "zonas": len(sim.zonas),
        "agentes": len(sim.agentes),
        "atenciones_totales": sum(z.veces_atendida for z in zonas),
        "senal_media": _media([z.senal_total for z in sim.zonas]),
        "espera_media": _media(esperas_con_curso),
        "espera_max": max(esperas_con_curso) if esperas_con_curso else 0,
        "zonas_vencidas": sum(1 for z in sim.zonas if z.vencida),
        "vencidas_promedio": sim.suma_zonas_vencidas / ticks,
        "zonas_nunca_atendidas": sum(1 for z in sim.zonas if z.veces_atendida == 0
                                     and z.asignada_a is None),
        "carga_por_agente": {a.nombre: a.zonas_atendidas for a in sim.agentes},
        "cv_carga": cv_carga,
        "ocio_pct": 100.0 * ociosos / ticks_tot if ticks_tot else 0.0,
        "reportes_recibidos": reportes_recibidos,
        "reportes_atendidos": len(respuestas),
        "reportes_pendientes": pendientes,
        "respuesta_reporte_media": _media(respuestas),
        "banos_a_tiempo_pct": (100.0 * banos_a_tiempo / banos_total) if banos_total else 100.0,
        "banos_atenciones": banos_a_tiempo + banos_tarde,
        "asignaciones": sim.asignaciones,
    }


def indicadores_ods(sim, r=None, ventana_reportes=40):
    """
    Indicadores del prototipo asociados a 5 ODS. Cada indicador trae los ids
    de zonas/agentes relacionados para resaltarlos en la escena 3D.
    """
    r = r or resumen(sim)
    autonomo = sim.estrategia == "enjambre"
    zonas_espera = [z.id for z in sim.zonas if z.ticks_en_espera is not None]
    banos = [z.id for z in sim.zonas if z.tipo == "bano"]
    con_reporte = [z.id for z in sim.zonas
                   if z.reportes_pendientes or (z.ultimo_reporte_tick is not None and
                                                sim.tick_actual - z.ultimo_reporte_tick <= ventana_reportes)]
    agentes = [a.id for a in sim.agentes]
    return [
        {
            "ods": 3, "titulo": "Salud y bienestar", "color": "#4C9F38",
            "explicacion": "Espacios sucios por menos tiempo reducen el riesgo sanitario para la comunidad.",
            "indicador": "Tiempo medio entre la señal de suciedad y la atención",
            "valor": round(r["espera_media"], 1), "unidad": "min",
            "detalle": f"Máximo observado: {r['espera_max']} min · {len(zonas_espera)} zonas esperando ahora",
            "zonas": zonas_espera, "agentes": [],
        },
        {
            "ods": 6, "titulo": "Agua limpia y saneamiento", "color": "#26BDE2",
            "explicacion": "Baños limpios a tiempo son la base del saneamiento en el campus.",
            "indicador": "Baños atendidos dentro del tiempo objetivo",
            "valor": round(r["banos_a_tiempo_pct"], 1), "unidad": "%",
            "detalle": f"{r['banos_atenciones']} atenciones de baño · objetivo según campus.json",
            "zonas": banos, "agentes": [],
        },
        {
            "ods": 8, "titulo": "Trabajo decente", "color": "#A21942",
            "explicacion": "Repartir la carga de forma pareja evita sobrecargar a unas personas y dejar ociosas a otras.",
            "indicador": "Dispersión de la carga (coef. de variación) y tiempo ocioso",
            "valor": round(r["cv_carga"], 2), "unidad": "CV",
            "detalle": f"Ocio medio: {r['ocio_pct']:.1f}% del turno",
            "zonas": [], "agentes": agentes,
        },
        {
            "ods": 9, "titulo": "Industria, innovación e infraestructura", "color": "#FD6925",
            "explicacion": "La coordinación por estigmergia escala sin un supervisor que reparta tareas.",
            "indicador": "Zonas y trabajadores operando sin intervención manual",
            "valor": f"{r['zonas']} · {r['agentes']}", "unidad": "zonas · trab.",
            "detalle": (f"{r['asignaciones']} autoasignaciones · 0 asignaciones manuales" if autonomo
                        else f"{r['asignaciones']} asignaciones del supervisor"),
            "zonas": [z.id for z in sim.zonas], "agentes": agentes,
        },
        {
            "ods": 11, "titulo": "Ciudades y comunidades sostenibles", "color": "#FD9D24",
            "explicacion": "Los estudiantes participan reportando por QR; el sistema responde a la comunidad.",
            "indicador": "Reportes QR atendidos",
            "valor": f"{r['reportes_atendidos']}/{r['reportes_recibidos']}", "unidad": "reportes",
            "detalle": (f"Respuesta media: {r['respuesta_reporte_media']:.1f} min · "
                        f"{r['reportes_pendientes']} pendientes"),
            "zonas": con_reporte, "agentes": [],
        },
    ]
