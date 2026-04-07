# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for KDP Scout App.

Build with:
    pip install pyinstaller
    pyinstaller kdp_scout_gui.spec

This produces a single .exe in dist/
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Use SPECPATH (PyInstaller built-in) to resolve paths relative to spec file
# This ensures the icon is always found regardless of where the build is run from
qss_path = os.path.join(SPECPATH, 'kdp_scout', 'gui', 'resources', 'style.qss')
ico_path = os.path.join(SPECPATH, 'kdp_scout', 'gui', 'resources', 'kdpsy.ico')
svg_path = os.path.join(SPECPATH, 'kdp_scout', 'gui', 'resources', 'kdpsy.svg')

a = Analysis(
    ['kdp_scout_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        (qss_path, os.path.join('kdp_scout', 'gui', 'resources')),
        (ico_path, os.path.join('kdp_scout', 'gui', 'resources')),
        (svg_path, os.path.join('kdp_scout', 'gui', 'resources')),
    ],
    hiddenimports=[
    "kdp_scout.collectors.goodreads",
    "kdp_scout.gui.pages.goodreads_explorer_page",
    "kdp_scout.gui.workers.goodreads_worker",
        'kdp_scout.gui',
        'kdp_scout.gui.pages',
        'kdp_scout.gui.pages.keywords_page',
        'kdp_scout.gui.pages.trending_page',
        'kdp_scout.gui.pages.competitors_page',
        'kdp_scout.gui.pages.ads_page',
        'kdp_scout.gui.pages.seeds_page',
        'kdp_scout.gui.pages.asin_lookup_page',
        'kdp_scout.gui.pages.automation_page',
        'kdp_scout.gui.pages.settings_page',
        'kdp_scout.gui.widgets',
        'kdp_scout.gui.workers',
        'kdp_scout.collectors',
        'kdp_scout.collectors.autocomplete',
        'kdp_scout.collectors.product_scraper',
        'kdp_scout.collectors.trending',
        'kdp_scout.collectors.dataforseo',
        'kdp_scout.collectors.bsr_model',
        'matplotlib.backends.backend_qtagg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='KDP Scout App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    icon=ico_path,
    console=False,  # No console window (--windowed)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
