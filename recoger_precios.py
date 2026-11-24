"""
Descarga los precios de todas las gasolineras de España desde la API pública
del Ministerio para la Transición Ecológica y los guarda en la carpeta datos/.

Cada ejecución genera o actualiza:
  - datos/precios/AAAA/AAAA-MM-DD.csv.gz -> un archivo por día con los precios
  - datos/estaciones.csv                  -> listado de gasolineras (ubicación, marca...)

Uso:
  python recoger_precios.py                       # precios de hoy
  python recoger_precios.py --forzar              # repite la descarga aunque ya exista el archivo de hoy
  python recoger_precios.py --fecha 01-11-2026    # (experimental) precios de un día pasado
  python recoger_precios.py --archivo datos.json  # procesa un JSON guardado (para pruebas)
"""

import argparse
import json
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

URL_BASE = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes"
URL_HOY = f"{URL_BASE}/EstacionesTerrestres/"
URL_HISTORICO = f"{URL_BASE}/EstacionesTerrestresHist/{{fecha}}"  # fecha en formato DD-MM-AAAA

# Sin estas cabeceras el servidor responde en XML o puede rechazar la petición.
CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

CARPETA_DATOS = Path(__file__).parent / "datos"
ZONA_HORARIA = ZoneInfo("Europe/Madrid")

# En España hay unas 12.000 gasolineras. Si llegan muchas menos, la respuesta está incompleta.
MINIMO_ESTACIONES = 5000

# Datos de cada gasolinera: nombre en la API -> nombre en nuestro CSV.
COLUMNAS_ESTACIONES = {
    "IDEESS": "id_estacion",
    "Rótulo": "rotulo",
    "Dirección": "direccion",
    "C.P.": "cp",
    "Localidad": "localidad",
    "Municipio": "municipio",
    "IDMunicipio": "id_municipio",
    "Provincia": "provincia",
    "IDProvincia": "id_provincia",
    "IDCCAA": "id_ccaa",
    "Latitud": "latitud",
    "Longitud (WGS84)": "longitud",
    "Margen": "margen",
    "Tipo Venta": "tipo_venta",
    "Remisión": "remision",
    "Horario": "horario",
}

# Códigos que llevan ceros a la izquierda ("02", "02250"): se leen como texto para no perderlos.
COLUMNAS_TEXTO = ["cp", "id_municipio", "id_provincia", "id_ccaa"]


def descargar(url: str, intentos: int = 3) -> dict:
    """Pide los datos a la API. Si falla, espera y lo vuelve a intentar."""
    for intento in range(1, intentos + 1):
        try:
            print(f"Descargando {url} (intento {intento}/{intentos})...")
            respuesta = requests.get(url, headers=CABECERAS, timeout=180)
            respuesta.raise_for_status()  # error si el servidor no responde "200 OK"
            datos = respuesta.json()
            if datos.get("ResultadoConsulta") != "OK":
                raise ValueError(f"la API respondió: {datos.get('ResultadoConsulta')}")
            return datos
        except (requests.RequestException, ValueError) as error:
            print(f"  Falló: {error}")
            if intento < intentos:
                time.sleep(30 * intento)  # espera 30 s, luego 60 s...
    raise SystemExit("No se pudieron descargar los datos. Se reintentará en la próxima ejecución.")


def a_numero(columna: pd.Series) -> pd.Series:
    """Convierte textos como '1,529' en números (1.529). Los vacíos quedan como NaN."""
    texto = columna.astype(str).str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(texto, errors="coerce")


def nombre_corto(columna: str) -> str:
    """'Precio Gasolina 95 E5' -> 'gasolina_95_e5' (sin tildes ni espacios)."""
    texto = columna.removeprefix("Precio ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def fecha_de_la_api(datos: dict) -> date | None:
    """La API indica la fecha de los precios en el campo 'Fecha', p. ej. '24/11/2026 7:30:15'."""
    try:
        return datetime.strptime(datos["Fecha"], "%d/%m/%Y %H:%M:%S").date()
    except (KeyError, TypeError, ValueError):
        return None


def ruta_del_dia(fecha: date, carpeta: Path) -> Path:
    return carpeta / "precios" / str(fecha.year) / f"{fecha.isoformat()}.csv.gz"


def guardar_precios(estaciones_api: pd.DataFrame, fecha: date, carpeta: Path) -> tuple[Path, int]:
    """Guarda una fila por gasolinera con el precio de cada combustible ese día."""
    columnas_precio = [c for c in estaciones_api.columns if c.startswith("Precio ")]

    precios = pd.DataFrame({
        "fecha": fecha.isoformat(),
        "id_estacion": pd.to_numeric(estaciones_api["IDEESS"]),
    })
    for columna in columnas_precio:
        precios[nombre_corto(columna)] = a_numero(estaciones_api[columna])

    # Fuera las gasolineras que ese día no tenían ningún precio publicado.
    combustibles = [nombre_corto(c) for c in columnas_precio]
    precios = precios.dropna(subset=combustibles, how="all").sort_values("id_estacion")

    ruta = ruta_del_dia(fecha, carpeta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0: si los datos no cambian, el archivo comprimido es idéntico byte a byte.
    precios.to_csv(ruta, index=False, float_format="%.3f",
                   compression={"method": "gzip", "mtime": 0})
    return ruta, len(precios)


def actualizar_estaciones(estaciones_api: pd.DataFrame, fecha: date, carpeta: Path) -> int:
    """Mantiene un listado de todas las gasolineras vistas, con la primera y última fecha
    en que aparecieron. Así se puede saber cuáles abren, cierran o cambian de marca."""
    disponibles = [c for c in COLUMNAS_ESTACIONES if c in estaciones_api.columns]
    nuevas = estaciones_api[disponibles].rename(columns=COLUMNAS_ESTACIONES)
    nuevas["id_estacion"] = pd.to_numeric(nuevas["id_estacion"])
    for columna in ("latitud", "longitud"):
        if columna in nuevas:
            nuevas[columna] = a_numero(nuevas[columna])
    nuevas["vista_por_primera_vez"] = fecha.isoformat()
    nuevas["vista_por_ultima_vez"] = fecha.isoformat()

    ruta = carpeta / "estaciones.csv"
    if ruta.exists():
        tipos = {c: str for c in COLUMNAS_TEXTO}
        antiguas = pd.read_csv(ruta, dtype=tipos, keep_default_na=False, na_values=[""])
        todas = pd.concat([antiguas, nuevas], ignore_index=True)
    else:
        todas = nuevas

    # Primera fecha en que se vio cada gasolinera (la más antigua de todas).
    primera_vez = todas.groupby("id_estacion")["vista_por_primera_vez"].min()
    # Para el resto de datos nos quedamos con la versión más reciente de cada gasolinera.
    todas = (todas.sort_values("vista_por_ultima_vez", kind="stable")
                  .drop_duplicates("id_estacion", keep="last")
                  .sort_values("id_estacion"))
    todas["vista_por_primera_vez"] = todas["id_estacion"].map(primera_vez)

    todas.to_csv(ruta, index=False)
    return len(todas)


def procesar(datos: dict, fecha: date, carpeta: Path = CARPETA_DATOS) -> tuple[Path, int, int]:
    estaciones_api = pd.DataFrame(datos["ListaEESSPrecio"])
    ruta, filas = guardar_precios(estaciones_api, fecha, carpeta)
    total_estaciones = actualizar_estaciones(estaciones_api, fecha, carpeta)
    return ruta, filas, total_estaciones


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga los precios de las gasolineras de España.")
    parser.add_argument("--fecha", help="(experimental) día pasado en formato DD-MM-AAAA")
    parser.add_argument("--archivo", help="procesar un JSON guardado en vez de descargarlo")
    parser.add_argument("--forzar", action="store_true", help="descargar aunque ya exista el archivo")
    args = parser.parse_args()

    if args.archivo:
        datos = json.loads(Path(args.archivo).read_text(encoding="utf-8"))
        fecha = fecha_de_la_api(datos) or datetime.now(ZONA_HORARIA).date()
    else:
        if args.fecha:
            fecha = datetime.strptime(args.fecha, "%d-%m-%Y").date()
            url = URL_HISTORICO.format(fecha=args.fecha)
        else:
            fecha = datetime.now(ZONA_HORARIA).date()
            url = URL_HOY

        # Si ya tenemos los precios de ese día, no hace falta repetir.
        if ruta_del_dia(fecha, CARPETA_DATOS).exists() and not args.forzar:
            print(f"Ya existen los precios del {fecha}. Nada que hacer.")
            return

        datos = descargar(url)
        if not args.fecha:
            fecha = fecha_de_la_api(datos) or fecha

        recibidas = len(datos.get("ListaEESSPrecio", []))
        if recibidas < MINIMO_ESTACIONES:
            raise SystemExit(f"Solo llegaron {recibidas} gasolineras: la respuesta parece incompleta.")

    ruta, filas, total_estaciones = procesar(datos, fecha)
    print(f"Guardados los precios de {filas} gasolineras en {ruta}")
    print(f"Listado de gasolineras actualizado: {total_estaciones} en total")


if __name__ == "__main__":
    main()
