"""Pruebas del script con datos de ejemplo (no necesitan internet).
Para ejecutarlas: pip install pytest && pytest
"""

import copy
import json
from datetime import date
from pathlib import Path

import pandas as pd

import recoger_precios
from recoger_precios import dias_entre, fecha_de_la_api, nombre_corto, procesar

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


def test_dias_entre():
    dias = dias_entre(date(2024, 2, 27), date(2024, 3, 1))
    assert dias == [date(2024, 2, 27), date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]


def test_recoger_dia_descarga_y_luego_salta(tmp_path, monkeypatch):
    urls = []

    def descarga_falsa(url, intentos=3):
        urls.append(url)
        return EJEMPLO

    monkeypatch.setattr(recoger_precios, "descargar", descarga_falsa)
    monkeypatch.setattr(recoger_precios, "CARPETA_DATOS", tmp_path)
    monkeypatch.setattr(recoger_precios, "MINIMO_ESTACIONES", 1)

    assert recoger_precios.recoger_dia(date(2024, 1, 1))
    assert urls[0].endswith("/EstacionesTerrestresHist/01-01-2024")  # formato de fecha de la API
    assert (tmp_path / "precios" / "2024" / "2024-01-01.csv.gz").exists()

    assert recoger_precios.recoger_dia(date(2024, 1, 1))  # ya existe: no vuelve a descargar
    assert len(urls) == 1


def test_recoger_dia_rechaza_respuestas_incompletas(tmp_path, monkeypatch):
    monkeypatch.setattr(recoger_precios, "descargar", lambda url, intentos=3: EJEMPLO)
    monkeypatch.setattr(recoger_precios, "CARPETA_DATOS", tmp_path)

    assert not recoger_precios.recoger_dia(date(2024, 1, 1))  # 3 gasolineras < mínimo
    assert not (tmp_path / "precios").exists()
