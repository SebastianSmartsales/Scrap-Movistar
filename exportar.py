"""Convierte data/rucs.csv en data/rucs_movistar.xlsx (RUC | Razón social | Tipo de cliente | Subtipo de cliente)."""
import json
import os

import pandas as pd
from openpyxl.utils import get_column_letter

import sesion

CSV = os.path.join(sesion.DATA, "rucs.csv")
XLSX = os.path.join(sesion.DATA, "rucs_movistar.xlsx")
PROGRESO = os.path.join(sesion.DATA, "progreso.json")


def leer() -> pd.DataFrame:
    """Une todas las pasadas (data/pasada*.csv y data/rucs.csv) y limpia los BOM que dejó la primera versión."""
    archivos = sorted(f for f in os.listdir(sesion.DATA) if f.startswith("pasada") and f.endswith(".csv"))
    rutas = [os.path.join(sesion.DATA, f) for f in archivos] + [CSV]
    print("Pasadas:", [os.path.basename(r) for r in rutas])
    df = pd.concat([pd.read_csv(r, dtype=str, keep_default_na=False, encoding="utf-8-sig") for r in rutas])
    return df.apply(lambda c: c.str.replace("\ufeff", "", regex=False).str.strip())


def main() -> None:
    df = leer()
    leidas = len(df)
    df = df.drop_duplicates(subset="ruc", keep="first")
    print(f"Filas leídas: {leidas}; únicas por RUC: {len(df)}; duplicadas: {leidas - len(df)}")
    if os.path.exists(PROGRESO):
        total = json.load(open(PROGRESO)).get("total_portal")
        print(f"Total que informó el portal: {total}; diferencia: {total - len(df) if total else '?'}")
    print("Por tipo de documento:", df["tipo_doc"].value_counts().to_dict())
    print("Por estado:", df["estado"].value_counts().to_dict())
    print("Por tipo de cliente:", df["tipo_cliente"].replace("", "(vacío)").value_counts().to_dict())

    out = df[["ruc", "razon_social", "tipo_cliente", "subtipo_cliente"]]
    out.columns = ["RUC", "Razón social", "Tipo de cliente", "Subtipo de cliente"]
    with pd.ExcelWriter(XLSX, engine="openpyxl") as w:
        out.to_excel(w, index=False, sheet_name="Movistar")
        ws = w.sheets["Movistar"]
        for fila in ws.iter_rows(min_row=2, max_col=1):
            fila[0].number_format = "@"
        for i, ancho in enumerate((14, 70, 22, 34), 1):
            ws.column_dimensions[get_column_letter(i)].width = ancho
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    print(f"Guardado: {XLSX}")


if __name__ == "__main__":
    main()
