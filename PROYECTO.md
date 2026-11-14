# DeHecho — Explorador ambiental y de incendios de La Araucanía

## Idea del proyecto

Desarrollar una herramienta interactiva que permita **explorar cómo cambian las condiciones ambientales de La Araucanía, relacionarlas con la actividad de incendios y evaluar su utilidad para anticiparla**.

La experiencia combina un mapa 2D/3D, un selector de variables y series temporales sincronizadas. El recorrido es **explorar → relacionar → anticipar**: la detección de tendencias cumple el desafío científico y la predicción conserva el objetivo original del proyecto.

**Criterio de alcance:** aprovechar las mediciones ambientales y los conteos CONAF ya disponibles, sin exigir nuevas fuentes de observaciones. La incorporación de puntos de calor o de un relieve realista no forma parte del alcance inicial.

**Pregunta central:** ¿dónde y cómo están cambiando las condiciones ambientales de la región, y qué relación tienen esos cambios con los incendios observados?

## Vínculo con NASA Space Apps 2026

El desafío [Be An Earth System Trend Detective!](https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/?tab=details) propone seleccionar variables de misiones o modelos de ciencias de la Tierra, visualizar su evolución y determinar **qué cambia, dónde, cuánto y si el cambio es estadísticamente significativo**.

DeHecho aplica ese enfoque al contexto de los incendios forestales:

| Pregunta del desafío | Respuesta propuesta |
| --- | --- |
| ¿Qué está cambiando? | Selección de temperatura, humedad del suelo, precipitación y humedad relativa. |
| ¿Dónde cambia? | Mapa de tendencias por comuna y comparación con la serie regional. |
| ¿Cuánto cambia? | Pendientes expresadas en unidades físicas por año o década. |
| ¿Cómo evoluciona? | Series temporales, anomalías y animación del mapa. |
| ¿Es significativo? | Incertidumbre y pruebas de tendencia que consideren dependencia temporal y comparaciones múltiples. |
| ¿Por qué importa? | Comparación con los incendios registrados por CONAF en sus escalas regional y comunal. |

La **predicción es una extensión del análisis**, no un sustituto de la detección de tendencias. Una correlación alta con incendios no demuestra que una variable esté cambiando con el tiempo.

## Datos disponibles

| Fuente | Contenido y escala | Uso |
| --- | --- | --- |
| `data/conaf/conaf.csv` | Conteos mensuales por región; `IX` corresponde a La Araucanía. | Actividad regional de incendios y objetivo predictivo inicial. |
| `data/conaf/conaf_comuna.csv` | Conteos por comuna y temporada julio–junio. | Comparación territorial por temporadas completas. |
| `datos_mensuales_2014_2023/limpios/region_mensual_limpio.csv` | Variables ambientales regionales mensuales de 2014–2023. | Series, anomalías, tendencias y relaciones con incendios. |
| `datos_mensuales_2014_2023/limpios/comunas_mensual_limpio.csv` | Variables ambientales de 32 comunas durante 120 meses. | Visualización espacial y análisis comunal. |
| `datos_mensuales_2014_2023/limpios/reporte_validacion.json` | Controles, unidades corregidas y banderas de cobertura. | Trazabilidad y calidad. |

Los productos ambientales incluyen fuentes NASA como MERRA-2, GLDAS, GPM y NASA POWER; sus características y agregaciones se documentan en `datos_mensuales_2014_2023/metadatos.json`.

### Reglas de integración

- Reconstruir el año calendario de CONAF: enero de `2014-2015` corresponde a enero de 2015.
- Usar códigos administrativos como texto y validar nombres, claves y correspondencias.
- Para tendencias ambientales, aprovechar los **120 meses** disponibles. Para relaciones mensuales con CONAF, usar la intersección actual de **114 meses: julio de 2014–diciembre de 2023**.
- Para comparaciones comunales, agregar el ambiente por temporada completa: **288 pares comuna–temporada**, de 2014–2015 a 2022–2023.
- No convertir un total comunal de temporada en doce observaciones mensuales ni rellenar ausencias de incendios con cero.
- Respetar `soil_coverage_ok`: con el umbral actual de 80 %, Saavedra se conserva en los conteos y variables no edáficas, pero sus valores de suelo se omiten del análisis. Quedan **279 pares comuna–temporada válidos para suelo**, exigiendo doce meses válidos por temporada.

## Cartografía mínima, sin nuevas mediciones

Los datos actuales son suficientes para explorar tendencias, relacionar variables con incendios y evaluar una predicción regional experimental. No se requiere incorporar FIRMS, nuevas variables ambientales ni nuevos registros de incendios para esas tareas.

Para dibujar un mapa geográfico por comuna sí se necesitan sus **límites administrativos**, que no están incluidos en los CSV. Si aún no se dispone de ellos en la interfaz, se incorporará únicamente una geometría compatible con los códigos comunales: es un soporte cartográfico, no una nueva medición para el análisis. Los metadatos existentes identifican la referencia administrativa utilizada al agregar los datos ambientales.

La vista 3D puede obtenerse mediante **extrusión de polígonos comunales**: su altura representa una variable o un conteo, según una leyenda explícita, y no la altitud del terreno. No necesita un modelo de elevación. La vista 2D conserva la misma información.

Los CSV actuales de CONAF no contienen coordenadas de incendios. Por tanto, se visualizarán **conteos por territorio, no puntos de calor ni ubicaciones de incendios individuales**. No se inventarán localizaciones ni se presentarán centroides comunales como puntos de ignición.

## Experiencia interactiva propuesta

### Controles compartidos

- **Variable:** temperatura, humedad del suelo, precipitación o humedad relativa.
- **Territorio:** región o comuna seleccionada en el mapa; comparación entre territorios.
- **Modo:** valores observados, anomalías, tendencias o predicción experimental.
- **Período de análisis:** intervalo utilizado para estimar tendencias y relaciones.
- **Fecha visualizada:** mes o temporada mostrado en el mapa, destacado simultáneamente en las series.
- **Vista 2D/3D:** representaciones alternativas de los mismos datos.

El período de análisis y la fecha visualizada son controles distintos: mover la fecha no debe recalcular una tendencia utilizando solo ese mes.

### Mapa y panel temporal sincronizados

El mapa mostrará valores ambientales, anomalías, tendencias o conteos CONAF mediante colores y, opcionalmente, alturas de los polígonos comunales. Al seleccionar una comuna o fecha se actualizarán:

1. **Serie ambiental:** valores, referencia estacional, anomalías y tendencia con incertidumbre.
2. **Serie de actividad de incendios:** conteos CONAF mensuales regionales o por temporada comunal, claramente identificados.
3. **Relación entre variables:** dispersión y asociaciones contemporáneas o con rezagos.
4. **Ficha de datos:** fuente, unidades, resolución, cobertura y observaciones válidas.

La escala temporal debe ser explícita: CONAF regional permite comparación mensual; CONAF comunal, por temporada. El mapa no animará incendios comunales mes a mes a partir de totales estacionales.

Se proponen tres lecturas coordinadas:

- **Mensual:** mapa del ambiente por comuna y serie de incendios para toda la región, identificando que son escalas espaciales diferentes.
- **Por temporada:** mapa de incendios comunales y resúmenes ambientales de la misma temporada completa.
- **Tendencias:** mapa de pendientes ambientales por comuna y series con incertidumbre para el período seleccionado.

La altura de una extrusión es una codificación visual, no una medición adicional. No se interpolarán agregados comunales para aparentar información a escala de predio.

## Exploración estadística

### 1. Detectar tendencias

Estimar tendencias lineales por variable y territorio, ajustando el ciclo mensual. Informar pendiente, intervalo de confianza y evidencia estadística; considerar autocorrelación temporal y corrección por comparaciones múltiples.

El mapa distinguirá **datos insuficientes**, **tendencias estimadas con poca evidencia** y **tendencias con evidencia estadística**. Un resultado no significativo no demuestra ausencia de cambio. El período 2014–2023 describe una evolución acotada, no una atribución de cambio climático de largo plazo.

### 2. Relacionar ambiente e incendios

Comparar asociaciones originales y entre anomalías; explorar episodios secos, su persistencia y rezagos de uno a tres meses. No interpretar las correlaciones como causalidad ni como capacidad predictiva ya validada.

En el notebook actual, las correlaciones regionales con incendios disminuyen al retirar el ciclo estacional medio: temperatura pasa de **+0,917 a +0,359**, mientras humedad del suelo conserva una asociación de **−0,630** entre anomalías. Esto justifica profundizar en disponibilidad de agua, sin afirmar todavía una tendencia de secamiento.

### 3. Evaluar predicción

El primer objetivo experimental será el **número mensual de incendios regionales**, utilizando antecedentes ambientales disponibles antes del mes pronosticado. Se compararán modelos sencillos con una referencia estacional y se evaluarán mediante separación temporal, sin usar datos futuros para construir variables o ajustar el modelo.

La salida será un conteo esperado con incertidumbre y métricas de desempeño fuera de muestra, no una probabilidad de incendio ni una alerta operacional sin validación. La predicción comunal mensual queda fuera del alcance porque los archivos actuales no proporcionan ese objetivo; no se añadirán registros solo para sostener esa funcionalidad.

## Alcance inicial y estado

**Disponible:** limpieza y exploración ambiental en `analisis.ipynb`; cruces y siete figuras comparativas en `comparacion_conaf_clima.ipynb`.

**MVP propuesto:**

1. Mapa 2D y extrusión 3D de los mismos agregados, con selección de variable, comuna y fecha, usando únicamente límites comunales como soporte cartográfico.
2. Series temporales sincronizadas y controles de calidad visibles.
3. Tendencias ambientales con magnitud e incertidumbre.
4. Visualización de conteos CONAF regionales mensuales y comunales por temporada, sin inventar puntos ni desagregaciones.
5. Comparación de anomalías y relaciones con rezagos.

**Etapa posterior:** módulo experimental de predicción regional, incorporado solo junto a su evaluación y limitaciones.

La interfaz, las pruebas de tendencia y el modelo predictivo se describen aquí como funcionalidades propuestas; no se consideran implementadas por los notebooks existentes. El alcance no exige incorporar nuevas fuentes de mediciones.
