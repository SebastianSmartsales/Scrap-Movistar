"""Reconocimiento: inicia sesión, abre la lista de empresas, pone 100 por página, pasa 2 páginas y guarda las
peticiones XHR/fetch (url, método, encabezados sin secretos, cuerpo y respuesta) en data/red.json."""
import json
import os
import sys

from playwright.sync_api import sync_playwright

import sesion

TOPE_CUERPO = 4000


def main(visible: bool):
    capturas = []

    def al_responder(r):
        if r.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            cuerpo = r.text()[:TOPE_CUERPO]
        except Exception:
            cuerpo = ""
        h = {k: ("<oculto>" if k.lower() in ("authorization", "cookie") else v) for k, v in r.request.headers.items()}
        capturas.append({"url": r.url, "metodo": r.request.method, "status": r.status, "encabezados": h,
                         "post": (r.request.post_data or "")[:TOPE_CUERPO], "respuesta": cuerpo})

    with sync_playwright() as p:
        browser, ctx, pg = sesion.abrir(p, visible=visible)
        try:
            ctx.on("response", al_responder)
            pg.goto(f"{sesion.base()}#/empresa", wait_until="networkidle")
            os.makedirs(sesion.DATA, exist_ok=True)
            pg.screenshot(path=os.path.join(sesion.DATA, "lista.png"), full_page=True)
            with open(os.path.join(sesion.DATA, "lista.txt"), "w", encoding="utf-8") as f:
                f.write(pg.locator("body").inner_text())
            with open(os.path.join(sesion.DATA, "lista.html"), "w", encoding="utf-8") as f:
                f.write(pg.content())
            print("URL:", pg.url)
        finally:
            with open(os.path.join(sesion.DATA, "red.json"), "w", encoding="utf-8") as f:
                json.dump(capturas, f, ensure_ascii=False, indent=1)
            print(f"{len(capturas)} peticiones guardadas")
            browser.close()


if __name__ == "__main__":
    main(visible="--visible" in sys.argv)
