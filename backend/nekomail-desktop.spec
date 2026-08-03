# PyInstaller spec for the standalone NekoMail desktop app (Windows, --onedir).
#
# backend/app/** deliberately does NOT get analyzed/frozen into the PYZ
# archive -- it's shipped as plain data files instead (see datas below) and
# imported at runtime via launcher.py's sys.path trick. Two reasons:
#   1. app/alembic/env.py and a few modules under app/ rely on real
#      Path(__file__) filesystem semantics (e.g. env.py locating itself to
#      compute a sys.path insert) that break if that code is compiled into
#      PyInstaller's frozen archive instead of sitting on disk as .py files.
#   2. It avoids any ambiguity between PyInstaller's frozen importer and the
#      plain on-disk copy launcher.py adds to sys.path at startup.
#
# Because app/'s own files are invisible to PyInstaller's static analysis as
# a result, every third-party package app/'s code imports has to be listed
# explicitly below (hiddenimports) rather than relying on transitive
# discovery -- see NEXT_STEPS.md for the full reasoning.
from PyInstaller.utils.hooks import collect_all

block_cipher = None

BACKEND_DIR = SPECPATH
APP_DIR = BACKEND_DIR + "/app"

# Every third-party package app/'s code (and launcher.py) imports.
# collect_all() (submodules + data + native binaries) is used for all of
# them, not just the obviously-native ones -- a plain hiddenimports entry
# only guarantees the named module itself, not its submodules, and a first
# build attempt proved that matters even for pure-Python packages: passlib
# was listed as a bare "passlib" hiddenimport, which pulled in
# passlib/__init__.py but NOT passlib.context (imported directly by
# services/auth_service.py), crashing with "No module named
# 'passlib.context'" at first-run seeding. Given this app is a personal,
# single-user tool (not size-optimized for distribution), erring toward an
# oversized-but-working bundle is the right trade-off over guessing
# submodules package by package.
PACKAGES = [
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "aiosqlite",
    "alembic",
    "pydantic",
    "pydantic_core",
    "pydantic_settings",
    "passlib",
    "bcrypt",
    "itsdangerous",
    "multipart",
    "cryptography",
    "aiosmtplib",
    "aioimaplib",
    "msal",
    "email_validator",
    "dotenv",
    "websockets",
    "httptools",
]

hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.loops.auto",
    "sqlalchemy.dialects.sqlite",
]

datas = [
    (APP_DIR, "app"),
    (BACKEND_DIR + "/alembic.ini", "."),
]
binaries = []

for pkg in PACKAGES:
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["desktop_app.py"],
    pathex=[BACKEND_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NekoMail",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NekoMail",
)
