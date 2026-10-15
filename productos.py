"""
Productos activos (móviles, mono, dúo, trío) de cada RUC de data/rucs*.csv.

Por RUC: GET productintegration/cards (tarjetas con productos activos; 404 = sin productos) y, por cada tarjeta con
activos, GET productintegration/filter (la tabla de la pestaña Productos). De cada fila se guarda lo que muestra el
portal: Código de producto, Plan y Subtipo de producto (MOVISTAR / MONO / DUO / TRIO).

El servidor limita el ritmo (429 "Too Many Requests"), así que las llamadas salen con un tope global y se frenan solas
si aparece un 429. Avance en data/productos.csv: lo ya consultado se salta al volver a ejecutar.
Uso:  python productos.py [--tasa 3] [--hilos 6] [--limite N] [--visible]
"""
import argparse
import csv
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from playwright.sync_api import sync_playwright

import exportar
import extraer
from extraer import log

BASE = "https://apimngr-genesis-prod.azure-api.net/productintegration/v2/api/productintegration/"
SALIDA = os.path.join(extraer.sesion.DATA, "productos.csv")
CAMPOS = ["ruc", "estado", "subtipo_producto", "codigo_producto", "plan"]
# tarjeta -> parámetros de la tabla de esa tarjeta (los que usa el propio portal)
TABLA = {"MOVISTAR": {"serviceType": "MOVIL", "product": "Movil"},
         "MONO": {"serviceType": "FIJA", "productGrouping": "MONO"},
         "DUO": {"serviceType": "FIJA", "productGrouping": "DUO"},
         "TRIO": {"serviceType": "FIJA", "productGrouping": "TRIO"}}
TAM_PAGINA = 500
LOTE = 300
INTENTOS = 6


class SesionVencida(Exception):
    pass


class Limitador:
    """Tope global de llamadas por segundo; si el servidor responde 429 se vuelve más lento, y se recupera solo."""

    def __init__(self, tasa: float):
        self.base = 1 / tasa
        self.intervalo = self.base
        self.siguiente = 0.0
        self.lock = threading.Lock()
        self.buenas = 0

    def esperar(self) -> None:
        with self.lock:
            ahora = time.time()
            inicio = max(ahora, self.siguiente)
            self.siguiente = inicio + self.intervalo
        if inicio > ahora:
            time.sleep(inicio - ahora)

    def castigo(self) -> None:
        with self.lock:
            self.intervalo = min(self.intervalo * 1.25, 3.0)
            self.siguiente = max(self.siguiente, time.time() + 5)
            self.buenas = 0
        log(f"⚠️ 429 del servidor: se baja el ritmo a {1 / self.intervalo:.2f} llamadas/s")

    def exito(self) -> None:
        with self.lock:
            self.buenas += 1
            if self.buenas >= 300 and self.intervalo > self.base:
                self.intervalo = max(self.base, self.intervalo * 0.9)
                self.buenas = 0


class Consulta:
    def __init__(self, api: extraer.SesionAPI, lim: Limitador):
        self.api, self.lim = api, lim
        self.parar = threading.Event()

    def get(self, endpoint: str, params: dict):
        """Una llamada con tope de ritmo y reintentos. Devuelve la respuesta (200 o 404) o lanza SesionVencida."""
        ultimo = None
        for intento in range(1, INTENTOS + 1):
            if self.parar.is_set():
                raise KeyboardInterrupt
            self.lim.esperar()
            try:
                r = requests.get(BASE + endpoint, params=params, headers=self.api.cab["headers"], timeout=90)
            except requests.RequestException as e:
                ultimo = e
                time.sleep(3 * intento)
                continue
            if r.status_code in (200, 404) and not (r.status_code == 404 and "SVC1006" not in r.text):
                self.lim.exito()
                return r
            if r.status_code == 401 or (r.status_code == 400 and "E043" in r.text):
                raise SesionVencida()
            if r.status_code == 429 or '"code":"429"' in r.text.replace(" ", ""):
                self.lim.castigo()
                time.sleep(5 * intento)
                continue
            ultimo = f"{r.status_code} {r.text[:120]}"
            time.sleep(3 * intento)
        raise RuntimeError(f"{endpoint} {params.get('documentNumber')}: {ultimo}")

    def ruc(self, ruc: str) -> list:
        """Filas [ruc, estado, subtipo, codigo, plan] de un RUC."""
        doc = {"documentType": "RUC", "documentNumber": ruc}
        r = self.get("cards", doc)
        if r.status_code == 404:
            return [[ruc, "sin_productos", "", "", ""]]
        filas = []
        for tarjeta in r.json():
            if not tarjeta.get("active") or tarjeta.get("product") not in TABLA:
                continue
            pagina = 1
            while True:
                t = self.get("filter", {"page": pagina, "size": TAM_PAGINA, **TABLA[tarjeta["product"]], **doc})
                if t.status_code == 404:
                    break
                datos = t.json()
                for x in datos.get("products", []):
                    if x.get("status") == "ACTIVO":
                        filas.append([ruc, "ok", x.get("product", ""), x.get("codeProduct", ""),
                                      x.get("nameFatherPlan", "")])
                if datos.get("pagination", {}).get("last", True) or not datos.get("products"):
                    break
                pagina += 1
        return filas or [[ruc, "sin_activos", "", "", ""]]


def pendientes() -> list:
    df = exportar.leer()
    df = df[df["tipo_doc"] == "RUC"].drop_duplicates(subset="ruc")
    hechos = set()
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding="utf-8-sig", newline="") as f:
            hechos = {fila["ruc"] for fila in csv.DictReader(f)}
    todos = list(df["ruc"])
    log(f"RUC en total: {len(todos)}; ya consultados: {len(hechos)}")
    return [r for r in todos if r not in hechos]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasa", type=float, default=3.0, help="llamadas por segundo (tope inicial)")
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--limite", type=int, default=0, help="solo los primeros N pendientes (pruebas)")
    ap.add_argument("--visible", action="store_true")
    a = ap.parse_args()

    por_hacer = pendientes()
    if a.limite:
        por_hacer = por_hacer[:a.limite]
    if not por_hacer:
        log("Nada pendiente")
        return 0
    nuevo = not os.path.exists(SALIDA)
    t0, hechos, errores = time.time(), 0, []

    with sync_playwright() as p:
        api = extraer.SesionAPI(p, a.visible)
        c = Consulta(api, Limitador(a.tasa))
        signal.signal(signal.SIGINT, lambda *_: (log("Ctrl+C: se termina el lote en curso"), c.parar.set()))
        with open(SALIDA, "a", newline="", encoding="utf-8") as f, ThreadPoolExecutor(a.hilos) as pool:
            w = csv.writer(f)
            if nuevo:
                w.writerow(CAMPOS)
            try:
                for i in range(0, len(por_hacer), LOTE):
                    lote = por_hacer[i:i + LOTE]
                    while lote and not c.parar.is_set():
                        vencidas = []

                        def uno(ruc):
                            try:
                                return ruc, c.ruc(ruc), None
                            except SesionVencida:
                                return ruc, None, "vencida"
                            except KeyboardInterrupt:
                                return ruc, None, "stop"
                            except Exception as e:
                                return ruc, None, str(e)[:150]

                        for ruc, filas, err in pool.map(uno, lote):
                            if filas is not None:
                                w.writerows(filas)
                                hechos += 1
                            elif err == "vencida":
                                vencidas.append(ruc)
                            elif err != "stop":
                                errores.append((ruc, err))
                        f.flush()
                        if not vencidas:
                            break
                        log(f"⚠️ sesión vencida; se renueva y se repiten {len(vencidas)} RUC")
                        api.renovar(forzar=True)
                        lote = vencidas
                    ritmo = hechos / max(time.time() - t0, 1)
                    falta = (len(por_hacer) - hechos) / max(ritmo, 0.001) / 3600
                    log(f"{hechos}/{len(por_hacer)} RUC; {ritmo:.2f} RUC/s; faltan ~{falta:.1f} h; errores: {len(errores)}")
                    if c.parar.is_set():
                        break
            finally:
                api.cerrar()
    if errores:
        with open(os.path.join(extraer.sesion.DATA, "productos_errores.txt"), "a", encoding="utf-8") as f:
            f.writelines(f"{r}\t{e}\n" for r, e in errores)
        log(f"{len(errores)} RUC con error (se reintentan al volver a ejecutar); detalle en data/productos_errores.txt")
    log("Terminado" if not c.parar.is_set() else "Detenido (se puede continuar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
