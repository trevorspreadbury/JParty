import sys, platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT / "src"))
from jparty import __version__ as version

uname = platform.uname()
arch = uname.machine
iconfile = "resources/icon.icns" if uname.system=="Darwin" else "resources/icon.ico"

a = Analysis(['src/jparty/__main__.py'],
             pathex=['src'],
             binaries=[],
             datas=[
                 ("src/jparty/assets/data/*", "jparty/assets/data"),
                 ("src/jparty/assets/buzzer", "jparty/assets/buzzer"),
             ],
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
