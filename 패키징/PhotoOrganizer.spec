# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct

project = Path(SPECPATH).parent
sys.path.insert(0, str(project))
from photo_version import VERSION, PRODUCT_NAME

version_tuple = tuple(map(int, VERSION.split('.'))) + (0,)
version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3f, flags=0,
                     OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('041204B0', [
        StringStruct('FileDescription', PRODUCT_NAME), StringStruct('ProductName', PRODUCT_NAME),
        StringStruct('FileVersion', VERSION), StringStruct('ProductVersion', VERSION),
        StringStruct('InternalName', 'PhotoOrganizer'), StringStruct('OriginalFilename', 'PhotoOrganizer.exe'),
    ])]), VarFileInfo([VarStruct('Translation', [0x0412, 1200])])],
)
datas = [(str(project / '아이콘' / (name + '.ico')), '아이콘') for name in ('photo_date', 'file_sort', 'raw_jpg')]
datas += [(str(project / name), name) for name in ('글꼴', '라이선스', '사용법')]
datas += copy_metadata('pillow')

a = Analysis([str(project / 'photo_app.py')], pathex=[str(project)], binaries=[], datas=datas,
             hiddenimports=['photo_pair_cleanup_gui', 'photo_organizer_gui'], hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=['pytest', 'matplotlib', 'numpy', 'pandas', 'IPython'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PhotoOrganizer', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, icon=str(project / '아이콘' / 'file_sort.ico'),
          version=version, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PhotoOrganizer')
