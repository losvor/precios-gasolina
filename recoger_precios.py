"""
Descarga los precios de todas las gasolineras de España desde la API pública
del Ministerio para la Transición Ecológica y los guarda en la carpeta datos/.

Usa el servicio histórico de la API, que da los precios de cualquier día pasado.
Así toda la serie (la de años anteriores y la de cada día nuevo) sale de la misma fuente.

Cada día procesado genera o actualiza:
  - datos/precios/AAAA/AAAA-MM-DD.csv.gz -> un archivo por día con los precios
  - datos/estaciones.csv                  -> listado de gasolineras (ubicación, marca...)

Uso:
  python recoger_precios.py                           # precios de ayer
  python recoger_precios.py --fecha 2024-01-01        # un día concreto
  python recoger_precios.py --desde 2022-01-01        # desde esa fecha hasta ayer
  python recoger_precios.py --desde 2022-01-01 --hasta 2022-12-31
  python recoger_precios.py --archivo datos.json      # procesa un JSON guardado (para pruebas)
  Añade --forzar para volver a descargar días que ya existen.
"""

import argparse
import json
import re
import subprocess
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# Precios de toda España en un día concreto (la fecha va en formato DD-MM-AAAA).
URL_HISTORICO = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
    "PreciosCarburantes/EstacionesTerrestresHist/{fecha}"
)

CARPETA_DATOS = Path(__file__).parent / "datos"
ZONA_HORARIA = ZoneInfo("Europe/Madrid")

# En España hay unas 12.000 gasolineras. Si llegan muchas menos, la respuesta está incompleta.
MINIMO_ESTACIONES = 5000

# Pausa entre días al descargar varios seguidos, para no saturar el servidor del Ministerio.
PAUSA_ENTRE_DIAS = 2  # segundos

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


class ErrorDescarga(Exception):
    """No se pudieron conseguir los datos de un día."""


def descargar(url: str, intentos: int = 3) -> dict:
    """Pide los datos a la API con curl. Si falla, espera y lo vuelve a intentar.

    Usamos curl en vez de la librería requests porque el servidor del Ministerio
    corta a veces las conexiones que vienen de Python, y con curl responde siempre.
    """
    orden = ["curl", "--silent", "--show-error", "--fail", "--compressed",
             "--max-time", "300", "--header", "Accept: application/json", url]
    for intento in range(1, intentos + 1):
        resultado = subprocess.run(orden, capture_output=True)
        if resultado.returncode == 0:
            try:
                datos = json.loads(resultado.stdout)
                if datos.get("ResultadoConsulta") == "OK":
                    return datos
                error = f"la API respondió: {datos.get('ResultadoConsulta')}"
            except json.JSONDecodeError as e:
                error = f"la respuesta no es un JSON válido ({e})"
        else:
            error = resultado.stderr.decode(errors="replace").strip()
        print(f"  Intento {intento}/{intentos} fallido: {error}")
        if intento < intentos:
            time.sleep(30 * intento)  # espera 30 s, luego 60 s...
    raise ErrorDescarga(f"no se pudo descargar {url}")


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
    """La API indica la fecha de los precios en el campo 'Fecha', p. ej. '01/01/2024 0:00:00'."""
    try:
        return datetime.strptime(datos["Fecha"], "%d/%m/%Y %H:%M:%S").date()
    except (KeyError, TypeError, ValueError):
        return None


def ruta_del_dia(fecha: date, carpeta: Path) -> Path:
    return carpeta / "precios" / str(fecha.year) / f"{fecha.isoformat()}.csv.gz"


def dias_entre(desde: date, hasta: date) -> list[date]:
    """Todos los días de 'desde' a 'hasta', ambos incluidos."""
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]


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
    for columna in nuevas.columns:
        nuevas[columna] = nuevas[columna].astype(str).str.strip()  # quita espacios sobrantes
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


def procesar(datos: dict, fecha: date, carpeta: Path) -> tuple[Path, int, int]:
    estaciones_api = pd.DataFrame(datos["ListaEESSPrecio"])
    ruta, filas = guardar_precios(estaciones_api, fecha, carpeta)
    total_estaciones = actualizar_estaciones(estaciones_api, fecha, carpeta)
    return ruta, filas, total_estaciones


def recoger_dia(fecha: date, forzar: bool = False) -> bool:
    """Descarga y guarda un día. Devuelve True si hay datos de ese día (nuevos o ya existentes)."""
    if ruta_del_dia(fecha, CARPETA_DATOS).exists() and not forzar:
        print(f"{fecha}: ya descargado.")
        return True
    inicio = time.time()
    try:
        datos = descargar(URL_HISTORICO.format(fecha=fecha.strftime("%d-%m-%Y")))
        recibidas = len(datos.get("ListaEESSPrecio", []))
        if recibidas < MINIMO_ESTACIONES:
            raise ErrorDescarga(f"solo llegaron {recibidas} gasolineras, la respuesta parece incompleta")
    except ErrorDescarga as error:
        print(f"{fecha}: ERROR, {error}")
        return False
    _, filas, total = procesar(datos, fecha, CARPETA_DATOS)
    segundos = time.time() - inicio
    print(f"{fecha}: guardados los precios de {filas} gasolineras ({total} en el listado, {segundos:.0f} s).")
    return True


def leer_fecha(texto: str) -> date:
    return datetime.strptime(texto, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga los precios de las gasolineras de España.")
    parser.add_argument("--fecha", type=leer_fecha, help="un día concreto (AAAA-MM-DD)")
    parser.add_argument("--desde", type=leer_fecha, help="primer día de un rango (AAAA-MM-DD)")
    parser.add_argument("--hasta", type=leer_fecha, help="último día del rango (por defecto, ayer)")
    parser.add_argument("--archivo", help="procesar un JSON guardado en vez de descargarlo")
    parser.add_argument("--forzar", action="store_true", help="descargar aunque el día ya exista")
    args = parser.parse_args()

    if args.archivo:
        datos = json.loads(Path(args.archivo).read_text(encoding="utf-8"))
        fecha = fecha_de_la_api(datos) or datetime.now(ZONA_HORARIA).date()
        ruta, filas, total = procesar(datos, fecha, CARPETA_DATOS)
        print(f"Guardados los precios de {filas} gasolineras en {ruta} ({total} en el listado).")
        return

    ayer = datetime.now(ZONA_HORARIA).date() - timedelta(days=1)
    if args.desde:
        dias = dias_entre(args.desde, min(args.hasta or ayer, ayer))
    else:
        dias = [args.fecha or ayer]

    fallidos = []
    for numero, dia in enumerate(dias, start=1):
        descargado_ya = ruta_del_dia(dia, CARPETA_DATOS).exists() and not args.forzar
        if not recoger_dia(dia, args.forzar):
            fallidos.append(dia)
        if numero < len(dias) and not descargado_ya:
            time.sleep(PAUSA_ENTRE_DIAS)

    if fallidos:
        lista = ", ".join(str(d) for d in fallidos)
        raise SystemExit(f"{len(fallidos)} de {len(dias)} días fallaron: {lista}. "
                         "Se reintentarán en la próxima ejecución.")
    print(f"Listo: {len(dias)} día(s) procesado(s).")


if __name__ == "__main__":
    main()
