# DeHecho: oportunidades de valor para el desafío

Revisión del 14 de noviembre de 2026. Incluye revisión de código, notebooks,
reportes, CSV locales y documentación científica. Los cálculos nuevos son
exploratorios, regionales y están separados de los resultados que sirve la API.

## Recomendación

Construir una investigación guiada con esta pregunta central:

> **¿Qué señales de calor y secamiento quedan ocultas cuando miramos solo los
> promedios, y cómo se relacionan con los incendios de La Araucanía?**

Hay dos señales adicionales aprovechables sin descargar nuevos datos: aumento
de los picos mensuales de temperatura y disminución del contenido de vapor de
agua del aire. Un indicador derivado de déficit de presión de vapor permite
conectar temperatura y humedad de forma comprensible, con límites explícitos.

La prioridad de producto es conectar el mapa con selección de variables, series,
tendencias y explicaciones. En el frontend revisado, `MapExplorer` selecciona
comunas y presenta su nombre; todavía no consulta la API ni presenta resultados
científicos. El backend ya tiene buena parte de las respuestas necesarias.

## Qué ya existe y conviene aprovechar

Fuentes principales revisadas: `analisis.ipynb`, `PROYECTO.md`, `ARQUITECTURA.md`,
`datos_mensuales_2014_2023/metadatos.json`, los reportes de `limpios/`, los CSV
CONAF y Giovanni, `app/api/routes.py` y el frontend `low-poly-studio`.

| Componente | Estado comprobado | Implicación |
| --- | --- | --- |
| Ambiente regional y comunal | 120 meses, 2014–2023; 32 comunas; 14 campos ambientales de origen | Hay variables disponibles que todavía no tienen tendencias publicadas. |
| Tendencias publicadas | Cuatro variables; efectos mensuales, HAC y Holm; 131 ajustes y una exclusión | La base estadística ya cubre magnitud y evidencia; falta acercarla al usuario. |
| CONAF regional | 114 meses conjuntos, julio 2014–diciembre 2023 | Permite contextualizar episodios y asociaciones regionales. |
| CONAF comunal | Conteos por temporada julio–junio | Permite comparaciones por temporada; no localización mensual de incendios. |
| Exploración previa | Anomalías, persistencia seca, desfases lluvia–suelo, episodios y sensibilidad | Estas funciones ya tienen cálculos: presentarlas sería integración, no un descubrimiento nuevo. |
| API | Catálogo, series, tendencias, asociaciones y cinco hallazgos | Hay un recorrido demostrable pendiente de conectar al mapa. |

En la publicación actual, la humedad relativa disminuye **9,34 puntos
porcentuales por década**, con evidencia tras Holm. Temperatura media, lluvia
y humedad superficial del suelo tienen pendientes estimadas, pero evidencia
insuficiente tras la corrección original. Esto no equivale a ausencia de cambio.

El déficit de lluvia conserva la asociación ajustada con incendios más estable
entre las especificaciones examinadas. En el modelo principal, una disminución
de aproximadamente **49,6 mm en la anomalía mensual** se asocia con una razón de
tasas de **1,73** (IC marginal 95 %: 1,49–2,00), controlando calendario, tiempo
y las otras variables incluidas. Es un resultado asociativo sobre conteos;
no es probabilidad individual de incendio ni estimación causal.

## Hallazgos adicionales calculados

Se examinaron 14 series regionales: las cuatro publicadas, siete campos
adicionales existentes y tres transformaciones de temperatura/humedad. Se usó
el mismo modelo lineal con efectos de mes y HAC de 12 meses. Holm se aplicó a
las **14 series examinadas**, por separado para cada ventana HAC de 4, 8, 12 y
18 meses. Esta familia exploratoria no sustituye la familia original.

El cálculo independiente reproduce pendientes, errores estándar, intervalos y
p de los cuatro resultados regionales publicados, incluida su corrección Holm
original. No se modificó el notebook ni se publicaron estos resultados en la API.

| Variable | Pendiente por década | IC 95 % marginal | p Holm, 14 series | Lectura |
| --- | ---: | ---: | ---: | --- |
| Temperatura media | +0,65 °C | −0,07 a +1,38 | 0,336 | Evidencia insuficiente. |
| Humedad relativa | −9,34 puntos porcentuales | −12,85 a −5,84 | 0,00000212 | Descenso con evidencia. |
| Promedio espacial de picos mensuales de temperatura | +3,87 °C | +2,67 a +5,06 | 0,00000000293 | Señal de calor en los picos de la malla. |
| Punto de rocío | −1,94 °C | −2,73 a −1,15 | 0,0000155 | Compatible con menor vapor de agua. |
| Humedad específica | −0,76 g/kg | −1,10 a −0,42 | 0,0000885 | Menor contenido de vapor por masa de aire. |
| Proxy VPD con temperatura y humedad relativa | +0,157 kPa | +0,085 a +0,229 | 0,000145 | Mayor déficit de saturación estimado a partir de medias. |
| Proxy VPD con temperatura y punto de rocío | +0,193 kPa | +0,107 a +0,279 | 0,0000945 | Coincide en dirección, con otra formulación. |

Las seis señales de esta tabla con evidencia la conservan en las cuatro
ventanas HAC. Al omitir un año calendario cada vez, la pendiente de los picos
mensuales queda entre **+3,62 y +4,29 °C/década**, la humedad específica entre
**−0,96 y −0,65 g/kg/década**, y el proxy VPD T/RH entre **+0,140 y
+0,175 kPa/década**. Son rangos de sensibilidad, no intervalos de confianza.

También se calcularon temperatura superficial del suelo, viento a 10 m y AOD;
no alcanzan evidencia en esta exploración. El máximo espacial de los picos
mensuales y la humedad relativa reconstruida se conservaron como comprobaciones
adicionales, y cuentan dentro de las 14 pruebas. Los resultados completos están
en [exploracion_regional.csv](exploracion_regional.csv) y
[exploracion_regional.json](exploracion_regional.json).

### A. La media y los picos cuentan historias diferentes

La comparación más útil para la demo es **temperatura media frente a picos
mensuales**. Hay evidencia de aumento de estos últimos en las tablas actuales,
aunque la tendencia de la media sea incierta.

El campo empleado, `temperature_monthly_peak_area_mean_c`, es el promedio
ponderado por área de los picos mensuales de cada píxel. Es diferente de
`temperature_monthly_max_c`, que toma el mayor pico entre los píxeles. Los picos
de distintos píxeles pueden ocurrir en días diferentes. Ninguno equivale a un
extremo de termómetro local ni mide por sí solo días de ola de calor. La
[documentación de procesamiento de NASA POWER](https://power.larc.nasa.gov/docs/methodology/data/processing/)
distingue los extremos T2M_MAX de los promedios de máximas diarias.

No se calculó una prueba formal de diferencia entre las dos pendientes.
Por tanto, que una sea significativa y la otra no lo sea no demuestra que
ambas pendientes difieran significativamente. Tampoco justifica extrapolar
+3,87 °C a las décadas siguientes. Antes de convertirlo en un titular científico,
conviene contrastar el resultado con datos diarios o estaciones independientes.

### B. Investigar por qué desciende la humedad relativa

La humedad relativa depende tanto de la temperatura como del vapor de agua.
La pregunta siguiente es si su descenso refleja solo calentamiento o también
menos humedad atmosférica. Las pendientes negativas de humedad específica y
punto de rocío son compatibles con la segunda posibilidad dentro de este período.

Esto **no constituye tres validaciones independientes**: las variables
comparten MERRA-2, y POWER calcula humedad relativa usando temperatura,
humedad específica y presión. La dependencia está descrita en la
[metodología de NASA POWER](https://power.larc.nasa.gov/docs/methodology/data/derived/met-derived-parameters/).
Para cuantificar cuánto aporta cada componente se necesitaría una descomposición
con campos coherentes y, para contrastar el resultado, una fuente independiente.

### C. Déficit de presión de vapor como indicador educativo

El VPD expresa la diferencia entre la presión de vapor de saturación y la
presión real. Puede explicarse como una medida de la demanda atmosférica de
humedad, sin presentarlo como riesgo de incendio ni como evapotranspiración.

Se usaron `es(T)=0.6108·exp(17.27·T/(T+237.3))`, `es(T)·(1−RH/100)` y
`es(T)−es(Td)`. Al aplicarse **después de promediar tiempo y espacio**, estas
transformaciones son proxies: no recuperan el VPD medio verdadero ni los
extremos diarios. La no linealidad y las precauciones de agregación se explican
en [FAO-56, datos meteorológicos](https://www.fao.org/4/x0490e/x0490e07.htm).

Su incremento aún no se ha evaluado como asociación ajustada con CONAF.
No se puede afirmar que mejore el modelo de incendios por mostrar una tendencia
clara. Tampoco conviene agregar VPD junto con todas sus variables componentes
sin revisar redundancia y definir la pregunta del modelo.

## Qué construir primero

| Prioridad | Propuesta | Valor para el desafío | Trabajo pendiente |
| --- | --- | --- | --- |
| 1 | Caso guiado «¿La media oculta cambios en el calor?» | Selecciona variables por una pregunta y compara magnitud y evidencia. | Validar/publicar la serie de picos, su tendencia y su definición; conectar gráfico y mapa. |
| 2 | Caso «¿Se está secando el aire?» | Relaciona variables familiares y especializadas; explica humedad relativa, específica y VPD. | Publicar indicadores exploratorios con procedencia y límites; calcular por comuna si se desea mapearlos. |
| 3 | Caso «¿Qué ocurrió en 2021 y antes de febrero de 2023?» | Conecta anomalías, persistencia y contexto CONAF ya calculados. | Preparar tarjetas de episodios y series alineadas; conservar referencias y escalas. |
| 4 | Comparador de sensibilidad al período y a la estación | Enseña por qué el período elegido altera la respuesta. | Precalcular ventanas y sus familias; separar resultados descriptivos de inferencia formal. |

Flujo propuesto: **pregunta → variables sugeridas y definiciones → territorio →
serie original/anomalía → pendiente e incertidumbre → conclusión y límites**.

Cada conclusión debería responder visiblemente:

- **Qué:** variable y definición comprensible.
- **Dónde:** territorio y resolución real de la fuente.
- **Cuánto:** pendiente en unidades, intervalo marginal y período.
- **Con qué evidencia:** resultado corregido y sensibilidad.

Un selector puede recomendar un grupo pequeño de variables según la pregunta,
su mecanismo físico, cobertura y resolución. No debería ordenar solo por el p
más pequeño. La explicación puede salir de plantillas verificables: no hace
falta un chatbot para aportar este valor.

En el mapa, usar color para dirección y magnitud, y una marca adicional para
incertidumbre o cobertura insuficiente. Mostrar números en la ficha. Las
32 comunas comparten píxeles de origen: no son 32 experimentos independientes.
Los hallazgos nuevos de este informe son regionales; aún no autorizan colorear
comunas con estos resultados ni asignar incendios regionales a cada comuna.

La API actual mantiene las tendencias de 2014–2023 aunque el usuario filtre
la serie. Una vista de sensibilidad debe advertirlo y utilizar estimaciones
específicas previamente calculadas; no basta con cambiar el rango del gráfico.

## Una oportunidad educativa que ya aparece en los datos

Al dividir ilustrativamente el registro, la pendiente de humedad relativa es
**+1,25 puntos porcentuales/década en 2014–2018** y **−14,27 en 2019–2023**.
Las ventanas son cortas y esta división fue elegida después de inspeccionar los
datos: son estimaciones descriptivas, no evidencia de un quiebre en 2019.

Sirven para demostrar que una pendiente de diez años puede resumir evoluciones
desiguales. Mantener el período principal y mostrar sensibilidad ayuda más que
buscar una ventana que produzca significación. Una separación verano/invierno
sería otro estudio pertinente; requeriría modelar y probar las diferencias,
sin asumir que dos signos distintos demuestran tendencias opuestas.

## Datos largos de Giovanni: oportunidad con una incompatibilidad

Los ocho CSV originales tienen 252 observaciones mensuales de 2005–2025,
salvo precipitación, con 249 hasta septiembre de 2025. Sus enlaces contienen
`shape=state_dept_countries_2017/shp_42`, una selección de la colección de países.
El inventario no acredita que representen el polígono administrativo de
La Araucanía; la geometría concreta de ese identificador no fue verificada.

Por tanto, **no se concatenaron con las series regionales**. Una ampliación
temporal requeriría repetir la extracción con igual geometría, producto,
versión, definición y agregación. Más años pueden aumentar la información,
pero no garantizan significación ni una pendiente constante.

También hay definiciones que el nombre de archivo puede ocultar:

- `sequedad_del_suelo_fines2025.csv` contiene **humedad de zona radicular**, no
  un índice de sequedad ni la misma capa superficial de 0–10 cm del análisis.
- `Particulas_atmosfericas_humo.csv` contiene **AODANA**, profundidad óptica de
  aerosoles; no identifica humo de incendios locales ni concentración de PM2.5.
- TLML y SPEEDLML corresponden al nivel bajo del modelo; no deben sustituir
  automáticamente temperatura a 2 m o viento a 10 m.
- El producto y las unidades de precipitación deben comprobarse antes de
  acumular. NASA distingue tasas y acumulaciones en su
  [guía IMERG](https://gpm.nasa.gov/data/imerg).

## Si posteriormente se amplía la adquisición

Los metadatos locales registran que se detuvo la adquisición para mantener el
alcance acotado. Esta revisión no reactivó descargas ni los trabajos cancelados.

La ampliación con mejor pregunta científica sería **separar cantidad de
incendios y superficie afectada**: «¿cambia cuánto se quema aunque no cambie
igual el número de incendios?». CONAF publica un
[resumen de ocurrencia y daño por comuna](https://www.conaf.cl/centro-documental/resumen-de-ocurrencia-y-dano-por-comuna-1985-2023/).
La página y el adjunto fueron localizados; la planilla no fue descargada ni
validada en esta revisión.

Para una capa satelital de área quemada, MCD64A1 es un producto mensual de
500 m con información de calidad, según su
[guía oficial](https://lpdaac.usgs.gov/documents/1006/MCD64_User_Guide_V61.pdf).
Permitiría investigar área afectada con un indicador distinto del registro
administrativo, conservando limitaciones de detección y comparabilidad.
Los puntos de calor FIRMS no equivalen a incendios individuales ni deben
convertirse automáticamente en hectáreas; NASA explica esta limitación en
su [capacitación FIRMS](https://appliedsciences.nasa.gov/sites/default/files/2025-05/Part%203%20FIRMS%202025%20Q%26A%20Session.docx.pdf).

Una segunda ampliación sería observar recuperación del verdor con MODIS NDVI/EVI
en áreas afectadas, comparadas con áreas de referencia y meses equivalentes.
Los productos y sus escalas están descritos en la
[guía MODIS de índices de vegetación](https://landweb.modaps.eosdis.nasa.gov/data/userguide/MODISC6VIUserguide.pdf).
Recuperar verdor no demuestra recuperar bosque nativo o biodiversidad. Esta
línea necesita más procesamiento y no es necesaria para la primera demo.

## Encaje y relato de la presentación

El [desafío oficial](https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/)
pide seleccionar variables, visualizar series y responder qué cambia, dónde,
cuánto y con qué significación. El caso de incendios aporta una pregunta local
y contexto real; el recorrido de investigación debe hacer visibles esas cuatro
respuestas.

Relato sugerido para la demo:

> «En La Araucanía preguntamos qué está cambiando en las condiciones ambientales.
> La tendencia de temperatura media es incierta en 2014–2023. Al investigar
> otras variables, encontramos evidencia exploratoria de picos mensuales más
> altos y aire con menos humedad. DeHecho muestra cuánto cambian, la
> incertidumbre y los límites de la medición. Después permite contrastarlos
> con los incendios registrados por CONAF, sin confundir asociación con causa».

## Reproducción

Desde la raíz de DeHecho:

```sh
python3 scripts/explorar_valor.py
```

No requiere instalar paquetes. Exporta CSV y JSON a esta carpeta, conserva
huellas de las fuentes y verifica su concordancia con los cuatro ajustes
regionales existentes. Las fórmulas y advertencias quedan en el JSON. No
modifica datos de origen, publicaciones, notebooks ni contratos de la API.
