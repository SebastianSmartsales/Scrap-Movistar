@echo off
REM Scrap Movistar: descarga RUC y productos y arma el Excel. Se puede cortar con Ctrl+C y volver a ejecutar: continua donde quedo.
cd /d "%~dp0"
set PY=..\Scrap\venv\Scripts\python.exe
if not exist "%PY%" set PY=python
echo === 1/3 Lista de RUC (unos 40 min; 2 pasadas) ===
if not exist data\pasada1.csv (
  "%PY%" -X utf8 extraer.py --reiniciar && move /y data\rucs.csv data\pasada1.csv && del data\progreso.json
  "%PY%" -X utf8 extraer.py --reiniciar
)
echo === 2/3 Productos por RUC (muchas horas; se puede cortar y continuar) ===
"%PY%" -X utf8 productos.py
echo === 3/3 Excel ===
"%PY%" -X utf8 exportar.py
pause
