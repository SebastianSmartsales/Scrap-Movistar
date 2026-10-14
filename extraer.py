"""
Descarga todas las empresas de "Todas las Empresas" del portal de agente de Movistar Empresas.

El portal lista con GET .../organization?offset=<N° de página, desde 0>&limit=<tamaño>. El navegador solo se usa para
iniciar sesión y obtener los encabezados (token Bearer incluido); las páginas se piden con requests.

Avance: data/rucs.csv (se agrega cada página) y data/progreso.json (última página completa). Si se corta, volver a
ejecutar continúa donde quedó. Uso:  python extraer.py [--limit 1000] [--reiniciar] [--visible]
"""
import argparse
import csv
import json
import math
import os
import sys
import time

import requests
from playwright.sync_api import sync_playwright

import sesion

CSV = os.path.join(sesion.DATA, "rucs.csv")
PROGRESO = os.path.join(sesion.DATA, "progreso.json")
CAMPOS = ["ruc", "razon_social", "tipo_cliente", "subtipo_cliente", "tipo_doc", "estado"]
FIELDS = "name,organizationIdentification,partyCharacteristic,status,id"
PAUSA = 1.0  # s entre páginas
INTENTOS = 5


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def obtener_cabeceras(pg) -> dict:
    """Abre la lista de empresas y toma los encabezados que usa el propio portal en su llamada a la API."""
    with pg.expect_response(lambda r: "partymanagement-oc/v1/organization?offset" in r.url, timeout=60_000) as info:
        pg.goto(f"{sesion.base()}#/empresa", wait_until="domcontentloaded")
        pg.get_by_text("Todas las Empresas", exact=True).first.click(timeout=30_000)
    req = info.value.request
    cab = {k: v for k, v in req.headers.items() if not k.startswith("sec-ch") and k != "referer"}
    return {"url": req.url.split("?")[0], "headers": cab}


def fila(o: dict) -> list:
    ident = o.get("organizationIdentification") or {}
    tc = {}
    for c in o.get("partyCharacteristic") or []:
        if c.get("name") == "typeClient" and isinstance(c.get("value"), dict):
            tc = c["value"]
            break
    return [ident.get("identificationId", ""), (o.get("name") or "").strip(), (tc.get("name") or "").strip(),
            ((tc.get("subType") or {}).get("name") or "").strip(), ident.get("type", ""), o.get("status", "")]


class SesionAPI:
    def __init__(self, p, visible: bool):
        self.p, self.visible = p, visible
        self.browser = self.ctx = self.pg = None
        self.cab = None
        self.http = requests.Session()
        self.renovar()

    def renovar(self, forzar: bool = False) -> None:
        """Abre el navegador (o reutiliza el abierto), asegura el login y toma encabezados nuevos.
        forzar=True descarta la sesión guardada: el portal puede seguir mostrando la pantalla de siempre aunque la
        sesión del servidor ya venció (error E043)."""
        if forzar:
            self.cerrar()
            if os.path.exists(sesion.SESION):
                os.remove(sesion.SESION)
        elif self.browser:
            try:
                sesion.iniciar_sesion(self.pg)
            except Exception:
                self.cerrar()
        if not self.browser:
            self.browser, self.ctx, self.pg = sesion.abrir(self.p, visible=self.visible)
        self.cab = obtener_cabeceras(self.pg)
        log("encabezados de la API renovados")

    def get(self, params: dict):
        r = self.http.get(self.cab["url"], params=params, headers=self.cab["headers"], timeout=120)
        if r.status_code == 400 and "E043" in r.text:  # sesión del servidor vencida
            log("⚠️ sesión vencida en el servidor (E043); se inicia sesión de nuevo")
            self.renovar(forzar=True)
            r = self.http.get(self.cab["url"], params=params, headers=self.cab["headers"], timeout=120)
        return r

    def cerrar(self) -> None:
        try:
            self.browser.close()
        except Exception:
            pass
        self.browser = None


def total_empresas(api: SesionAPI) -> int:
    r = api.get({"additionalData.key": "COUNT", "additionalData.value": "TOTAL"})
    r.raise_for_status()
    return int(r.json()["organization"][0]["name"])


class PaginaRota(RuntimeError):
    """El portal responde 400 de forma sostenida para esa página (algún registro la rompe)."""


def pedir_pagina(api: SesionAPI, pagina: int, limit: int) -> list:
    ultimo = None
    for intento in range(1, INTENTOS + 1):
        try:
            r = api.get({"offset": pagina, "limit": limit, "fields": FIELDS})
            if r.status_code in (401, 403):
                log(f"⚠️ API respondió {r.status_code}; se renuevan sesión y encabezados")
                api.renovar()
                continue
            if r.status_code == 400 and intento >= 2:
                raise PaginaRota(f"400 en la página {pagina} (limit={limit})")
            r.raise_for_status()
            return r.json().get("organization", [])
        except PaginaRota:
            raise
        except (requests.RequestException, ValueError) as e:
            ultimo = e
            espera = 10 * intento
            log(f"⚠️ página {pagina}: {type(e).__name__}; reintento {intento}/{INTENTOS} en {espera} s")
            time.sleep(espera)
    raise RuntimeError(f"la página {pagina} falló tras {INTENTOS} intentos: {ultimo}")


SALTADAS = os.path.join(sesion.DATA, "saltadas.json")


def pedir_rango(api: SesionAPI, inicio: int, n: int, total: int) -> list:
    """
    Filas de las posiciones [inicio, inicio+n). Si el portal devuelve vacía una página que debería traer datos (pasa con
    algún registro que rompe la consulta en el servidor), la divide en 10 pedazos más chicos hasta aislarlo; de la
    posición que no se puede leer queda constancia en data/saltadas.json.
    """
    try:
        filas = pedir_pagina(api, inicio // n, n)
    except PaginaRota:
        filas = []
    if filas or inicio + n > total - 50:  # vacía al final de la lista: fin legítimo (el total del portal oscila)
        return filas
    if n == 1:
        for _ in range(3):  # el vacío puede ser pasajero (la posición 81432 falló una vez y luego se leyó bien)
            time.sleep(5)
            filas = pedir_pagina(api, inicio, 1)
            if filas:
                return filas
        log(f"⛔ posición {inicio} ilegible: se salta")
        previas = json.load(open(SALTADAS)) if os.path.exists(SALTADAS) else []
        json.dump(previas + [inicio], open(SALTADAS, "w"))
        return []
    sub = max(n // 10, 1)
    log(f"⚠️ rango {inicio}-{inicio + n - 1} vacío; se pide de a {sub}")
    out = []
    for k in range(inicio, inicio + n, sub):
        out += pedir_rango(api, k, sub, total)
        time.sleep(0.3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--reiniciar", action="store_true")
    ap.add_argument("--visible", action="store_true")
    a = ap.parse_args()

    os.makedirs(sesion.DATA, exist_ok=True)
    siguiente = 0
    if not a.reiniciar and os.path.exists(PROGRESO) and os.path.exists(CSV):
        prog = json.load(open(PROGRESO))
        if prog.get("limit") == a.limit:
            siguiente = prog["ultima_pagina"] + 1
        else:
            log(f"El avance guardado usó limit={prog.get('limit')}; usa --reiniciar o el mismo --limit")
            return 1
    if siguiente == 0:
        with open(CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(CAMPOS)

    with sync_playwright() as p:
        api = SesionAPI(p, a.visible)
        try:
            total = total_empresas(api)
            paginas = math.ceil(total / a.limit)
            log(f"Total según el portal: {total}; {paginas} páginas de {a.limit}; se empieza en la {siguiente}")
            acumuladas = 0
            for pg_n in range(siguiente, paginas + 1):  # +1: por si el total creció mientras se descargaba
                filas = pedir_rango(api, pg_n * a.limit, a.limit, total)
                if not filas:
                    log(f"página {pg_n} vacía: fin")
                    break
                with open(CSV, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(fila(o) for o in filas)
                json.dump({"limit": a.limit, "ultima_pagina": pg_n, "total_portal": total}, open(PROGRESO, "w"))
                acumuladas += len(filas)
                log(f"página {pg_n + 1}/{paginas}: {len(filas)} filas (esta corrida: {acumuladas})")
                if (pg_n + 1) * a.limit >= total + a.limit:  # ya se pasó la última página posible
                    break
                time.sleep(PAUSA)
        finally:
            api.cerrar()
    log("Terminado. Siguiente paso: python exportar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
