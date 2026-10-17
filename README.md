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
| 🎯 **Demo individual** | Marcador, scoreboard por equipo (K/D/A, ADR, HS%, KAST, entries, tradeos, multikills, clutches, utilidad, precisión, Rating 1.0/2.0), ronda a ronda con kill feed, economía (valor de equipo y win rate según el tipo de compra), detalle por jugador (armas, clutches, rivales, mapa de kills/muertes), matriz de duelos, duelos de apertura, tradeos, utilidad (con el mapa de granadas), **tácticas** (a qué sitio va cada equipo de T, timing de plante, lineups repetidos dibujados desde dónde se lanzan hasta dónde caen) y mapas de calor de posiciones con filtros por lado, jugador, rondas y segundos de ronda. |
| 📚 **Multi-demo** | Lista de partidas, leaderboard agregado (calculado sobre el total de rondas, no como promedio de promedios), comparación de hasta 4 jugadores, evolución por partida y resumen por mapa, ya sea general o desde la perspectiva de un jugador, más **tácticas por equipo** sumando las partidas de un mismo mapa: sitios y lineups que un rival repite entre partidas. |
| 📊 **Dashboard** | Vista resumida. Sin jugador foco muestra la biblioteca completa: partidas por mapa, rondas por lado, armas, cómo terminan las rondas y top jugadores. Con jugador foco muestra sus KPIs, el rating por partida, el winrate por mapa, el ADR por lado, las armas y los multikills. |
| 🈯 **Datos crudos traducidos** | Las tablas normalizadas con columnas en español y valores legibles: T/CT, nombres de armas, zonas del mapa, motivo de fin de ronda, Sí/No y tiempos de ronda en segundos. Se pueden filtrar y descargar. |
| 🧾 **Datos crudos** | (1) Las tablas tal cual quedan en la caché. (2) Cualquier evento del juego tal como lo entrega demoparser2, con props extra a elección. (3) Un explorador de ticks: cualquier prop por jugador, por ronda y cada N ticks. (4) El header de la demo. |

## CLI

```bash
cs2a stats partida.dem                   # scoreboard en la terminal
cs2a export partida.dem -o exports       # crudo/ + traducido/ + estadísticas (CSV)
cs2a export ~/demos -o exports -f both   # varias demos (en paralelo) + leaderboard agregado, CSV y Parquet
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
  parser.py      demo -> DemoData (tablas normalizadas) + caché parquet
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
