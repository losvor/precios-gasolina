# Precios de la gasolina en España

Recogida automática de los precios diarios de **todas las gasolineras de España** desde 2022,
para analizar después si los precios **suben rápido cuando sube el petróleo y bajan despacio
cuando baja** (el llamado efecto "cohetes y plumas").

> Estado: fase 1, recogida de datos. El análisis vendrá después.

## Cómo funciona

- **Cada mañana**, GitHub Actions ejecuta `recoger_precios.py`, que descarga los precios del día
  anterior y revisa la última semana por si algún día falló.
- **El histórico** (desde enero de 2022) se rellena con el proceso `Rellenar histórico de precios`.
  El Ministerio tarda unos 30 s por día, así que se hace en tandas automáticas cada 6 horas que
  continúan donde lo dejó la anterior. Se puede lanzar a mano desde la pestaña Actions con otras
  fechas para añadir años anteriores.
- Todo sale del **servicio histórico de la API del Ministerio**, que da los precios de cualquier día.
  Usar siempre la misma fuente evita mezclar datos tomados de formas distintas.
- Los archivos se guardan en la carpeta `datos/` del propio repositorio.

### Decisiones técnicas

- **Descarga con `curl`, no con `requests`.** Al probarlo en GitHub, el servidor del Ministerio
  cortaba a veces las conexiones de Python durante el inicio de la conexión segura (TLS),
  mientras que `curl` respondía siempre. Python se encarga del procesado.
- **Control de calidad:** si llegan menos de 5.000 gasolineras (hay unas 12.000), el día se
  descarta y se reintenta en la siguiente ejecución.
- **Archivos comprimidos y deterministas:** cada día ocupa poco, y si se vuelve a descargar con
  los mismos datos el archivo es idéntico, así que no genera cambios innecesarios.

## Datos que genera

**`datos/precios/AAAA/AAAA-MM-DD.csv.gz`**: un archivo por día (comprimido; pandas lo lee directamente).

| Columna | Significado |
|---|---|
| `fecha` | Día de los precios |
| `id_estacion` | Identificador de la gasolinera (une con `estaciones.csv`) |
| `gasolina_95_e5`, `gasoleo_a`, ... | Precio en € de cada combustible (vacío si no lo vende) |

**`datos/estaciones.csv`**: una fila por gasolinera.

| Columna | Significado |
|---|---|
| `id_estacion` | Identificador de la gasolinera |
| `rotulo` | Marca o nombre (Repsol, Cepsa, Ballenoil...) |
| `direccion`, `cp`, `localidad`, `municipio`, `provincia` | Ubicación |
| `latitud`, `longitud` | Coordenadas para mapas |
| `vista_por_primera_vez`, `vista_por_ultima_vez` | Primer y último día en que apareció en los datos |

Leer los datos en Python:

```python
import pandas as pd
from pathlib import Path

precios = pd.concat(pd.read_csv(f) for f in Path("datos/precios").rglob("*.csv.gz"))
estaciones = pd.read_csv("datos/estaciones.csv", dtype={"cp": str})
datos = precios.merge(estaciones, on="id_estacion")
```

## Ejecutarlo en tu ordenador

Necesitas Python 3.10 o superior y `curl` (viene instalado en Mac y Linux).

```bash
pip install -r requirements.txt
python recoger_precios.py                       # precios de ayer
python recoger_precios.py --fecha 2024-01-01    # un día concreto
python recoger_precios.py --desde 2024-01-01 --hasta 2024-01-31
```

Pruebas automáticas con datos de ejemplo (no necesitan internet):

```bash
pip install pytest
pytest
```

## Fuente

Ministerio para la Transición Ecológica y el Reto Demográfico, Geoportal de Gasolineras
(servicio REST de precios de carburantes, publicado en [datos.gob.es](https://datos.gob.es/es/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas)).
