# Scrap Movistar

Descarga de la plataforma de agente de Movistar Empresas (`mimovistarempresas.movistar.com.pe`) todos los RUC con
razon social, tipo y subtipo de cliente, y por cada RUC sus productos activos (moviles, mono, duo, trio).

## Uso
1. Copia `.env.example` a `.env` y completa `MOVISTAR_DOCUMENTO` y `MOVISTAR_PASSWORD`.
2. `pip install -r requirements.txt` y `playwright install chromium` (o usa el venv de la carpeta Scrap).
3. Doble clic a `ejecutar.bat` (o los pasos por separado de abajo).

| Paso | Comando | Que hace | Tiempo |
|---|---|---|---|
| 1 | `python extraer.py` | Lista de RUC via la API del portal (1000 por pagina) -> `data/rucs.csv` | ~20 min |
| 2 | `python productos.py` | Por RUC: codigo de producto, plan y subtipo de producto -> `data/productos.csv` | **decenas de horas** |
| 3 | `python exportar.py` | Une todo en `data/rucs_movistar.xlsx` (una fila por producto) | segundos |

- **Se puede cortar con Ctrl+C y volver a ejecutar:** `extraer.py` sigue en la ultima pagina y `productos.py` salta
  los RUC ya consultados. `python exportar.py` se puede correr en cualquier momento con lo avanzado.
- La PC no debe suspenderse mientras corre. El portal limita el ritmo (429): el programa se frena solo.
- Si la sesion del servidor vence (~45 min) vuelve a iniciar sesion sola.
- No uses la misma cuenta en otro lado mientras corre: el portal bloquea el usuario.
- `productos.py --tasa 2 --hilos 4` baja el ritmo; `--limite 100` prueba con 100 RUC.
- Los registros de prueba del portal (documento tipo OTROS) se dejan fuera del Excel.
