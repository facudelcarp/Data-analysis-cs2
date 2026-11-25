# PyInstaller: `pyinstaller packaging/cs2a.spec` (desde la raíz del repo) -> dist/CS2DataAnalysis/
#
# Carpeta y no un único .exe: el modo onefile descomprime todo en una carpeta temporal en cada arranque
# (varios segundos). Los radares y mallas no van adentro: se descargan desde Herramientas a la carpeta del usuario.
import os

from PyInstaller.utils.hooks import collect_dynamic_libs

# Módulos de Qt que la app no usa: fuera, para no arrastrar cientos de MB (web, 3D, QML, multimedia…)
QT_EXCLUDES = [f"PySide6.{m}" for m in (
    "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtQuick",
    "QtQuick3D", "QtQuickWidgets", "QtQml", "Qt3DCore", "Qt3DRender", "Qt3DExtras", "QtMultimedia",
    "QtMultimediaWidgets", "QtCharts", "QtDataVisualization", "QtGraphs", "QtPdf", "QtPdfWidgets", "QtBluetooth",
    "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialPort", "QtSql", "QtTest", "QtDesigner",
    "QtHelp", "QtRemoteObjects", "QtScxml", "QtSpatialAudio", "QtTextToSpeech", "QtHttpServer")]

# pyarrow: la app usa Parquet y compute; Flight (RPC), S3 y Gandiva suman ~50 MB que no se usan.
# Substrait NO se puede sacar: el núcleo de pyarrow (lib, _parquet, _compute…) lo enlaza.
PYARROW_EXCLUDES = ["pyarrow.flight", "pyarrow._flight", "pyarrow._s3fs", "pyarrow.gandiva", "pyarrow.cuda",
                    "pyarrow._cuda", "pyarrow._azurefs", "pyarrow._gcsfs", "pyarrow._hdfs"]
DROP_BINARIES = ["arrow_flight", "gandiva", "arrow_s3", "Qt6Quick", "Qt6Qml", "Qt6Pdf",
                 "Qt6WebEngine", "Qt6Multimedia", "Qt63D", "qpdf"]

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=collect_dynamic_libs("demoparser2"),
    hiddenimports=["demoparser2"],
    # Plantillas de puestos (chicas, ~240 KB): van adentro; sin ellas no hay roles por posición
    datas=[(os.path.join(SPECPATH, "..", "assets", "positions", "templates.npz"), "assets/positions")],
    excludes=[*QT_EXCLUDES, *PYARROW_EXCLUDES, "tkinter", "matplotlib", "IPython", "streamlit", "plotly", "pytest",
              "PyQt5", "PyQt6", "PySide2", "PIL", "cryptography", "lxml", "yaml", "jinja2", "sqlalchemy", "openpyxl",
              "scipy", "numba", "botocore", "boto3", "fsspec"],
    noarchive=False,
)
# Bibliotecas nativas que igual entran por dependencias de plugins: se filtran por nombre
a.binaries = [b for b in a.binaries if not any(x in b[0] for x in DROP_BINARIES)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CS2DataAnalysis", console=False,
          upx=False)  # UPX dispara falsos positivos de antivirus
coll = COLLECT(exe, a.binaries, a.datas, name="CS2DataAnalysis", upx=False)
