# CS2 Data Analysis

Herramienta para analizar demos de Counter-Strike 2 (`.dem`): una app web (Streamlit) con cinco vistas
y una CLI para exportar todo a CSV/Parquet. El parseo usa [demoparser2](https://github.com/LaihoE/demoparser),
que está escrito en Rust y procesa una demo de 60 MB en ~2 s. Además, cada demo se guarda en caché
(Parquet), así que la segunda vez que se abre carga al instante.

## Instalación

```bash
pip install -e .            # o: pip install -r requirements.txt
streamlit run app.py        # o: cs2a app
```

Para precargar una carpeta al abrir la app: `streamlit run app.py -- --demos ~/demos` (o `cs2a app --demos ~/demos`).

## Vistas

| Vista | Qué muestra |
|---|---|
| 🎯 **Demo individual** | Marcador, **aim y micro-game** (TTD, reacción, crosshair placement, pre-aim/flick/prefire, TTK, counter-strafe, precisión de primera bala y de spray, indicadores a revisar), scoreboard por equipo (K/D/A, ADR, HS%, KAST, entries, tradeos, multikills, clutches, utilidad, precisión, Rating 1.0/2.0), ronda a ronda con kill feed, economía (valor de equipo y win rate según el tipo de compra), detalle por jugador (armas, clutches, rivales, mapa de kills/muertes), matriz de duelos, duelos de apertura, tradeos, utilidad (con el mapa de granadas), **tácticas** (a qué sitio va cada equipo de T, timing de plante, lineups repetidos dibujados desde dónde se lanzan hasta dónde caen) y mapas de calor de posiciones con filtros por lado, jugador, rondas y segundos de ronda. |
| 📚 **Multi-demo** | Lista de partidas, leaderboard agregado (calculado sobre el total de rondas, no como promedio de promedios), comparación de hasta 4 jugadores, evolución por partida y resumen por mapa, ya sea general o desde la perspectiva de un jugador, más **tácticas por equipo** sumando las partidas de un mismo mapa: sitios y lineups que un rival repite entre partidas. |
| 📊 **Dashboard** | Vista resumida. Sin jugador foco muestra la biblioteca completa: partidas por mapa, rondas por lado, armas, cómo terminan las rondas y top jugadores. Con jugador foco muestra sus KPIs, el rating por partida, el winrate por mapa, el ADR por lado, las armas y los multikills. |
| 🈯 **Datos crudos traducidos** | Las tablas normalizadas con columnas en español y valores legibles: T/CT, nombres de armas, zonas del mapa, motivo de fin de ronda, Sí/No y tiempos de ronda en segundos. Se pueden filtrar y descargar. |
| 🧾 **Datos crudos** | (1) Las tablas tal cual quedan en la caché. (2) Cualquier evento del juego tal como lo entrega demoparser2, con props extra a elección. (3) Un explorador de ticks: cualquier prop por jugador, por ronda y cada N ticks. (4) El header de la demo. |

## Archivo `.cs2a`

Formato propio para guardar y compartir análisis. Una demo de 500 MB queda en ~300 KB (alrededor de 1500 veces más chica),
y la app y la CLI lo abren sin el `.dem` original.

```bash
cs2a pack ~/demos -o temporada.cs2a      # muchas demos -> un archivo
cs2a info temporada.cs2a                 # qué contiene, sin cargarlo
```

En la app: subir `.cs2a` como cualquier demo, y el botón **💾 Guardar sesión (.cs2a)**.

No es un formato binario cerrado: es un ZIP con un índice `cs2a.json` y una tabla Parquet por demo, así que también
se abre con `unzip` + pandas/polars/DuckDB. Lo compacto sale de usar zstd 19 y diccionarios, de reducir los tipos
y de cuantizar las posiciones a int16 ordenadas por jugador con `DELTA_BINARY_PACKED`: las trayectorias son continuas
y las diferencias, chicas. La caché local usa el mismo formato. La especificación está en `cs2analysis/storage.py`.

## Aim y micro-game

Cada kill con arma de fuego se reconstruye tick a tick en los 3 s previos: posiciones, ángulos de mira, agachado y
disparos. Para saber *desde cuándo* el atacante veía a la víctima se calcula **línea de visión real** contra la malla
de colisión del mapa, teniendo en cuenta los humos activos (`cs2a assets` baja las mallas). Sin malla se usa el
`approximate_spotted_by` del juego, que es menos preciso.

| Métrica | Definición |
|---|---|
| TTD | De tener línea de visión al primer daño (mediana) |
| Reacción | De tener línea de visión al primer disparo |
| Crosshair placement | Ángulo mira→cabeza del rival en ese instante, total y vertical |
| Pre-aim / flick / prefire | ≤ 3° · ≥ 10° y disparo en ≤ 500 ms · disparó antes de ver |
| TTK / tiempo hasta morir | Primer daño → kill, visto del lado del atacante y de la víctima |
| Counter-strafe | Disparos con velocidad ≤ 34% de la máxima del arma |
| Precisión 1ª bala / spray | Impactos de la 1ª bala de cada ráfaga / de la 4ª en adelante |
| Mal parado | Muertes en las que la víctima miraba a > 45° de su asesino |
| Indicadores a revisar | Snaps inhumanos (≥ 30° en ≤ 100 ms, sin spray previo, a ≥ 5 m) y kills sin visión + wallbangs |

Validación:
- En las kills por headshot, la mira está a 0.86° de la cabeza en el tick de la kill, contra 3.3° en las kills al cuerpo
  (con la mira más baja). Esto confirma la convención de ángulos y las alturas de ojos y cabeza.
- En demos de FACEIT y HLTV los valores son humanos: TTD de ~300-500 ms, crosshair placement de 1.3-5°.
- La demo de matchmaking de Valve incluida en las fixtures tiene dos jugadores que matan casi todo a través de
  paredes y giran 60-80° en menos de 100 ms. Los indicadores los marcan a ellos y a nadie en las demos limpias,
  y eso quedó como test de regresión.

## CLI

```bash
cs2a stats partida.dem                   # scoreboard en la terminal
cs2a export partida.dem -o exports       # crudo/ + traducido/ + estadísticas (CSV)
cs2a export ~/demos -o exports -f both   # varias demos (en paralelo) + leaderboard agregado, CSV y Parquet
cs2a pack ~/demos -o lib.cs2a            # empaquetar en .cs2a (ver arriba)
cs2a assets                              # radares + mallas de colisión (para línea de visión)
```

## Cómo se calculan las métricas

Validado con 6 demos reales de distintos orígenes: matchmaking de Valve, FACEIT, ESEA y dos demos pro de HLTV.
Entre ellas hay partidas con halftime, overtime, ronda de cuchillo, coach y formatos de eventos viejos y nuevos de demoparser2.

- **Contra el scoreboard interno del juego** (props `*_total` del último tick): kills, muertes, asistencias, HS y daño
  coinciden 1:1. El daño de utilidad tiene diferencias de ±3 puntos, en casos de fuego que coincide en el mismo tick con otro daño.
- **Contra csstats, FACEIT y HLTV** (ground truth de las [fixtures de awpy](https://github.com/pnxenopoulos/awpy-fixtures)):
  kills, muertes, HS, KAST y multikills coinciden. El ADR difiere entre 0.5 y 1%, porque cada sitio lo define distinto.
  csstats llega a una diferencia mayor, pero ahí el juego coincide con esta herramienta. Las asistencias incluyen las de
  flash, igual que el juego.

```bash
python scripts/fetch_fixtures.py         # baja las 5 demos de referencia (~1.8 GB) a tests/data/
pytest                                   # corre la integración sobre cada demo de tests/data/
```

- **Daño real**: es la vida que tenía la víctima antes del golpe menos la que le quedó después. El campo `dmg_health`
  del evento viene "bruto" (por ejemplo, un AWP informa 115 aunque a la víctima le queden 30 de vida) y no
  coincide con el juego. En los datos crudos se conservan los dos valores.
- **Variantes de arma**: `player_hurt` informa la M4A1-S como "m4a1" y la USP-S como "hkp2000". Para
  distinguirlas se usa el último disparo (`weapon_fire`) del atacante.
- **Equipos A/B**: el equipo A es el que arranca CT. Para cada ronda se cruza el roster de cada lado con los
  rosters acumulados, lo que cubre halftime, overtime, reconexiones y suplentes. Los coaches (figuran en un
  equipo pero nunca están vivos) se excluyen.
- **Rondas**: se aceptan los dos formatos de `round_end` de demoparser2: motivo y ganador numéricos (parches viejos)
  o como texto (`ct_killed`, `"T"`, desde ~14160). Se descarta todo lo previo al último `begin_new_match`, que
  incluye el warmup y la ronda de cuchillo. Si la demo no trae `round_officially_ended` (broadcasts), la ronda se
  cierra antes del siguiente freeze time.
- Las kills de salida (después de que termina la ronda) cuentan para esa ronda.
- **KAST**: rondas con kill, asistencia, supervivencia o muerte tradeada. **Tradeo**: vengar a un compañero dentro de los 5 s.
- **Lineups**: cada detonación se empareja con su lanzamiento (el `weapon_fire` de la granada, que trae la posición del jugador).
  Para flash y HE se respeta la mecha de ~1.7 s. Después se agrupan por equipo, tipo, lado, zona de lanzamiento (~320 u)
  y punto de caída (~160 u).
- **Clutch**: el primer momento en que un lado queda con un solo jugador vivo frente a X rivales.
- **Economía**: se toma el valor de equipo al terminar el tiempo de compra (o el del freeze end, si es mayor).
  Eco < $5k · Semi-eco < $10k · Force < $20k · Full buy ≥ $20k. Las rondas 1 y 13 se marcan como pistola.
- **Rating 1.0**: es la fórmula oficial publicada por HLTV. **Rating 2.0 / Impacto**: es la aproximación por regresión de la
  comunidad, porque HLTV no publica esa fórmula. En la UI aparece marcado con `*`.
- **Fecha de la partida**: es la fecha de modificación del archivo, porque las demos de CS2 no traen la fecha en el header.

## Radares

```bash
cs2a radars     # o el botón "Descargar radares" en la app
```

El comando descarga las imágenes de radar y la tabla de coordenadas de [awpy-data](https://github.com/pnxenopoulos/awpy-data),
que las extrae de los archivos del juego. No se versionan en el repo porque son assets de Valve.
Para Nuke, Vertigo y Train hay un selector de nivel (superior/inferior).
Sin radar, los mapas se dibujan en coordenadas del juego sobre una silueta formada por las posiciones de los jugadores.

## Estructura

```
cs2analysis/
  parser.py      demo -> DemoData (tablas normalizadas) + caché .cs2a
  storage.py     formato .cs2a
  micro.py       aim / reacción / spray / movimiento (duels + shots)
  geometry.py    línea de visión contra la malla de colisión del mapa
  tactics.py     sitios, timings y lineups
  stats.py       player_rounds -> métricas (sirve igual para 1 o N demos)
  multi.py       Library: varias demos, leaderboard, tendencias, mapas
  translate.py   tablas "crudas traducidas"
  constants.py   armas, hitgroups, motivos de fin de ronda, columnas en español
  maps.py        metadatos de radar
  cli.py         cs2a
  ui/            vistas de Streamlit
app.py           entrada de la app
tests/           lógica sintética + integración con una demo real (CS2A_TEST_DEMO)
```

## Tests

```bash
pytest                                       # tests de lógica
CS2A_TEST_DEMO=/ruta/partida.dem pytest      # + integración contra el scoreboard del juego
```

## Limitaciones conocidas

- A algunas demos de broadcast les faltan eventos (`player_hurt` parciales, ningún `player_blind`). En esos casos
  el daño puede desviarse 1 o 2% del juego y no hay datos de flashes.
- "Enemigos flasheados" cuenta todas las cegueras a rivales y no coincide exactamente con el contador del juego,
  que aplica un criterio no documentado.
- La detección de sitio A/B de la bomba usa la zona en la que estaba el plantador (`BombsiteA`/`BombsiteB`).
