"""Login al portal de agente de Movistar Empresas (adaptado de Scrap/app/movistar/cliente.py)."""
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

DATA = "data"
SESION = os.path.join(DATA, "sesion.json")
BUSCADOR = 'input[placeholder="Buscar por Nro. de Doc / Razón Social"]'
ESPERA_LOGIN = 40_000
INTENTOS_LOGIN = 3
_BLOQUEADO = re.compile(r"usuario bloqueado", re.I)


class LoginError(Exception):
    pass


def url() -> str:
    return os.getenv("MOVISTAR_URL", "https://mimovistarempresas.movistar.com.pe/#/agente").strip()


def base() -> str:
    return url().split("#")[0]


def abrir(p, navegador="msedge", visible=False):
    """Abre el navegador, reutiliza la sesión guardada y asegura que haya login. Devuelve (browser, contexto, pagina)."""
    canal = None if navegador == "chromium" else navegador
    browser = p.chromium.launch(headless=not visible, channel=canal)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900},
                              storage_state=SESION if os.path.exists(SESION) else None)
    pg = ctx.new_page()
    pg.set_default_timeout(30_000)
    try:
        iniciar_sesion(pg)
    except Exception:
        browser.close()
        raise
    return browser, ctx, pg


def _sesion_activa(pg) -> bool:
    try:
        pg.goto(f"{base()}#/empresa", wait_until="domcontentloaded", timeout=60_000)
        pg.locator(BUSCADOR).or_(pg.locator("input[formcontrolname=documentNumber]")).first.wait_for(timeout=20_000)
        return "#/agente" not in pg.url and pg.locator(BUSCADOR).first.is_visible()
    except Exception:
        return False


def iniciar_sesion(pg) -> None:
    tipo = os.getenv("MOVISTAR_TIPO_DOC", "Otros")
    doc, clave = os.getenv("MOVISTAR_DOCUMENTO"), os.getenv("MOVISTAR_PASSWORD")
    if not (doc and clave):
        raise LoginError("Faltan MOVISTAR_DOCUMENTO / MOVISTAR_PASSWORD en .env")
    ultimo = None
    for intento in range(1, INTENTOS_LOGIN + 1):
        try:
            if _sesion_activa(pg):
                return
            pg.goto(url(), wait_until="networkidle", timeout=60_000)
            pg.locator("mat-select[formcontrolname=documentTypeCode]").click(timeout=15_000)
            pg.locator("mat-option", has_text=tipo).first.click(timeout=10_000)
            pg.locator("input[formcontrolname=documentNumber]").fill(doc, timeout=10_000)
            pg.locator("input[formcontrolname=password]").fill(clave, timeout=10_000)
            pg.locator("button[type=submit]").click(timeout=10_000)
            limite = time.time() + ESPERA_LOGIN / 1000
            while time.time() < limite and "#/agente" in pg.url:
                if _BLOQUEADO.search(pg.locator("body").inner_text()):
                    raise LoginError("usuario bloqueado por el portal; espera unos minutos")
                pg.wait_for_timeout(500)
            pg.locator(BUSCADOR).wait_for(timeout=ESPERA_LOGIN)
            os.makedirs(DATA, exist_ok=True)
            pg.context.storage_state(path=SESION)
            return
        except LoginError:
            raise
        except Exception as e:
            ultimo = e
            os.makedirs(DATA, exist_ok=True)
            try:
                pg.screenshot(path=os.path.join(DATA, "login_error.png"))
            except Exception:
                pass
            pg.wait_for_timeout(10_000 * intento)
    raise LoginError(f"no se pudo iniciar sesión tras {INTENTOS_LOGIN} intentos ({type(ultimo).__name__})")
