# DeHecho

Inspector estadístico de La Araucanía. Véanse [el proyecto](PROYECTO.md) y [la arquitectura](ARQUITECTURA.md).

## Ejecutar en local

Desde la raíz del proyecto, con Python 3.11 o superior. Si aún no tienes el entorno:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-api.txt
```

Para iniciar:

```sh
.venv/bin/python -m uvicorn main:app --reload
```

Abre **http://127.0.0.1:8000/docs**. No necesitas generar publicaciones ni definir `DEHECHO_MANIFEST`; esa variable ya no se utiliza.

## Datos disponibles

La API lee directamente los CSV y JSON ambientales de `datos_mensuales_2014_2023/` y `limpios/` al arrancar. No copia archivos, no escribe manifiestos y no ejecuta notebooks.

| `dataset` | Contenido |
| --- | --- |
| `ambiente_region` | Cuatro variables ambientales, 120 meses. |
| `ambiente_comunas` | Las mismas variables, 32 comunas. |
| `tendencias_ambientales` | 132 filas de tendencias 2014–2023, incluida la exclusión del suelo de Saavedra. |

Se verifican integridad, fechas, códigos, unidades y calidad. Solo se admite equivalencia de hashes históricos por saltos de línea `LF/CRLF`; cualquier cambio de contenido bloquea los conjuntos afectados. Los detalles de validación quedan en los logs y registros internos, no en las respuestas.

Después de actualizar CSV o JSON, **reinicia el servicio**. Los análisis afectados deben reejecutarse fuera de la API cuando corresponda; los archivos no se vigilan ni se recalculan por petición. La integración de CONAF y sus hallazgos sigue pendiente.

## Probar desde `/docs`

Pulsa **Try it out**, completa los parámetros y luego **Execute**. Deja vacíos los campos opcionales que no utilices.

- `/api/series`: `dataset=ambiente_region`, `variable=temperature_2m_c`, `territory_id=09`, `start=2020-01-01`, `end=2020-12-31`.
- `/api/series`: `dataset=ambiente_comunas`, `territory_id=09116`, `variable=soil_moisture_0_10cm_kgm2`. Devuelve valores `null` por calidad insuficiente.
- `/api/tendencias`: `dataset=tendencias_ambientales`, `variable=relative_humidity_2m_pct`, `territory_id=09`.

## Respuestas

- `/health`: solo `{"status":"ok"}` o `{"status":"degraded"}`. El código `200` indica que el servicio responde.
- `/api/catalogo`: lista de conjuntos, disponibilidad y opciones de selección.
- `/api/series`: lista de series agrupadas con `points` (`start`, `end`, `value` y motivo si falta el valor).
- `/api/tendencias`: resultados planos con pendiente, intervalo marginal, p Holm, estado, muestra utilizada y exclusión si corresponde.
- `/api/asociaciones` y `/api/hallazgos`: rutas preparadas, todavía sin datos reales integrados.

No se exponen metadatos técnicos, hashes ni auditorías. Los faltantes son `null`, no cero. Filtrar no modifica el período de las tendencias ni recalcula Holm. Una consulta válida sin observaciones devuelve `[]`; errores: `404` para conjunto desconocido, `422` para parámetros incompatibles y `503` para resultados no disponibles, desactualizados o inválidos.

## Pruebas

```sh
.venv/bin/python -m pip install -r requirements-api-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

Las pruebas usan datos sintéticos y copias temporales de los datos reales para comprobar modificaciones, sin alterar los datasets del proyecto.
