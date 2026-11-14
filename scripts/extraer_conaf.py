"""Consolida las hojas anuales de data/conaf/conaf.xls en un solo CSV.

Cada hoja 1985..2024 representa una temporada julio-junio con la ocurrencia
de incendios por mes y region. El script conserva los datos tal como estan:
los vacios quedan vacios, los ceros quedan en cero y no se recalculan
TOTAL ni PORCENTAJE.
"""

import csv
from collections import Counter
from pathlib import Path

from python_calamine import CalamineWorkbook

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "data" / "conaf" / "conaf.xls"
SALIDA = RAIZ / "data" / "conaf" / "conaf_anual.csv"

MESES = [
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
]

# Orden de regiones de las hojas mas recientes. Las regiones que aun no
# existian en una temporada quedan vacias, nunca en 0.
REGIONES = [
    "XV", "I", "II", "III", "IV", "V", "RM", "VI", "VII",
    "XVI", "VIII", "IX", "XIV", "X", "XI", "XII",
]

COLUMNAS = ["año", "temporada", "mes", *REGIONES, "TOTAL", "PORCENTAJE"]


def texto(valor):
    return str(valor).strip()


def numero(valor):
    """Devuelve None para celdas vacias; el numero original en otro caso."""
    if valor is None or texto(valor) == "":
        return None
    return float(valor)


def leer_hoja(hoja):
    filas = hoja.to_python()

    fila_cabecera = next(
        i for i, fila in enumerate(filas)
        if fila and texto(fila[0]).upper() == "MES"
    )
    cabecera = [texto(v).upper() for v in filas[fila_cabecera]]
    col_total = cabecera.index("TOTAL") if "TOTAL" in cabecera else None
    col_porcentaje = (
        cabecera.index("PORCENTAJE") if "PORCENTAJE" in cabecera else None
    )

    fila_regiones = filas[fila_cabecera + 1]
    columna_region = {
        texto(codigo): columna
        for columna, codigo in enumerate(fila_regiones)
        if columna > 0 and texto(codigo) != ""
    }

    registros = []
    for fila in filas[fila_cabecera + 2:]:
        if not fila or texto(fila[0]).upper() not in MESES:
            continue
        registro = {"mes": texto(fila[0]).upper()}
        for codigo in REGIONES:
            columna = columna_region.get(codigo)
            registro[codigo] = (
                numero(fila[columna]) if columna is not None
                and columna < len(fila) else None
            )
        registro["TOTAL"] = (
            numero(fila[col_total])
            if col_total is not None and col_total < len(fila) else None
        )
        registro["PORCENTAJE"] = (
            numero(fila[col_porcentaje])
            if col_porcentaje is not None and col_porcentaje < len(fila)
            else None
        )
        registros.append(registro)

    return registros


def leer_total_hoja(hoja):
    """Fila resumen 'Total' de la temporada, si la hoja la trae."""
    filas = hoja.to_python()
    fila_cabecera = next(
        i for i, fila in enumerate(filas)
        if fila and texto(fila[0]).upper() == "MES"
    )
    cabecera = [texto(v).upper() for v in filas[fila_cabecera]]
    if "TOTAL" not in cabecera:
        return None
    col_total = cabecera.index("TOTAL")
    for fila in filas[fila_cabecera + 2:]:
        if fila and texto(fila[0]).upper() == "TOTAL":
            return numero(fila[col_total]) if col_total < len(fila) else None
    return None


def main():
    libro = CalamineWorkbook.from_path(ENTRADA)
    anios = sorted(h for h in libro.sheet_names if h.isdigit())

    filas_csv = []
    discrepancias = []
    sin_regiones = []
    diferencias_total_hoja = []
    suma_total_mensual = Counter()
    vacios_por_temporada = Counter()
    meses_por_temporada = {}

    for anio in anios:
        hoja = libro.get_sheet_by_name(anio)
        registros = leer_hoja(hoja)
        total_hoja = leer_total_hoja(hoja)
        meses_por_temporada[anio] = [r["mes"] for r in registros]
        temporada = f"{int(anio) - 1}-{anio}"

        # Orden julio -> junio; se conserva lo que exista en la hoja.
        registros.sort(key=lambda r: MESES.index(r["mes"])
                       if r["mes"] in MESES else len(MESES))

        for registro in registros:
            valores_region = [registro[c] for c in REGIONES]
            presente = [v for v in valores_region if v is not None]
            vacios_por_temporada[anio] += len(REGIONES) - len(presente)

            if registro["TOTAL"] is not None and presente:
                suma = sum(presente)
                if abs(suma - registro["TOTAL"]) > 1e-6:
                    discrepancias.append(
                        (anio, registro["mes"], suma, registro["TOTAL"])
                    )
            elif registro["TOTAL"] not in (None, 0.0):
                sin_regiones.append((anio, registro["mes"], registro["TOTAL"]))

            if registro["TOTAL"] is not None:
                suma_total_mensual[anio] += registro["TOTAL"]

            filas_csv.append({
                "año": int(anio),
                "temporada": temporada,
                "mes": registro["mes"],
                **{c: registro[c] for c in REGIONES},
                "TOTAL": registro["TOTAL"],
                "PORCENTAJE": registro["PORCENTAJE"],
            })

        if total_hoja is not None:
            if abs(suma_total_mensual[anio] - total_hoja) > 1e-6:
                diferencias_total_hoja.append(
                    (anio, suma_total_mensual[anio], total_hoja)
                )

    with SALIDA.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS)
        escritor.writeheader()
        for fila in filas_csv:
            escritor.writerow({
                columna: "" if valor is None else valor
                for columna, valor in fila.items()
            })

    print(f"Temporadas: {len(anios)} ({anios[0]}..{anios[-1]})")
    print(f"Filas escritas: {len(filas_csv)}")
    print(f"Archivo: {SALIDA}")

    incompletas = {
        anio: [m for m in MESES if m not in meses]
        for anio, meses in meses_por_temporada.items()
        if len(meses) != 12
    }
    print(f"Temporadas con meses faltantes: {len(incompletas)}")
    for anio, faltan in incompletas.items():
        print(f"  {anio}: faltan {', '.join(faltan) or 'ninguno'} ({len(meses_por_temporada[anio])} meses)")

    print(f"Discrepancias suma-regiones vs TOTAL: {len(discrepancias)}")
    for anio, mes, suma, total in discrepancias[:20]:
        print(f"  {anio} {mes}: suma={suma:g} TOTAL={total:g}")

    print(f"Filas sin regiones pero con TOTAL distinto de 0: {len(sin_regiones)}")
    for anio, mes, total in sin_regiones[:20]:
        print(f"  {anio} {mes}: TOTAL={total:g}")

    print(f"Temporadas cuya suma mensual no cuadra con su fila Total: {len(diferencias_total_hoja)}")
    for anio, suma, total in diferencias_total_hoja:
        print(f"  {anio}: suma={suma:g} fila Total={total:g}")

    print("Vacíos por temporada (de 16 regiones x mes):")
    for anio in anios:
        print(f"  {anio}: {vacios_por_temporada[anio]}")


if __name__ == "__main__":
    main()
