@echo off
REM FreeCAD Tool Server launcher (Windows)
REM Must use FreeCAD's bundled Python — system Python won't work, because
REM FreeCAD's compiled bindings are built against its own python DLL.

REM Edit this if your FreeCAD is installed elsewhere.
set FREECAD_BIN=C:\Program Files\FreeCAD 1.1\bin
set FREECAD_PYTHON=%FREECAD_BIN%\python.exe

echo Starting FreeCAD Tool Server...
echo Using Python: %FREECAD_PYTHON%
echo Server: http://localhost:8000   Docs: http://localhost:8000/docs
echo.

"%FREECAD_PYTHON%" main.py
