#!/usr/bin/env python3
"""Launcher for C64 BASIC V2 Interpreter."""
import sys
import os

# Add repo root to path so the c64basic package (sub-folder) is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from c64basic.main import main

if __name__ == '__main__':
    main()
