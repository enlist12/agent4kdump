# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

repo_root = Path.cwd()
hiddenimports = []
hiddenimports += collect_submodules('src')
hiddenimports += collect_submodules('agents')
hiddenimports += collect_submodules('client')

datas = [
    (str(repo_root / 'kdump_analyze'), 'kdump_analyze'),
]
env_file = repo_root / '.env'
if env_file.exists():
    datas.append((str(env_file), '.'))

a = Analysis(
    [str(repo_root / 'client' / 'backend' / 'entry.py')],
    pathex=[str(repo_root)],
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
