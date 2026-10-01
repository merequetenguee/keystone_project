"""
app.py

Aplicación web del prototipo: backend FastAPI que expone la simulación del
enjambre en vivo + frontend 3D (Three.js) servido desde la carpeta static/.

Uso (un solo comando; abre el navegador automáticamente):
    python app.py
    python app.py --puerto 8080 --sin-navegador --semilla 42

Arquitectura:
    navegador (static/index.html + js/*.js, Three.js local)
        |  WebSocket /ws   <- escena y estado de la simulación en cada tick
        |  HTTP /api/...   -> comandos (pausar, agregar trabajador, reporte QR...)
    app.py (FastAPI) -> motor.py (MotorSimulacion) -> simulador.py / supervisor.py
                                                     -> campus.py / metricas.py
"""

import argparse
import asyncio
import os
import socket
import threading
import webbrowser
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from motor import MotorSimulacion

DIR_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

motor = MotorSimulacion(semilla=int(os.environ.get("ENJAMBRE_SEMILLA", "42")))


@asynccontextmanager
async def ciclo_de_vida(_app):
    tarea = asyncio.create_task(motor.bucle())
    yield
    tarea.cancel()


app = FastAPI(title="Enjambre de aseo por estigmergia", lifespan=ciclo_de_vida)
app.mount("/static", StaticFiles(directory=DIR_STATIC), name="static")


# ------------------------------------------------------------------ modelos
class ControlIn(BaseModel):
    accion: Literal["iniciar", "pausar", "alternar", "paso", "reiniciar"]


class VelocidadIn(BaseModel):
    velocidad: float = Field(..., gt=0, le=20)


class ParametrosIn(BaseModel):
    alpha: Optional[float] = Field(None, ge=0, le=5)
    beta: Optional[float] = Field(None, ge=0, le=6)
    rho: Optional[float] = Field(None, ge=0, le=1)
    k_urgencia: Optional[float] = Field(None, ge=0, le=5)
    prob_reporte: Optional[float] = Field(None, ge=0, le=0.5)
    excluir_ocupadas: Optional[bool] = None


class AgenteIn(BaseModel):
    nombre: Optional[str] = Field(None, max_length=40)
    x: Optional[float] = None
    y: Optional[float] = None
    tiempo_atencion: Optional[int] = Field(None, ge=1, le=60)
    velocidad: Optional[float] = Field(None, gt=0, le=10)


class ZonaIn(BaseModel):
    tipo: str = "salon"
    nombre: Optional[str] = Field(None, max_length=60)
    x: Optional[float] = None
    y: Optional[float] = None
    tiempo_objetivo: Optional[int] = Field(None, ge=1, le=1000)
    tiempo_atencion: Optional[int] = Field(None, ge=1, le=60)


class ReporteIn(BaseModel):
    zona_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    intensidad: Optional[float] = Field(None, gt=0, le=200)
    en_ticks: int = Field(0, ge=0, le=1000)


async def _ejecutar(funcion, *args, escena=False, **kwargs):
    """Ejecuta un comando sobre el motor, traduce errores a HTTP y difunde el estado."""
    try:
        resultado = funcion(*args, **kwargs)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await motor.difundir(escena=escena)
    return resultado


# ------------------------------------------------------------------- rutas
@app.get("/")
async def inicio():
    return FileResponse(os.path.join(DIR_STATIC, "index.html"))


@app.websocket("/ws")
async def ws_estado(ws: WebSocket):
    await ws.accept()
    await motor.conectar(ws)
    try:
        while True:
            await ws.receive_text()      # el cliente no envía nada; mantiene viva la conexión
    except WebSocketDisconnect:
        pass
    finally:
        motor.desconectar(ws)


@app.get("/api/estado")
async def api_estado():
    return motor.estado()


@app.get("/api/escena")
async def api_escena():
    return motor.escena()


@app.post("/api/control")
async def api_control(cuerpo: ControlIn):
    cambio = motor.control(cuerpo.accion)
    await motor.difundir(escena=cambio)
    return {"ok": True, "corriendo": motor.corriendo, "tick": motor.sim.tick_actual}


@app.post("/api/velocidad")
async def api_velocidad(cuerpo: VelocidadIn):
    await _ejecutar(motor.fijar_velocidad, cuerpo.velocidad)
    return {"ok": True, "velocidad": motor.velocidad}


@app.post("/api/parametros")
async def api_parametros(cuerpo: ParametrosIn):
    await _ejecutar(motor.actualizar_parametros, **cuerpo.model_dump(exclude_none=True))
    return {"ok": True, "parametros": motor.sim.parametros()}


@app.post("/api/agentes")
async def api_agregar_agente(cuerpo: AgenteIn):
    a = await _ejecutar(motor.agregar_agente, **cuerpo.model_dump())
    return {"ok": True, "id": a.id, "nombre": a.nombre, "pos": a.posicion}


@app.delete("/api/agentes/{agente_id}")
async def api_quitar_agente(agente_id: str):
    a = await _ejecutar(motor.quitar_agente, agente_id)
    return {"ok": True, "id": a.id}


@app.post("/api/zonas")
async def api_agregar_zona(cuerpo: ZonaIn):
    z = await _ejecutar(motor.agregar_zona, escena=True, **cuerpo.model_dump())
    return {"ok": True, "id": z.id, "nombre": z.nombre, "pos": z.posicion, "edificio": z.edificio}


@app.delete("/api/zonas/{zona_id}")
async def api_quitar_zona(zona_id: str):
    z = await _ejecutar(motor.quitar_zona, zona_id, escena=True)
    return {"ok": True, "id": z.id}


@app.post("/api/reportes")
async def api_reporte(cuerpo: ReporteIn):
    z = await _ejecutar(motor.reportar, **cuerpo.model_dump())
    return {"ok": True, "zona": z.id, "nombre": z.nombre, "en_ticks": cuerpo.en_ticks}


@app.get("/api/comparacion")
async def api_comparacion(ticks: int = 600, semilla: int = 7):
    if not 50 <= ticks <= 5000:
        raise HTTPException(status_code=400, detail="ticks debe estar entre 50 y 5000")
    return await motor.comparar(ticks, semilla)


# -------------------------------------------------------------- arranque
def _puerto_libre(host, inicial):
    for puerto in range(inicial, inicial + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, puerto))
                return puerto
            except OSError:
                continue
    raise RuntimeError("no se encontró un puerto libre")


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Enjambre de aseo por estigmergia - app 3D")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador")
    parser.add_argument("--semilla", type=int, default=None,
                        help="semilla aleatoria (por defecto 42 o ENJAMBRE_SEMILLA)")
    args = parser.parse_args()
    if args.semilla is not None:
        motor.semilla = args.semilla
        motor.reiniciar()

    puerto = _puerto_libre(args.host, args.puerto)
    url = f"http://{args.host}:{puerto}/"
    print(f"Enjambre de aseo corriendo en {url}  (Ctrl+C para detener)")
    if not args.sin_navegador:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
