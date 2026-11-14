# DeHecho — Inspector estadístico de La Araucanía

## Objetivo

Permitir consultar **cómo cambian las condiciones ambientales, dónde, cuánto y con qué evidencia estadística**, y relacionarlas con los incendios registrados por CONAF.

Así se responde al desafío [Earth System Trend Detective de NASA Space Apps 2026](https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/?tab=details). Se aprovechan los datos existentes; **la predicción y las alertas quedan fuera del alcance inicial**.

## Qué permitirá consultar

- Series de temperatura, precipitación, humedad relativa y humedad del suelo por región o comuna.
- Anomalías: diferencias respecto de lo habitual para cada mes en el período de referencia.
- Tendencias 2014–2023, con magnitud, incertidumbre y evidencia estadística.
- Asociaciones con incendios, episodios y resultados del modelo explicativo ya estimado.

Los análisis están disponibles en `analisis.ipynb` y sus resultados en `datos_mensuales_2014_2023/limpios/`. La API lee directamente las series y tendencias ambientales; falta integrar CONAF y sus hallazgos, con reejecución solo si cambian sus datos efectivos. No se recalculan en cada consulta. Véase [ARQUITECTURA.md](ARQUITECTURA.md).

## Datos y límites importantes

- **Ambiente:** 120 meses de 2014–2023 y 32 comunas. El contexto regional conjunto con incendios cubre 114 meses: julio de 2014–diciembre de 2023.
- **Incendios:** conteos regionales mensuales y comunales por temporada julio–junio. No hay coordenadas de incendios ni desglose comunal mensual; no se deben inventar ni repartir totales regionales entre comunas.
- **Cruce regional:** `definitivo.csv` alinea los mismos 114 meses conjuntos por `fecha` calendario; `año_x` conserva el inicio de temporada. No sustituye los 120 meses de la base ambiental utilizada para tendencias.
- **Calidad:** excluir suelo de Saavedra por baja cobertura, sin eliminar sus otras variables. Una cobertura desconocida no equivale a 100 %. Los faltantes no son ceros.
- **Interpretación:** las asociaciones y el modelo binomial negativo son explicativos, no prueban causalidad ni predicen riesgo. Los conteos no representan superficie quemada o gravedad. Las comunas pueden compartir píxeles y no son réplicas independientes.

## Qué respaldan los resultados actuales

La **humedad relativa presenta descenso con evidencia** en la región y sus comunas durante 2014–2023. Las otras tres variables no alcanzan evidencia tras la corrección aplicada; eso no demuestra ausencia de cambio.

El **déficit de lluvia conserva la asociación ajustada con incendios más estable entre las variantes examinadas**. No debe confundirse con la variable que más cambia ni con un predictor validado.

Las tendencias publicadas corresponden al período completo 2014–2023: filtrar una serie no cambia su estimación. Deben conservarse los métodos, referencias y correcciones de los reportes originales; no se deduce la evidencia solo del intervalo de confianza.
