# Arquitectura mínima del inspector estadístico

## Enfoque

**Archivos existentes → validación y carga en memoria → consultas FastAPI → respuestas JSON.**

Se sirven series y análisis ya calculados. No hacen falta base de datos, microservicios ni ejecutar notebooks por petición. El frontend usará **Blockbench**; su integración con la API se definirá posteriormente.

Al arrancar se capturan una sola vez los CSV y JSON del proyecto y se contrastan con sus reportes. Los cargadores ambiental, CONAF y exploratorio son independientes. No se necesitan publicaciones ni configuración adicional. Si cambian las fuentes, se bloquean los resultados afectados; la reejecución ocurre fuera de la API y se reinicia el servicio para cargar los archivos actualizados. Uso en [README.md](README.md).

## Entradas

En `datos_mensuales_2014_2023/limpios/`:

| Archivos | Uso |
| --- | --- |
| `region_mensual_limpio.csv`, `comunas_mensual_limpio.csv` | Series ambientales. |
| `incendios_contexto_mensual.csv` | Contexto regional conjunto, anomalías y antecedentes. |
| `tendencias_ambientales_2014_2023.csv`, `reporte_tendencias.json` | Tendencias, evidencia y método. |
| `modelo_conaf_binomial_negativa.csv`, `hallazgos_exploratorios.json` | Asociaciones, modelo explicativo, episodios y sensibilidad. |
| `reporte_validacion.json` | Reglas y advertencias de calidad. |

Se complementan con `metadatos.json` de la carpeta superior y las fuentes de `data/conaf/`. Se concilia `definitivo.csv` con el contexto mensual en el período publicado: es un cruce regional existente, no una fuente adicional de observaciones.

`docs/investigacion/exploracion_regional.csv` y `.json` se leen donde están, sin modificarlos. Aportan 14 tendencias regionales exploratorias y cinco resúmenes; se validan entre sí y contra las dos fuentes limpias registradas. No se amplían series ni se calculan proxies mensuales.

## Módulos necesarios

| Módulo | Responsabilidad |
| --- | --- |
| `datos` | Leer archivos, validar fechas y códigos, aplicar calidad y conservar procedencia. No modificar fuentes. |
| `consultas` | Filtrar series y preparar resúmenes compatibles con su escala temporal. |
| `resultados` | Consultar resultados publicados y proyectar solo los campos científicos necesarios, sin recalcularlos. |
| `api` | Validar parámetros con Pydantic y exponer resultados mínimos mediante FastAPI; mantener auditoría y métodos internos. |

La carga utiliza CSV/JSON y validación con Pydantic. SciPy y statsmodels quedan en el proceso de estimación, fuera de las peticiones del inspector.

## Consultas mínimas

- `GET /health`: solo estado del servicio y disponibilidad global.
- `GET /api/catalogo`: conjuntos, disponibilidad, variables, unidades y territorios.
- `GET /api/series`: valores y contexto por variable, territorio y período.
- `GET /api/tendencias`: estimaciones originales (`tendencias_ambientales`) y exploratorias regionales (`tendencias_regionales_exploratorias`) para 2014–2023.
- `GET /api/asociaciones`: cuatro razones de tasas ajustadas (`asociaciones_conaf`); correlaciones y contrastes quedan pendientes.
- `GET /api/hallazgos`: cinco resúmenes CONAF (`hallazgos_conaf`) y cinco ambientales exploratorios (`hallazgos_ambientales`).

Las consultas devuelven **listas de resultados sin metadatos técnicos**. Las series agrupan puntos; las tendencias entregan pendiente y evidencia; las asociaciones incluyen razón de tasas, intervalo marginal, p Holm, muestra y dirección del cambio ambiental. Los faltantes conservan su motivo. Fuentes, métodos, hashes y diagnósticos permanecen internos, sin otro endpoint de metadatos.

## Reglas que no deben perderse

- **No recalcular al filtrar:** preservar el período 2014–2023 y las familias Holm publicadas: cuatro pruebas regionales y 127 comunales originales; 14 regionales exploratorias, por separado. Los intervalos son marginales; la evidencia se determina con el p corregido. Mantener las configuraciones HAC de cada análisis según sus reportes.
- **No mezclar escalas ni referencias:** incendios comunales por temporada y regionales por mes. En el contexto exportado, las anomalías contemporáneas usan 114 meses y los antecedentes una referencia ambiental de 120 meses.
- **No confundir faltantes con ceros:** responder `null` con motivo; distinguir exclusión por calidad, cobertura desconocida y evidencia insuficiente. Mantener `high_activity = null` fuera de la población comparada; alta actividad histórica no significa riesgo futuro.
- **No publicar pronósticos:** el modelo existente es explicativo. El recálculo para otros intervalos y la predicción quedan fuera del alcance inicial.

Las cinco consultas de datos están implementadas con pruebas sintéticas y datos reales. Se conservan los resultados existentes, sin reestimación; esta propuesta no exige nuevas mediciones.
