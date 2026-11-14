from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import Settings
from app.consultas.service import QueryError
from app.datos.load_data import load_data
from app.datos.publication import Publication


def create_app(
    settings: Settings | None = None,
    *,
    data_loader: Callable[[], Publication] | None = None,
) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.publication = data_loader() if data_loader is not None else load_data(settings.project_root)
        yield

    application = FastAPI(
        title="DeHecho — Inspector estadístico",
        version="0.3.0",
        description="Consulta directa del ambiente y los resultados explicativos CONAF. Sin pronósticos ni recálculo por petición.",
        lifespan=lifespan,
    )

    @application.exception_handler(QueryError)
    async def query_error_handler(request: Request, exc: QueryError):
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": exc.code, "message": exc.message},
        })

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        details = [{"loc": error["loc"], "message": error["msg"], "type": error["type"]}
                   for error in exc.errors()]
        return JSONResponse(status_code=422, content=jsonable_encoder({
            "error": {"code": "invalid_parameters", "message": "Parámetros de consulta no válidos.", "details": details},
        }))

    application.include_router(router)
    return application
