# Enjambre de Tareas por Estigmergia — prototipo

Prototipo en Python: personal de aseo universitario que se autoasigna a zonas
del campus según una señal de urgencia, sin que ningún supervisor reparta las
rondas. Implementa la regla de decisión de Ant Colony Optimization descrita en
el documento de síntesis (JTBD + SCAMPER + teoría de juegos):

```
p_ij = (tau_ij^alpha · eta_ij^beta) / Σ_k (tau_ik^alpha · eta_ik^beta)
tau = señal de la zona (urgencia base + boost por reporte QR, que se evapora con rho)
eta = 1 / (1 + distancia del trabajador a la zona)
```

Incluye una app web con escena 3D (Three.js), comparación contra una línea
base "tipo supervisor" y un panel de indicadores ODS.

## Cómo correrlo

```bash
python -m venv venv
venv\Scripts\activate             # en macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

python app.py                     # app 3D: abre el navegador en http://127.0.0.1:8000
```

`python app.py` arranca el servidor y abre el navegador automáticamente. Si el
puerto 8000 está ocupado usa el siguiente libre. Opciones:
`--puerto 8080`, `--sin-navegador`, `--semilla 7`.

Versión de consola (sin navegador):

```bash
python main.py              # campus completo (campus.json) -> resultado_campus.png
python main.py --mini       # mini-campus original de 5 zonas -> prototipo_aseo_resultado.png
python comparacion.py       # enjambre vs. supervisor (600 ticks) en una tabla
```

`python main.py --mini` reproduce exactamente el log y la gráfica del prototipo
original (misma semilla y la misma secuencia aleatoria).

## Arquitectura

```
Navegador  static/index.html + static/js/*.js  (Three.js r160, copiado en static/vendor/)
   │   ▲
   │   └── WebSocket /ws : mensaje "escena" (geometría) + "estado" en cada tick
   └────── HTTP /api/... : comandos (pausar, velocidad, parámetros, actores, reportes)
app.py (FastAPI + uvicorn)
   └── motor.py  MotorSimulacion: avanza la simulación en el bucle asyncio y la serializa
         ├── simulador.py   Simulador (enjambre ACO)   ├── zona.py    Zona (señal + métricas)
         ├── supervisor.py  SimuladorSupervisor        ├── agente.py  Agente (camina y limpia)
         ├── campus.py      carga campus.json, red de caminos (Dijkstra), fábricas
         ├── metricas.py    métricas y los 5 indicadores ODS
         └── comparacion.py enjambre vs. supervisor con la misma semilla y los mismos reportes
```

Todo el estado de la simulación vive en el servidor; el navegador solo dibuja.
Los trabajadores se interpolan sobre su ruta entre ticks para que el movimiento
sea fluido. Tick base: 0,5 s a velocidad 1× (1 tick = 1 minuto simulado).

## Archivos

| Archivo | Qué hace |
|---|---|
| `zona.py` | `Zona`: señal de urgencia (base + boost por reporte, con evaporación) y métricas de espera / reportes. |
| `agente.py` | `Agente`: trabajador con estados libre → en ruta → limpiando. Con `velocidad=None` no se desplaza (comportamiento original). |
| `simulador.py` | Ciclo de simulación y regla ACO `elegir_zona()` (sin cambios en la fórmula). Agregar/quitar zonas, agentes y reportes en ejecución. |
| `supervisor.py` | Línea base: rondas fijas round-robin (la zona j la atiende el trabajador j mod n), sin mirar la señal. |
| `campus.json` | El mapa: 40×40 unidades, 8 edificios, 29 zonas de 7 tipos, red de caminos, 10 trabajadores y parámetros. |
| `campus.py` | Carga y valida `campus.json`, red de caminos con rutas más cortas, fábricas de zonas/agentes, mini-campus original. |
| `metricas.py` | Tiempo de espera, zonas desatendidas, balance de carga, ocio, reportes y los indicadores ODS. |
| `comparacion.py` | Corre enjambre y supervisor en igualdad de condiciones e imprime la tabla. |
| `motor.py` / `app.py` | Servidor web (FastAPI + WebSocket) para la app 3D. |
| `main.py` | Versión de consola con gráfica en PNG. |
| `static/` | Frontend: `index.html`, `css/estilos.css`, `js/` (escena, modelos 3D, interfaz, gráficas, ODS) y `vendor/three/`. |
| `tests/` | Pruebas: `test_simulacion.py`, `test_api.py` (pytest) y `prueba_ui.py` (Playwright con Edge/Chrome). |
| `capturas/` | Capturas de pantalla generadas por `tests/prueba_ui.py`. |

## Configurar el campus (`campus.json`)

- `parametros`: `alpha`, `beta`, `rho`, `k_urgencia`, `prob_reporte`,
  `intensidad_reporte`, `umbral_atencion` (señal a partir de la cual una zona
  "necesita atención") y `excluir_ocupadas`.
- `tipos_zona`: por tipo, `factor_k` (multiplica a `k_urgencia`: los baños se
  ensucian más rápido), `tiempo_objetivo` (minutos máximos de espera) y
  `tiempo_atencion` (ticks de limpieza; `null` = el del trabajador).
- `edificios` (centro, ancho, largo y pisos), `plazas`, `caminos` (nodos y
  aristas), `zonas` (id, nombre, tipo, posición) y `agentes`. Una zona cuya
  posición cae dentro de un edificio se dibuja sobre su techo y se atiende por
  una puerta en la fachada.

Los valores por defecto (`alpha=2`, `beta=3`, velocidad 2,5, 10 trabajadores)
salen de un barrido corto con `comparacion.py`. Con `alpha=beta=1` el enjambre
viaja demasiado entre puntas del campus y queda casi empatado con el
supervisor. Los deslizadores de la app permiten probar otros valores en vivo.

## La app 3D

- **Escena**: edificios con volumen, ventanas y techos (planos con pretil o a
  dos aguas), caminos con faroles, plazas, fuente, árboles y cámara orbital
  (arrastrar = rotar, rueda = zoom, clic derecho = desplazar). Botones de vista
  general y vista superior.
- **Zonas**: cada una tiene una columna cuya altura es la señal. La parte sólida
  es la urgencia base y la parte luminosa es el boost del reporte QR, que se ve
  evaporarse. El color indica el estado: azul claro (baja), azul (cerca del
  umbral), ámbar (necesita atención), rojo con halo (vencida) y verde (en
  limpieza).
- **Trabajadores**: modelo 3D con uniforme y carrito de aseo (balde, contenedor
  y trapeador). Caminan por los senderos hacia la zona elegida, con la ruta
  resaltada por flechas animadas, y al limpiar mueven el trapeador.
- **Reportes QR**: ondas azules y un ícono QR que sube sobre la zona.
- **Controles**: iniciar/pausar (también con la barra espaciadora), +1 tick,
  velocidad 0,5×–8×, reiniciar, y deslizadores de α, β, ρ, k_urgencia y prob.
  de reporte.
- **Agregar y quitar actores**:
  - Trabajador: nombre, tiempo de atención, velocidad y posición elegida en el
    mapa o al azar.
  - Zona: tipo, nombre, tiempo objetivo, tiempo de atención y posición.
  - Reporte QR: zona, intensidad e inmediato o programado *N* ticks después.
  - Las listas de actores permiten quitarlos. Un clic en una zona de la escena
    la elige para el reporte.
- **Métricas en vivo**: zonas atendidas, señal media, espera media y zonas
  desatendidas. Gráfica de señal por zona (color = tipo, línea punteada =
  umbral; al pasar el mouse se resalta la zona en 3D) y gráfica de la señal
  media en el tiempo.
- **Enjambre vs. supervisor**: el botón "Comparar ahora" corre ambas
  estrategias 600 ticks con la configuración actual.

## Panel de ODS

| ODS | Indicador del prototipo | Al pasar el mouse resalta |
|---|---|---|
| 3 Salud y bienestar | Tiempo medio entre la señal de suciedad (señal ≥ umbral o reporte) y el inicio de la limpieza | zonas que esperan atención |
| 6 Agua limpia y saneamiento | % de atenciones de baño dentro de su tiempo objetivo (los baños vencidos cuentan como fallos) | baños |
| 8 Trabajo decente | Coeficiente de variación de zonas atendidas por trabajador + % de tiempo ocioso | trabajadores |
| 9 Industria, innovación e infraestructura | Zonas y trabajadores operando + autoasignaciones sin asignación manual | todo |
| 11 Ciudades y comunidades sostenibles | Reportes QR atendidos / recibidos y tiempo de respuesta | zonas con reportes recientes |

Son **indicadores del prototipo calculados con la simulación, no mediciones
reales**, y así se aclara en la interfaz.

## Definiciones de las métricas

- **Espera**: ticks entre que una zona necesita atención y que un trabajador
  empieza a limpiarla. Incluye las esperas en curso para no favorecer a una
  estrategia que deja zonas olvidadas.
- **Zona desatendida (vencida)**: lleva esperando más que su `tiempo_objetivo`.
- **Balance de carga**: desviación estándar / media de zonas atendidas por
  trabajador (0 = reparto perfecto).
- **Comparación justa**: ambas estrategias usan el mismo campus, la misma
  semilla y un generador aparte para los reportes, así reciben exactamente los
  mismos reportes QR.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q                 # 22 pruebas: núcleo, regla ACO, supervisor, métricas y API
python -m playwright install chromium   # solo si no tienes Edge ni Chrome instalados
python tests/prueba_ui.py           # prueba de la interfaz en un navegador real + capturas/
```

`prueba_ui.py` arranca la app, usa todos los controles, verifica cada acción
contra la API, revisa que la consola del navegador no tenga errores y guarda
capturas de pantalla en `capturas/`.

## Limitaciones conocidas

- Los trabajadores nunca quedan ociosos (ocio ≈ 0 %): la urgencia base crece
  siempre, así que siempre hay alguna zona con señal > 0,1 que elegir. Es
  propio del modelo, no un error del cálculo.
- El enjambre tiene una espera **máxima** mayor que el supervisor: la regla es
  probabilística y de vez en cuando una zona de baja señal queda relegada más
  tiempo. En promedio espera bastante menos.
- La heurística η usa distancia en línea recta, como el prototipo original,
  aunque los trabajadores caminan por los senderos.
- El estado de la simulación es uno solo en el servidor: todas las pestañas
  abiertas ven y controlan la misma simulación.
- Las zonas agregadas en vivo no se guardan en `campus.json`; al reiniciar se
  vuelve a la configuración del archivo.
