# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules

repo_root = Path.cwd()
src_root = repo_root / 'src'
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))
hiddenimports = []
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('agents')
hiddenimports += collect_submodules('client')
hiddenimports.append('runtime_config')

datas = [
    (str(repo_root / 'kdump_analyze'), 'kdump_analyze'),
]
env_file = repo_root / '.env'
if env_file.exists():
    datas.append((str(env_file), '.'))

a = Analysis(
    [str(repo_root / 'src' / 'client' / 'backend' / 'entry.py')],
    pathex=[str(repo_root), str(repo_root / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='agent4kdump-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
