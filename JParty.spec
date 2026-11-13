import sys, platform
from pathlib import Path

ROOT = Path(SPECPATH).resolve()  # PyInstaller sets SPECPATH; __file__ is undefined in specs
sys.path.append(str(ROOT / "src"))
from jparty import __version__ as version
from PyInstaller.utils.hooks import copy_metadata

uname = platform.uname()
arch = uname.machine
iconfile = "resources/icon.icns" if uname.system=="Darwin" else "resources/icon.ico"

a = Analysis(['src/jparty/__main__.py'],
             pathex=['src'],
             binaries=[],
             datas=[
                 ("src/jparty/assets/data/*", "jparty/assets/data"),
                 ("src/jparty/assets/buzzer", "jparty/assets/buzzer"),
             ]
             # Bundle jparty's package metadata so importlib.metadata.version("jparty")
             # works in the packaged app (`jparty self-check` verifies it).
             + copy_metadata("jparty"),
             hiddenimports=["qrcode"],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=None,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data,
             cipher=None)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='JParty',
          debug=False,
          bootloader_ignore_signals=False,
          target_arch=arch,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False , icon=iconfile)

if uname.system == "Darwin":
    app = BUNDLE(exe,
                 name='JParty.app',
                 version=version,
                 icon=iconfile,
                 bundle_identifier='us.stuartthomas.jparty')

print(f"Built for {uname.system} with architecture {arch}")
