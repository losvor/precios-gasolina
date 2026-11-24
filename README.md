# Precios de la gasolina en España

Recogida automática y diaria de los precios de **todas las gasolineras de España**, para analizar
después si los precios **suben rápido cuando sube el petróleo y bajan despacio cuando baja**
(el llamado efecto "cohetes y plumas").

> Estado: fase 1, recogida de datos. El análisis llegará cuando haya varios meses de histórico.

## Cómo funciona

1. Cada mañana, GitHub Actions ejecuta `recoger_precios.py` de forma automática.
2. El script descarga los precios de la API pública del Ministerio para la Transición Ecológica.
3. Guarda los precios del día y actualiza el listado de gasolineras en la carpeta `datos/`.
4. GitHub guarda esos archivos en el repositorio, así que el histórico crece solo cada día.

Si la descarga de la mañana falla, hay un segundo intento por la tarde. Si el archivo del día ya
existe, el script no hace nada.

## Datos que genera

**`datos/precios/AAAA/AAAA-MM-DD.csv.gz`**: un archivo por día (comprimido; pandas lo lee directamente).

| Columna | Significado |
|---|---|
| `fecha` | Día de los precios |
| `id_estacion` | Identificador de la gasolinera (une con `estaciones.csv`) |
| `gasolina_95_e5`, `gasoleo_a`, ... | Precio en €/litro de cada combustible (vacío si no lo vende) |

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

```bash
pip install -r requirements.txt
python recoger_precios.py                      # precios de hoy
python recoger_precios.py --fecha 01-11-2026   # (experimental) un día pasado
```

Pruebas automáticas con datos de ejemplo (no necesitan internet):

```bash
pip install pytest
pytest
```

## Fuente

Ministerio para la Transición Ecológica y el Reto Demográfico, Geoportal de Gasolineras
(servicio REST de precios de carburantes, publicado en [datos.gob.es](https://datos.gob.es/es/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas)).
