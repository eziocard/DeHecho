# DeHecho

Inspector estadístico de La Araucanía. Véanse [el proyecto](PROYECTO.md) y [la arquitectura](ARQUITECTURA.md).

## Ejecutar en local

Desde la raíz del proyecto, con Python 3.12 o superior. El entorno de referencia usa Python 3.14.10 en Linux. Crea el entorno solo si todavía no existe:

```sh
python3 -m venv .venv
```

Instala o actualiza las dependencias de API, análisis y pruebas desde el único archivo:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

`requirements.txt` conserva también los paquetes adicionales del entorno de trabajo. No lo reemplaces con `pip freeze` sin revisar el cambio: ese comando refleja solo lo instalado en el intérprete elegido, no lo que necesita todo el proyecto.

Para iniciar:

```sh
.venv/bin/python -m uvicorn main:app --reload
```

Abre **http://127.0.0.1:8000/docs**. No necesitas generar publicaciones ni definir `DEHECHO_MANIFEST`; esa variable ya no se utiliza.

## Datos disponibles

La API lee directamente los CSV y JSON ambientales, los resultados de `limpios/` y `docs/investigacion/`, las fuentes `data/conaf/` y `definitivo.csv` al arrancar. No copia archivos, no escribe manifiestos y no ejecuta notebooks.

| `dataset` | Contenido |
| --- | --- |
| `ambiente_region` | Cuatro variables ambientales, 120 meses. |
| `ambiente_comunas` | Las mismas variables, 32 comunas. |
| `tendencias_ambientales` | 132 filas de tendencias 2014–2023, incluida la exclusión del suelo de Saavedra. |
| `asociaciones_conaf` | Cuatro razones de tasas ajustadas del modelo binomial negativo regional, sobre 114 meses. |
| `hallazgos_conaf` | Cinco resúmenes del modelo, su sensibilidad y la presencia mensual de incendios. |
| `tendencias_regionales_exploratorias` | 14 estimaciones regionales 2014–2023, con su propia familia Holm de 14 pruebas. |
| `hallazgos_ambientales` | Cinco resúmenes exploratorios sobre picos térmicos, vapor de agua y proxies VPD. |

Los dos identificadores nuevos seleccionan resultados existentes, no nuevos archivos ni mediciones. La investigación permanece en su ubicación original; su marcador histórico `exploratory_not_published_to_API` se conserva sin editar, aunque estos resultados ya pueden consultarse.

Se verifican integridad, fechas, códigos, unidades y calidad. Solo se admite equivalencia de hashes históricos por saltos de línea `LF/CRLF`; cualquier cambio de contenido bloquea los conjuntos afectados. Los detalles de validación quedan en los logs y registros internos, no en las respuestas.

Después de actualizar CSV o JSON, **reinicia el servicio**. Los análisis afectados deben reejecutarse fuera de la API cuando corresponda; los archivos no se vigilan ni se recalculan por petición. Un cambio CONAF no deshabilita los resultados ambientales independientes. Una investigación exploratoria ausente o inválida no bloquea los cinco conjuntos anteriores.

## Probar desde `/docs`

Pulsa **Try it out**, completa los parámetros y luego **Execute**. Deja vacíos los campos opcionales que no utilices.

- `/api/series`: `dataset=ambiente_region`, `variable=temperature_2m_c`, `territory_id=09`, `start=2020-01-01`, `end=2020-12-31`.
- `/api/series`: `dataset=ambiente_comunas`, `territory_id=09116`, `variable=soil_moisture_0_10cm_kgm2`. Devuelve valores `null` por calidad insuficiente.
- `/api/tendencias`: `dataset=tendencias_ambientales`, `variable=relative_humidity_2m_pct`, `territory_id=09`.
- `/api/tendencias`: `dataset=tendencias_regionales_exploratorias`, `variable=temperature_monthly_peak_area_mean_c`, `territory_id=09`.
- `/api/asociaciones`: `dataset=asociaciones_conaf`, `variable=precipitation_mm`, `territory_id=09`.
- `/api/hallazgos`: `dataset=hallazgos_conaf`, `variable=soil_moisture_0_10cm_kgm2`, `territory_id=09`.
- `/api/hallazgos`: `dataset=hallazgos_ambientales`, `variable=dewpoint_2m_c`, `territory_id=09`.

## Respuestas

- `/health`: solo `{"status":"ok"}` o `{"status":"degraded"}`. El código `200` indica que el servicio responde.
- `/api/catalogo`: lista de conjuntos, disponibilidad y opciones de selección.
- `/api/series`: lista de series agrupadas con `points` (`start`, `end`, `value` y motivo si falta el valor).
- `/api/tendencias`: resultados planos con pendiente, intervalo marginal, p Holm, estado, muestra utilizada y exclusión si corresponde.
- `/api/asociaciones`: razones de tasas, intervalo marginal, p Holm, muestra y escala del cambio ambiental. `increment` es una magnitud positiva; `direction=decrease` significa disminución de la anomalía mensual. `unit` corresponde al incremento, no a la razón de tasas. Son asociaciones ajustadas, no causalidad ni pronósticos.
- `/api/hallazgos`: títulos y resúmenes derivados de los reportes existentes, con período y variable cuando corresponde. Los CONAF conservan la sensibilidad del suelo y la falta de evidencia independiente para temperatura y humedad relativa; los ambientales explicitan su carácter exploratorio y límites.

Las asociaciones y hallazgos CONAF son regionales (`09`) y cubren julio de 2014–diciembre de 2023. No se extrapolan a comunas ni a otros períodos. Correlaciones y contrastes de grupos quedan para una incorporación posterior; esta etapa sirve el modelo ajustado principal y sus resúmenes.

La exploración cubre solo la región `09`, con 120 meses de 2014–2023. No reemplaza las tendencias originales ni sus familias Holm de cuatro pruebas regionales y 127 comunales. Las pendientes usan unidades por década; la humedad específica permanece en kg/kg (los resúmenes la expresan en g/kg). Los VPD son proxies calculados con medias, no VPD medio verdadero ni extremos diarios; no tienen asociaciones ajustadas CONAF. No se amplían las series observadas ni se calculan series mensuales derivadas. Tampoco se incorporan los archivos Giovanni 2005–2025.

No se exponen metadatos técnicos, hashes ni auditorías. Los faltantes son `null`, no cero. Filtrar no modifica el período de las tendencias ni recalcula Holm. Una consulta válida sin observaciones devuelve `[]`; errores: `404` para conjunto desconocido, `422` para parámetros incompatibles y `503` para resultados no disponibles, desactualizados o inválidos.

## Pruebas

```sh
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
```

Las pruebas usan datos sintéticos y copias temporales de los datos reales para comprobar modificaciones, sin alterar los datasets del proyecto.
