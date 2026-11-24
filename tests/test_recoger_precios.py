"""Pruebas del script con datos de ejemplo (no necesitan internet).
Para ejecutarlas: pip install pytest && pytest
"""

import copy
import json
from datetime import date
from pathlib import Path

import pandas as pd

from recoger_precios import fecha_de_la_api, nombre_corto, procesar

EJEMPLO = json.loads((Path(__file__).parent / "ejemplo_api.json").read_text(encoding="utf-8"))


def test_nombre_corto():
    assert nombre_corto("Precio Gasolina 95 E5") == "gasolina_95_e5"
    assert nombre_corto("Precio Gases licuados del petróleo") == "gases_licuados_del_petroleo"


def test_fecha_de_la_api():
    assert fecha_de_la_api(EJEMPLO) == date(2026, 11, 24)


def test_guarda_precios_como_numeros(tmp_path):
    ruta, filas, _ = procesar(EJEMPLO, date(2026, 11, 24), tmp_path)

    assert ruta == tmp_path / "precios" / "2026" / "2026-11-24.csv.gz"
    precios = pd.read_csv(ruta)
    assert filas == 2  # la gasolinera sin ningún precio no se guarda
    granada = precios.set_index("id_estacion").loc[11500]
    assert granada["gasolina_95_e5"] == 1.529
    assert pd.isna(granada["gases_licuados_del_petroleo"])


def test_estaciones_conservan_ceros_y_fechas(tmp_path):
    procesar(EJEMPLO, date(2026, 11, 24), tmp_path)

    # Al día siguiente una gasolinera cambia de marca y otra desaparece.
    dia_2 = copy.deepcopy(EJEMPLO)
    dia_2["ListaEESSPrecio"][0]["Rótulo"] = "GALP"
    dia_2["ListaEESSPrecio"].pop(1)
    procesar(dia_2, date(2026, 11, 25), tmp_path)

    estaciones = pd.read_csv(tmp_path / "estaciones.csv", dtype={"cp": str, "id_provincia": str})
    estaciones = estaciones.set_index("id_estacion")

    assert len(estaciones) == 3  # la desaparecida sigue en el listado
    assert estaciones.loc[4375, "cp"] == "02250"  # el cero inicial no se pierde
    assert estaciones.loc[4375, "vista_por_ultima_vez"] == "2026-11-24"
    assert estaciones.loc[11500, "rotulo"] == "GALP"  # datos más recientes
    assert estaciones.loc[11500, "vista_por_primera_vez"] == "2026-11-24"
    assert estaciones.loc[11500, "vista_por_ultima_vez"] == "2026-11-25"
