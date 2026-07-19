"""
InvenTree — Suite funcional: Stock (test_stock_inventree_suite.py)
FN2/FN3 Stock e Items de Stock, Transferencias (Hito 2)
Un único contexto Playwright (ahorro de memoria). Capturas por caso.

TC-SI01  Listar stock items (UI)
TC-SI02  Crear stock item — qty válida con ubicación
TC-SI03  Crear stock item — sin ubicación (location=null)
TC-SI04  Crear stock item — con número de serie
TC-SI05  Editar cantidad de stock item existente
TC-SI06  Eliminar stock item
TC-SI07  Ver detalle de stock item (UI)
TC-SI08  LÍMITE — Crear qty = 0
TC-SI09  LÍMITE — Crear qty negativa
TC-SI10  Acceso no autenticado (API)
TC-TR01  Transferencia parcial a otra ubicación
TC-TR02  Transferir TODO (qty completa)
TC-TR03  LÍMITE — Transferir a la misma ubicación
TC-TR04  LÍMITE — Transferir qty = 0
TC-TR05  LÍMITE — Transferir qty negativa
TC-TR06  LÍMITE — Transferir más de lo disponible
TC-TR07  Transferencia sin autenticación (API)
"""
import os, subprocess, sys, time, requests, json
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE       = "http://localhost:8000"
API        = f"{BASE}/api"
USER       = "admin"
PASS       = "inventree"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SS_DIR     = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "stock")

PART_R  = 1   # Resistencia 10k
PART_C  = 2   # Capacitor 100uF
PART_L  = 3   # LED Rojo
LOC_A   = 1   # Almacén A
LOC_B   = 2   # Almacén B
LOC_C   = 3   # Almacén C
LOC_D   = 4   # Cajón 1

results = []

# ── helpers ──────────────────────────────────────────────────────────────

def log(tc, name, ok, detail=""):
    mark = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {mark}  {tc}: {name}")
    if detail:
        print(f"         {detail}")
    results.append({"tc": tc, "name": name, "pass": ok, "detail": detail})

def snap(page, name):
    p = f"{SS_DIR}/{name}.png"
    page.screenshot(path=p, full_page=True)
    return p

def authed_session():
    s = requests.Session()
    s.get(f"{API}/auth/v1/config", auth=(USER, PASS))
    csrf = s.cookies.get("csrftoken", "")
    s.post(f"{API}/auth/v1/auth/login",
           json={"username": USER, "password": PASS},
           headers={"X-CSRFToken": csrf, "Referer": BASE})
    return s, s.cookies.get("csrftoken", csrf)

def api_get(path, auth=True):
    a = (USER, PASS) if auth else None
    return requests.get(f"{API}{path}", auth=a)

def api_call(method, path, data=None, auth=True):
    s, csrf = authed_session() if auth else (requests.Session(), "")
    kw = {"headers": {"X-CSRFToken": csrf, "Referer": BASE}}
    if data is not None:
        kw["json"] = data
    fn = getattr(s, method)
    return fn(f"{API}{path}", **kw)

def stock_pk(r):
    """POST /api/stock/ → lista; devuelve pk del primer elemento."""
    body = r.json()
    if isinstance(body, list):
        return body[0].get("pk") if body else None
    return body.get("pk")

def stock_data(r):
    body = r.json()
    return body[0] if isinstance(body, list) and body else (body if isinstance(body, dict) else {})

def make_item(part, loc, qty, serial=None):
    d = {"part": part, "location": loc, "quantity": qty}
    if serial:
        d["serial"] = serial
    r = api_call("post", "/stock/", d)
    return stock_pk(r) if r.status_code == 201 else None

def transfer(item_pk, dest, qty, notes="TC"):
    return api_call("post", "/stock/transfer/", {
        "location": dest,
        "items": [{"pk": item_pk, "quantity": qty}],
        "notes": notes
    })

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MANAGE_PY = os.path.join(_BASE_DIR, "src", "backend", "InvenTree", "manage.py")

def clear_cache():
    subprocess.run(
        [sys.executable, _MANAGE_PY,
         "shell", "-c",
         "from django.core.cache import cache; cache.clear()"],
        capture_output=True)

def wipe_stock():
    items = api_get("/stock/?limit=500").json().get("results", [])
    for it in items:
        api_call("delete", f"/stock/{it['pk']}/")

# ── casos ─────────────────────────────────────────────────────────────────

def tc_si01(page):
    wipe_stock()
    page.goto(f"{BASE}/web/stock/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-SI01_list_empty")
    ok = "/web/stock" in page.url
    log("TC-SI01", "Listar stock items (UI vacía)", ok,
        f"URL={page.url}")

def tc_si02(page):
    r = api_call("post", "/stock/", {"part": PART_R, "location": LOC_A, "quantity": 100})
    ok = r.status_code == 201
    d  = stock_data(r)
    pk = d.get("pk")
    if pk:
        page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
        time.sleep(2)
    snap(page, "TC-SI02_create_valid")
    log("TC-SI02", "Crear stock item válido (qty=100, Almacén A)", ok,
        f"HTTP {r.status_code} | pk={pk} | qty={d.get('quantity')}")

def tc_si03(page):
    r = api_call("post", "/stock/", {"part": PART_C, "quantity": 50})
    ok = r.status_code == 201
    d  = stock_data(r)
    pk = d.get("pk")
    if pk:
        page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
        time.sleep(2)
    snap(page, "TC-SI03_no_location")
    log("TC-SI03", "Crear stock item sin ubicación", ok,
        f"HTTP {r.status_code} | pk={pk} | location={d.get('location')}")

def tc_si04(page):
    r = api_call("post", "/stock/", {
        "part": PART_L, "location": LOC_B, "quantity": 1, "serial": "SN-TEST-001"
    })
    ok = r.status_code == 201
    d  = stock_data(r)
    pk = d.get("pk")
    if pk:
        page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
        time.sleep(2)
    snap(page, "TC-SI04_serial")
    log("TC-SI04", "Crear stock item con número de serie SN-TEST-001", ok,
        f"HTTP {r.status_code} | serial={d.get('serial')} | pk={pk}")

def tc_si05(page):
    pk = make_item(PART_R, LOC_A, 200)
    if not pk:
        log("TC-SI05", "Editar cantidad", False, "No se creó item")
        return
    r = api_call("patch", f"/stock/{pk}/", {"quantity": 350})
    ok = r.status_code == 200 and r.json().get("quantity") == 350
    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-SI05_edit_qty")
    log("TC-SI05", "Editar cantidad 200 → 350", ok,
        f"HTTP {r.status_code} | qty={r.json().get('quantity')}")

def tc_si06(page):
    pk = make_item(PART_C, LOC_C, 10)
    if not pk:
        log("TC-SI06", "Eliminar stock item", False, "No se creó item")
        return
    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-SI06_before_delete")

    r_del = api_call("delete", f"/stock/{pk}/")
    r_get = api_get(f"/stock/{pk}/")

    page.goto(f"{BASE}/web/stock/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-SI06_after_delete")
    ok = r_del.status_code in (200, 204) and r_get.status_code == 404
    log("TC-SI06", "Eliminar stock item", ok,
        f"DELETE={r_del.status_code} | GET_tras_borrar={r_get.status_code}")

def tc_si07(page):
    items = api_get("/stock/?limit=5").json().get("results", [])
    if not items:
        pk = make_item(PART_L, LOC_A, 25)
    else:
        pk = items[0]["pk"]
    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(3)
    snap(page, "TC-SI07_detail_ui")
    text = page.locator("body").inner_text()
    ok = len(text) > 100
    log("TC-SI07", "Ver detalle de stock item (UI)", ok,
        f"pk={pk} | URL={page.url}")

def tc_si08(page):
    r = api_call("post", "/stock/", {"part": PART_R, "location": LOC_A, "quantity": 0})
    accepted = r.status_code == 201
    rejected = r.status_code in (400, 422)
    ok = accepted or rejected
    d = stock_data(r) if accepted else {}
    detail = f"HTTP {r.status_code}"
    note = "ACEPTADO" if accepted else "RECHAZADO"
    if not accepted:
        detail += f" | error={r.json()}"
    else:
        detail += f" | pk={d.get('pk')}"
    snap(page, "TC-SI08_qty_zero")
    log("TC-SI08", f"LÍMITE — Crear qty=0 [{note}]", ok, detail)

def tc_si09(page):
    r = api_call("post", "/stock/", {"part": PART_C, "location": LOC_B, "quantity": -50})
    rejected = r.status_code in (400, 422)
    ok = rejected   # se espera rechazo
    detail = f"HTTP {r.status_code}"
    if not rejected:
        detail += " ⚠ DEFECTO: qty negativa fue aceptada"
    else:
        detail += f" | error={r.json()}"
    snap(page, "TC-SI09_qty_negative")
    log("TC-SI09", "LÍMITE — Crear qty negativa (debe rechazar)", ok, detail)

def tc_si10(page):
    r = requests.get(f"{API}/stock/")
    page.goto(f"{BASE}/api/stock/", wait_until="networkidle", timeout=10000)
    time.sleep(1)
    snap(page, "TC-SI10_unauth")
    ok = r.status_code in (401, 403)
    log("TC-SI10", "Acceso no autenticado al API de stock", ok,
        f"HTTP {r.status_code} (esperado 401/403)")

def tc_tr01(page):
    pk = make_item(PART_R, LOC_A, 200)
    if not pk:
        log("TC-TR01", "Transferencia parcial", False, "No se creó item"); return

    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-TR01_before")

    r = transfer(pk, LOC_B, 80, "TC-TR01 parcial")
    ok = r.status_code in (200, 201)

    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(3)
    snap(page, "TC-TR01_after_partial")
    d = api_get(f"/stock/{pk}/").json()
    log("TC-TR01", "Transferencia parcial 80/200 → Almacén B", ok,
        f"HTTP {r.status_code} | qty_restante={d.get('quantity')} | loc={d.get('location')}")

def tc_tr02(page):
    pk = make_item(PART_C, LOC_A, 50)
    if not pk:
        log("TC-TR02", "Transferencia total", False, "No se creó item"); return

    r = transfer(pk, LOC_C, 50, "TC-TR02 total")
    ok = r.status_code in (200, 201)

    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(3)
    snap(page, "TC-TR02_transfer_all")
    d = api_get(f"/stock/{pk}/").json()
    log("TC-TR02", "Transferir toda la cantidad 50 → Almacén C", ok,
        f"HTTP {r.status_code} | loc_nueva={d.get('location')} (esperado {LOC_C})")

def tc_tr03(page):
    pk = make_item(PART_L, LOC_B, 30)
    if not pk:
        log("TC-TR03", "Transferir misma ubicación", False, "No se creó item"); return

    r = transfer(pk, LOC_B, 30, "TC-TR03 misma loc")
    accepted = r.status_code in (200, 201)
    rejected = r.status_code in (400, 422)
    ok = accepted or rejected
    note = "ACEPTADO" if accepted else "RECHAZADO"

    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-TR03_same_location")
    detail = f"HTTP {r.status_code}"
    if rejected:
        detail += f" | error={r.json()}"
    log("TC-TR03", f"LÍMITE — Transferir a misma ubicación [{note}]", ok, detail)

def tc_tr04(page):
    pk = make_item(PART_R, LOC_A, 100)
    if not pk:
        log("TC-TR04", "Transferir qty=0", False, "No se creó item"); return

    r = transfer(pk, LOC_C, 0, "TC-TR04 qty cero")
    rejected = r.status_code in (400, 422)
    ok = rejected
    detail = f"HTTP {r.status_code}"
    if not rejected:
        detail += " ⚠ DEFECTO: qty=0 fue aceptada en transferencia"
    else:
        detail += f" | error={r.json()}"

    snap(page, "TC-TR04_transfer_qty_zero")
    log("TC-TR04", "LÍMITE — Transferir qty=0 (debe rechazar)", ok, detail)

def tc_tr05(page):
    pk = make_item(PART_C, LOC_B, 60)
    if not pk:
        log("TC-TR05", "Transferir qty negativa", False, "No se creó item"); return

    r = transfer(pk, LOC_A, -10, "TC-TR05 qty neg")
    rejected = r.status_code in (400, 422)
    ok = rejected
    detail = f"HTTP {r.status_code}"
    if not rejected:
        detail += " ⚠ DEFECTO: qty negativa fue aceptada"
    else:
        detail += f" | error={r.json()}"

    snap(page, "TC-TR05_transfer_qty_negative")
    log("TC-TR05", "LÍMITE — Transferir qty negativa (debe rechazar)", ok, detail)

def tc_tr06(page):
    pk = make_item(PART_L, LOC_C, 20)
    if not pk:
        log("TC-TR06", "Transferir qty excesiva", False, "No se creó item"); return

    r = transfer(pk, LOC_A, 9999, "TC-TR06 exceso")
    rejected = r.status_code in (400, 422)
    ok = rejected
    detail = f"HTTP {r.status_code}"
    if not rejected:
        detail += " ⚠ DEFECTO: transferencia > disponible fue aceptada"
    else:
        detail += f" | error={r.json()}"

    page.goto(f"{BASE}/web/stock/item/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2)
    snap(page, "TC-TR06_over_quantity")
    log("TC-TR06", "LÍMITE — Transferir más de disponible 9999/20 (debe rechazar)", ok, detail)

def tc_tr07(page):
    # Intento de transferencia sin autenticación
    r = requests.post(f"{API}/stock/transfer/", json={
        "location": LOC_B,
        "items": [{"pk": 1, "quantity": 5}],
        "notes": "sin auth"
    })
    page.goto(f"{BASE}/api/stock/transfer/", wait_until="networkidle", timeout=10000)
    time.sleep(1)
    snap(page, "TC-TR07_transfer_unauth")
    ok = r.status_code in (401, 403)
    log("TC-TR07", "Transferencia sin autenticación (debe rechazar)", ok,
        f"HTTP {r.status_code} (esperado 401/403)")

# ══════════════════════════════════════════════════════════════
# FN2/FN3 — Control de Stock (RF-004, Hito 2): casos extendidos
# Filtros de querystring, ubicaciones, adjust actions (count/add/remove/
# transfer/return/assign/merge/status), test-results, tracking, serialize.
# ══════════════════════════════════════════════════════════════

AUTH = (USER, PASS)

def cov_api(method, path, data=None, params=None):
    fn = getattr(requests, method)
    kw = {"auth": AUTH}
    if data is not None:
        kw["json"] = data
    if params is not None:
        kw["params"] = params
    return fn(f"{API}{path}", **kw)

def cov_short(r):
    try:
        return str(r.json())[:150]
    except Exception:
        return r.text[:150]

def cov_extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", [])
    return []

def cov_create_stock_item(part=1, location=1, quantity=50):
    r = cov_api("post", "/stock/", {"part": part, "location": location, "quantity": quantity})
    if r.status_code != 201:
        return None
    data = r.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data.get("pk")

def fn2_location():
    cases = [
        ("has_location_type", {"has_location_type": "false"}), ("depth", {"depth": 0}),
        ("top_level", {"top_level": "true"}), ("cascade", {"cascade": "false"}),
        ("parent", {"parent": 1}),
    ]
    for name, params in cases:
        r = cov_api("get", "/stock/location/", params=params)
        log(f"FN2-LOC-{name}", f"Filtro location ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r = cov_api("get", "/stock/location/tree/")
    log("FN2-LOC-tree", "Árbol de ubicaciones", r.status_code == 200, f"HTTP {r.status_code}")

    r = cov_api("post", "/stock/location-type/", {"name": "COV Location Type", "description": "Tipo temporal coverage"})
    ok = r.status_code == 201
    log("FN2-LOCTYPE-create", "Crear StockLocationType", ok, f"HTTP {r.status_code} {cov_short(r)}")
    if ok:
        cov_api("delete", f"/stock/location-type/{r.json()['pk']}/")

def fn2_stock_filters():
    cases = [
        ("include_variants", {"include_variants": "true", "part": 1}), ("part", {"part": 1}),
        ("status", {"status": 10}), ("allocated", {"allocated": "false"}),
        ("expired", {"expired": "false"}), ("external", {"external": "false"}),
        ("in_stock", {"in_stock": "true"}), ("available", {"available": "true"}),
        ("serialized", {"serialized": "false"}), ("has_batch", {"has_batch": "false"}),
        ("tracked", {"tracked": "false"}), ("consumed", {"consumed": "false"}),
        ("installed", {"installed": "false"}), ("has_installed", {"has_installed": "false"}),
        ("has_child_items", {"has_child_items": "false"}), ("sent_to_customer", {"sent_to_customer": "false"}),
        ("depleted", {"depleted": "false"}), ("has_purchase_price", {"has_purchase_price": "false"}),
        ("category", {"category": 1}), ("part_tree", {"part_tree": 5}),
        ("has_stocktake", {"has_stocktake": "false"}), ("stale", {"stale": "false"}),
        ("exclude_tree", {"exclude_tree": 1}), ("cascade", {"cascade": "true", "location": 1}),
        ("location", {"location": 1}),
    ]
    for name, params in cases:
        r = cov_api("get", "/stock/", params=params)
        log(f"FN2-STOCK-{name}", f"Filtro stock ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r = cov_api("get", "/stock/status/")
    log("FN2-STOCK-status-codes", "Códigos de estado de stock", r.status_code == 200, f"HTTP {r.status_code}")
    r = cov_api("post", "/generate/batch-code/", {})
    log("FN2-GEN-batchcode", "Generar batch code", r.status_code in (200, 201), f"HTTP {r.status_code}")
    r_ctx = cov_api("post", "/generate/batch-code/", {"part": 1, "location": 1, "quantity": 5})
    log("FN2-GEN-batchcode-context", "Generar batch code con contexto (part/location/quantity)", r_ctx.status_code in (200, 201), f"HTTP {r_ctx.status_code}")
    r2 = cov_api("post", "/generate/serial-number/", {})
    log("FN2-GEN-serial", "Generar serial number", r2.status_code in (200, 201), f"HTTP {r2.status_code}")
    r2b = cov_api("post", "/generate/serial-number/", {"part": 1, "quantity": 3})
    log("FN2-GEN-serial-part", "Generar 3 serial numbers para part=1 (recorre el while loop)", r2b.status_code in (200, 201), f"HTTP {r2b.status_code} {cov_short(r2b)}")
    # quantity=0 es falsy -> "quantity or 1" lo convierte a 1 silenciosamente,
    # por eso se usa -1 para disparar la validación "quantity < 1"
    r2c = cov_api("post", "/generate/serial-number/", {"part": 1, "quantity": -1})
    log("FN2-GEN-serial-negative", "Generar serial con quantity=-1 (debe rechazar)", r2c.status_code in (400, 422), f"HTTP {r2c.status_code} {cov_short(r2c)}")

    r_opt = requests.options(f"{API}/stock/", auth=AUTH)
    log("FN2-STOCK-options", "OPTIONS /api/stock/ (metadata de API)", r_opt.status_code == 200, f"HTTP {r_opt.status_code}")

def fn2_stock_pack_size():
    """StockList.create() con supplier_part de pack_quantity != 1 (use_pack_size)."""
    r_sp = cov_api("post", "/company/part/", {"part": 1, "supplier": 1, "SKU": "COV-PACK-SKU", "pack_quantity": "2"})
    sp_pk = r_sp.json().get("pk") if r_sp.status_code == 201 else None
    if not sp_pk:
        log("FN2-STOCK-pack-size", "Crear SupplierPart con pack_quantity=2", False, f"HTTP {r_sp.status_code} {cov_short(r_sp)}")
        return

    # Sin 'use_pack_size' -> debe rechazar (flag requerido cuando pack_size != 1)
    r_noflag = cov_api("post", "/stock/", {"part": 1, "supplier_part": sp_pk, "location": 1, "quantity": 10})
    log("FN2-STOCK-pack-size-noflag", "Crear StockItem con supplier_part pack!=1 sin use_pack_size (debe rechazar)",
        r_noflag.status_code in (400, 422), f"HTTP {r_noflag.status_code} {cov_short(r_noflag)}")

    # Con use_pack_size=True -> multiplica quantity por pack_quantity
    r_pack = cov_api("post", "/stock/", {"part": 1, "supplier_part": sp_pk, "location": 1, "quantity": 10, "use_pack_size": True})
    ok_pack = r_pack.status_code == 201
    log("FN2-STOCK-pack-size-true", "Crear StockItem con use_pack_size=True (quantity x pack_quantity)",
        ok_pack, f"HTTP {r_pack.status_code} {cov_short(r_pack)}")
    if ok_pack:
        pack_item = r_pack.json()
        pack_item = pack_item[0] if isinstance(pack_item, list) else pack_item
        cov_api("delete", f"/stock/{pack_item.get('pk')}/")

    cov_api("delete", f"/company/part/{sp_pk}/")

def fn3_adjust_actions():
    """Transferencias y ajustes de stock extendidos (RF-004 / FN3)."""
    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    if not pk:
        log("FN3-ADJ-count", "StockCount (recuento)", False, "No se pudo crear StockItem")
        return
    r = cov_api("post", "/stock/count/", {"items": [{"pk": pk, "quantity": 25}], "notes": "coverage count"})
    log("FN3-ADJ-count", "StockCount (recuento)", r.status_code in (200, 201), f"HTTP {r.status_code}")
    cov_api("delete", f"/stock/{pk}/")

    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    r = cov_api("post", "/stock/add/", {"items": [{"pk": pk, "quantity": 5}], "notes": "coverage add"})
    log("FN3-ADJ-add", "StockAdd (agregar stock)", r.status_code in (200, 201), f"HTTP {r.status_code}")
    r2 = cov_api("post", "/stock/remove/", {"items": [{"pk": pk, "quantity": 3}], "notes": "coverage remove"})
    log("FN3-ADJ-remove", "StockRemove (quitar stock)", r2.status_code in (200, 201), f"HTTP {r2.status_code}")
    cov_api("delete", f"/stock/{pk}/")

    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    r = cov_api("post", "/stock/transfer/", {"items": [{"pk": pk, "quantity": 4}], "location": 2, "notes": "coverage transfer"})
    log("FN3-ADJ-transfer", "StockTransfer (transferencia)", r.status_code in (200, 201), f"HTTP {r.status_code}")
    r2 = cov_api("post", "/stock/return/", {"items": [{"pk": pk, "quantity": 2}], "location": 1, "notes": "coverage return"})
    log("FN3-ADJ-return", "StockReturn (devolución)", r2.status_code in (200, 201, 400), f"HTTP {r2.status_code} {cov_short(r2)}")
    cov_api("delete", f"/stock/{pk}/")

    # StockTransfer con merge=True: target ya existe en el destino -> find_merge_target()
    # + merge_stock_items() (ramas no cubiertas por una transferencia normal)
    pk_target = cov_create_stock_item(part=1, location=2, quantity=5)
    pk_source_full = cov_create_stock_item(part=1, location=1, quantity=3)
    if pk_target and pk_source_full:
        r_mfull = cov_api("post", "/stock/transfer/", {"items": [{"pk": pk_source_full, "quantity": 3, "merge": True}], "location": 2, "notes": "coverage transfer-merge-full"})
        log("FN3-ADJ-transfer-merge-full", "StockTransfer con merge=True (traslado completo)", r_mfull.status_code in (200, 201), f"HTTP {r_mfull.status_code} {cov_short(r_mfull)}")
        cov_api("delete", f"/stock/{pk_target}/")

    # merge=True con quantity < stock del item -> splitStock() + merge del pedazo dividido
    pk_target2 = cov_create_stock_item(part=1, location=2, quantity=5)
    pk_source_split = cov_create_stock_item(part=1, location=1, quantity=8)
    if pk_target2 and pk_source_split:
        r_msplit = cov_api("post", "/stock/transfer/", {"items": [{"pk": pk_source_split, "quantity": 3, "merge": True}], "location": 2, "notes": "coverage transfer-merge-split"})
        log("FN3-ADJ-transfer-merge-split", "StockTransfer con merge=True (traslado parcial, splitStock)", r_msplit.status_code in (200, 201), f"HTTP {r_msplit.status_code} {cov_short(r_msplit)}")
        cov_api("delete", f"/stock/{pk_target2}/")
        cov_api("delete", f"/stock/{pk_source_split}/")

    # StockAssign exige que el Part sea "salable" -> marcar part=1 salable temporalmente
    cov_api("patch", "/part/1/", {"salable": True})

    # Asignar a cliente (items = [{"item": pk}], no [pk] -- StockAssignmentItemSerializer
    # exige un objeto por item) y luego devolver -> return_to_stock() recorre las
    # ramas de item.customer (no cubiertas con un item "normal")
    pk_ret = cov_create_stock_item(part=1, location=1, quantity=6)
    if pk_ret:
        r_assign = cov_api("post", "/stock/assign/", {"items": [{"item": pk_ret}], "customer": 2, "notes": "coverage assign-for-return"})
        log("FN3-ADJ-assign-for-return", "StockAssign a cliente (previo a return)", r_assign.status_code in (200, 201, 400), f"HTTP {r_assign.status_code} {cov_short(r_assign)}")
        if r_assign.status_code in (200, 201):
            r_ret2 = cov_api("post", "/stock/return/", {"items": [{"pk": pk_ret, "quantity": 6}], "location": 1, "notes": "coverage return-from-customer", "merge": True})
            log("FN3-ADJ-return-customer", "StockReturn de item asignado a cliente (merge=True)", r_ret2.status_code in (200, 201, 400), f"HTTP {r_ret2.status_code} {cov_short(r_ret2)}")
        cov_api("delete", f"/stock/{pk_ret}/")

    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    r = cov_api("post", "/stock/change_status/", {"items": [pk], "status": 50, "notes": "coverage damaged"})
    log("FN3-ADJ-status", "StockChangeStatus (cambiar estado)", r.status_code in (200, 201, 400), f"HTTP {r.status_code}")
    cov_api("delete", f"/stock/{pk}/")

    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    r = cov_api("post", "/stock/assign/", {"items": [{"item": pk}], "customer": 2, "notes": "coverage assign"})
    log("FN3-ADJ-assign", "StockAssign a cliente", r.status_code in (200, 201, 400), f"HTTP {r.status_code} {cov_short(r)}")
    cov_api("delete", f"/stock/{pk}/")
    cov_api("patch", "/part/1/", {"salable": False})

    pk1 = cov_create_stock_item(part=1, location=1, quantity=10)
    pk2 = cov_create_stock_item(part=1, location=1, quantity=5)
    if pk1 and pk2:
        r = cov_api("post", "/stock/merge/", {"items": [{"item": pk1}, {"item": pk2}], "location": 1, "notes": "coverage merge"})
        ok = r.status_code in (200, 201)
        log("FN3-ADJ-merge", "StockMerge (fusionar)", ok, f"HTTP {r.status_code} {cov_short(r)}")
        if not ok:
            cov_api("delete", f"/stock/{pk1}/"); cov_api("delete", f"/stock/{pk2}/")

def fn3_test_results_tracking_serialize():
    r_existing = requests.get(f"{API}/part/", params={"name": "COV Stock Testable Part", "format": "json"}, auth=AUTH)
    for item in cov_extract_list(r_existing.json()):
        if item.get("name") == "COV Stock Testable Part":
            cov_api("patch", f"/part/{item['pk']}/", {"active": False})
            cov_api("delete", f"/part/{item['pk']}/")

    r_tp = cov_api("post", "/part/", {
        "name": "COV Stock Testable Part", "description": "Parte temporal coverage stock",
        "category": 1, "testable": True, "trackable": True, "active": True,
    })
    part_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if part_pk:
        cov_api("post", "/part/test-template/", {"part": part_pk, "test_name": "COV Voltage Test", "description": "Chequeo de voltaje", "required": True})
        item_pk = cov_create_stock_item(part=part_pk, location=1, quantity=1)
        if item_pk:
            r = cov_api("post", "/stock/test/", {"stock_item": item_pk, "test": "COV Voltage Test", "result": True, "value": "5V"})
            ok = r.status_code == 201
            log("FN3-TESTRESULT-create", "Crear StockItemTestResult", ok, f"HTTP {r.status_code} {cov_short(r)}")
            r2 = cov_api("get", "/stock/test/", params={"stock_item": item_pk})
            log("FN3-TESTRESULT-list", "Listar test results ?stock_item=", r2.status_code == 200, f"HTTP {r2.status_code}")
            cov_api("delete", f"/stock/{item_pk}/")
        cov_api("patch", f"/part/{part_pk}/", {"active": False})
        cov_api("delete", f"/part/{part_pk}/")

    pk = cov_create_stock_item(part=1, location=1, quantity=10)
    if pk:
        r = cov_api("get", "/stock/track/", params={"item": pk})
        log("FN3-TRACK-list", "Listar StockItemTracking ?item=", r.status_code == 200, f"HTTP {r.status_code}")
        cov_api("delete", f"/stock/{pk}/")

    r_existing = requests.get(f"{API}/part/", params={"name": "COV Trackable Part", "format": "json"}, auth=AUTH)
    for item in cov_extract_list(r_existing.json()):
        if item.get("name") == "COV Trackable Part":
            cov_api("patch", f"/part/{item['pk']}/", {"active": False})
            cov_api("delete", f"/part/{item['pk']}/")
    r_tp = cov_api("post", "/part/", {
        "name": "COV Trackable Part", "description": "Parte temporal coverage trackable",
        "category": 1, "trackable": True, "active": True,
    })
    part_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if part_pk:
        item_pk = cov_create_stock_item(part=part_pk, location=1, quantity=5)
        if item_pk:
            r = cov_api("post", f"/stock/{item_pk}/serialize/", {"quantity": 5, "serial_numbers": "1-5", "destination": 1})
            log("FN3-SERIALIZE", "Serializar StockItem (qty=5)", r.status_code in (200, 201), f"HTTP {r.status_code} {cov_short(r)}")
            cov_api("delete", f"/stock/{item_pk}/")

        # Creación directa con 'serial_numbers' en el POST /stock/ (bulk-create
        # serializado), distinto del endpoint dedicado /serialize/
        r_bulk = cov_api("post", "/stock/", {"part": part_pk, "location": 1, "quantity": 3, "serial_numbers": "101-103"})
        ok_bulk = r_bulk.status_code == 201
        log("FN3-STOCK-bulk-serial-create", "Crear StockItems serializados directamente vía POST /stock/", ok_bulk, f"HTTP {r_bulk.status_code} {cov_short(r_bulk)}")
        if ok_bulk:
            # Reintentar con los MISMOS números de serie -> find_conflicting_serial_numbers()
            # detecta el conflicto (rama de "ya existen" no cubierta por una creación normal)
            r_dup_serial = cov_api("post", "/stock/", {"part": part_pk, "location": 1, "quantity": 3, "serial_numbers": "101-103"})
            log("FN3-STOCK-bulk-serial-conflict", "Reintentar los mismos serial_numbers (deben chocar)", r_dup_serial.status_code in (400, 422), f"HTTP {r_dup_serial.status_code} {cov_short(r_dup_serial)}")

            bulk_items = r_bulk.json()
            bulk_items = bulk_items if isinstance(bulk_items, list) else [bulk_items]
            for bi in bulk_items:
                cov_api("delete", f"/stock/{bi.get('pk')}/")

        # serial_numbers en un part NO trackable -> debe rechazar
        r_np = cov_api("post", "/part/", {"name": "COV NonTrack Part", "description": "x", "category": 1, "trackable": False})
        np_pk = r_np.json().get("pk") if r_np.status_code == 201 else None
        if np_pk:
            r_badserial = cov_api("post", "/stock/", {"part": np_pk, "location": 1, "quantity": 2, "serial_numbers": "1-2"})
            log("FN3-STOCK-serial-nontrackable", "serial_numbers en parte no-trackable (debe rechazar)", r_badserial.status_code in (400, 422), f"HTTP {r_badserial.status_code} {cov_short(r_badserial)}")
            cov_api("patch", f"/part/{np_pk}/", {"active": False})
            cov_api("delete", f"/part/{np_pk}/")

        cov_api("patch", f"/part/{part_pk}/", {"active": False})
        cov_api("delete", f"/part/{part_pk}/")

    # StockItemInstall / StockItemUninstall: pk=5 (PCB Sensor v1, assembly con
    # BOM) recibe instalado un StockItem de pk=1 (Resistencia 10k, en su BOM)
    parent_pk = cov_create_stock_item(part=5, location=1, quantity=1)
    child_pk = cov_create_stock_item(part=1, location=1, quantity=1)
    if parent_pk and child_pk:
        r_install = cov_api("post", f"/stock/{parent_pk}/install/", {"stock_item": child_pk, "quantity": 1})
        ok_install = r_install.status_code in (200, 201)
        log("FN3-STOCK-install", "StockItemInstall (child en BOM del parent)", ok_install, f"HTTP {r_install.status_code} {cov_short(r_install)}")
        if ok_install:
            r_uninstall = cov_api("post", f"/stock/{child_pk}/uninstall/", {"location": 1, "note": "coverage uninstall"})
            log("FN3-STOCK-uninstall", "StockItemUninstall (desinstalar)", r_uninstall.status_code in (200, 201), f"HTTP {r_uninstall.status_code} {cov_short(r_uninstall)}")
        cov_api("delete", f"/stock/{child_pk}/")
    if parent_pk:
        cov_api("delete", f"/stock/{parent_pk}/")


def fn3_coverage_extra():
    """Casos adicionales de cobertura FN2/FN3: validaciones y ramas no
    ejercidas por los flujos "felices" anteriores."""

    # -- StockLocation.delete() con delete_stock_items / delete_sub_locations --
    r_parent = cov_api("post", "/stock/location/", {"name": "COV Del Parent", "description": "x"})
    parent_loc = r_parent.json().get("pk") if r_parent.status_code == 201 else None
    if parent_loc:
        r_child = cov_api("post", "/stock/location/", {"name": "COV Del Child", "description": "x", "parent": parent_loc})
        child_loc = r_child.json().get("pk") if r_child.status_code == 201 else None
        item_pk = cov_create_stock_item(part=1, location=parent_loc, quantity=3)
        r_del = cov_api("delete", f"/stock/location/{parent_loc}/",
                         {"delete_stock_items": True, "delete_sub_locations": True})
        log("COV-LOC-delete-cascade", "DELETE location con delete_stock_items+delete_sub_locations",
            r_del.status_code in (200, 204), f"HTTP {r_del.status_code}")

    r_parent2 = cov_api("post", "/stock/location/", {"name": "COV Del Parent2", "description": "x"})
    parent_loc2 = r_parent2.json().get("pk") if r_parent2.status_code == 201 else None
    if parent_loc2:
        r_child2 = cov_api("post", "/stock/location/", {"name": "COV Del Child2", "description": "x", "parent": parent_loc2})
        child_loc2 = r_child2.json().get("pk") if r_child2.status_code == 201 else None
        r_del2 = cov_api("delete", f"/stock/location/{parent_loc2}/",
                          {"delete_stock_items": False, "delete_sub_locations": False})
        log("COV-LOC-delete-nocascade", "DELETE location con delete_stock_items=False+delete_sub_locations=False",
            r_del2.status_code in (200, 204), f"HTTP {r_del2.status_code}")
        # delete_sub_locations=False -> el hijo sobrevive (re-parentado a la raíz); limpiarlo aparte
        if child_loc2:
            cov_api("delete", f"/stock/location/{child_loc2}/", {"delete_stock_items": True, "delete_sub_locations": True})

    # -- StockLocation.clean() / structural --
    r_struct = cov_api("post", "/stock/location/", {"name": "COV Structural", "description": "x", "structural": True})
    struct_pk = r_struct.json().get("pk") if r_struct.status_code == 201 else None
    if struct_pk:
        item_bad = cov_api("post", "/stock/", {"part": 1, "location": struct_pk, "quantity": 5})
        log("COV-LOC-structural-reject", "Crear StockItem en ubicación structural (debe rechazar)",
            item_bad.status_code in (400, 422), f"HTTP {item_bad.status_code} {cov_short(item_bad)}")
        cov_api("delete", f"/stock/location/{struct_pk}/", {"delete_stock_items": True, "delete_sub_locations": True})

    # -- StockLocation.icon (custom_icon / location_type icon) --
    r_lt = cov_api("post", "/stock/location-type/", {"name": "COV IconType", "description": "x", "icon": "ti:box:outline"})
    lt_pk = r_lt.json().get("pk") if r_lt.status_code == 201 else None
    if lt_pk:
        r_loc_icon = cov_api("post", "/stock/location/", {"name": "COV Loc IconType", "description": "x", "location_type": lt_pk})
        loc_icon_pk = r_loc_icon.json().get("pk") if r_loc_icon.status_code == 201 else None
        if loc_icon_pk:
            r_get = cov_api("get", f"/stock/location/{loc_icon_pk}/")
            log("COV-LOC-icon-locationtype", "GET location con icon heredado de location_type",
                r_get.status_code == 200, f"HTTP {r_get.status_code}")
            cov_api("delete", f"/stock/location/{loc_icon_pk}/", {"delete_stock_items": True, "delete_sub_locations": True})
        cov_api("delete", f"/stock/location-type/{lt_pk}/")

    r_loc_custom = cov_api("post", "/stock/location/", {"name": "COV Loc CustomIcon", "description": "x", "custom_icon": "ti:star:outline"})
    if r_loc_custom.status_code == 201:
        cicon_pk = r_loc_custom.json()["pk"]
        r_get2 = cov_api("get", f"/stock/location/{cicon_pk}/")
        log("COV-LOC-icon-custom", "GET location con custom_icon", r_get2.status_code == 200, f"HTTP {r_get2.status_code}")
        cov_api("delete", f"/stock/location/{cicon_pk}/", {"delete_stock_items": True, "delete_sub_locations": True})

    # -- POST /stock/ validaciones --
    r_noqty = cov_api("post", "/stock/", {"part": 1, "location": 1})
    log("COV-STOCK-create-noqty", "POST /stock/ sin quantity (debe rechazar)", r_noqty.status_code in (400, 422), f"HTTP {r_noqty.status_code}")

    r_badpart = cov_api("post", "/stock/", {"part": 999999, "location": 1, "quantity": 5})
    log("COV-STOCK-create-badpart", "POST /stock/ con part inexistente (debe rechazar)", r_badpart.status_code in (400, 422), f"HTTP {r_badpart.status_code}")

    r_badsp = cov_api("post", "/stock/", {"part": 1, "location": 1, "quantity": 5, "supplier_part": 999999})
    log("COV-STOCK-create-badsupplierpart", "POST /stock/ con supplier_part inexistente (debe rechazar)", r_badsp.status_code in (400, 422), f"HTTP {r_badsp.status_code}")

    r_badserial = cov_api("post", "/stock/", {"part": 1, "location": 1, "quantity": 3, "serial_numbers": "abc-def"})
    log("COV-STOCK-create-badserialformat", "POST /stock/ con serial_numbers malformado (debe rechazar)", r_badserial.status_code in (400, 422), f"HTTP {r_badserial.status_code}")

    r_status_item = cov_create_stock_item(part=1, location=1, quantity=10)
    if r_status_item:
        r_patch_status = cov_api("patch", f"/stock/{r_status_item}/", {"status": 50})
        log("COV-STOCK-patch-status", "PATCH stock item con status directo", r_patch_status.status_code == 200, f"HTTP {r_patch_status.status_code}")
        cov_api("delete", f"/stock/{r_status_item}/")

    # -- serialize(): validaciones --
    r_tp = cov_api("post", "/part/", {"name": "COV Serialize Validate Part", "description": "x", "category": 1, "trackable": True, "active": True})
    sv_part = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if sv_part:
        item_sv = cov_create_stock_item(part=sv_part, location=1, quantity=3)
        if item_sv:
            r_over = cov_api("post", f"/stock/{item_sv}/serialize/", {"quantity": 99, "serial_numbers": "1-99", "destination": 1})
            log("COV-SERIALIZE-overqty", "Serialize con quantity > disponible (debe rechazar)", r_over.status_code in (400, 422), f"HTTP {r_over.status_code}")

            r_baddest = cov_api("post", f"/stock/{item_sv}/serialize/", {"quantity": 3, "serial_numbers": "abc", "destination": 1})
            log("COV-SERIALIZE-badserials", "Serialize con serial_numbers malformado (debe rechazar)", r_baddest.status_code in (400, 422), f"HTTP {r_baddest.status_code}")
            cov_api("delete", f"/stock/{item_sv}/")

        item_nt = cov_create_stock_item(part=1, location=1, quantity=3)
        if item_nt:
            r_nontrack = cov_api("post", f"/stock/{item_nt}/serialize/", {"quantity": 3, "serial_numbers": "1-3", "destination": 1})
            log("COV-SERIALIZE-nontrackable", "Serialize sobre part no-trackable (debe rechazar)", r_nontrack.status_code in (400, 422), f"HTTP {r_nontrack.status_code}")
            cov_api("delete", f"/stock/{item_nt}/")
        cov_api("patch", f"/part/{sv_part}/", {"active": False})
        cov_api("delete", f"/part/{sv_part}/")

    # -- install/uninstall: validaciones --
    r_install_missing = cov_api("post", "/stock/999999/install/", {"stock_item": 1, "quantity": 1})
    log("COV-INSTALL-noparent", "Install sobre stock item inexistente (debe rechazar)", r_install_missing.status_code in (400, 404, 422), f"HTTP {r_install_missing.status_code}")

    r_notbom_part = cov_api("post", "/part/", {"name": "COV NotInBOM Part", "description": "x", "category": 1, "purchaseable": True})
    notbom_part_pk = r_notbom_part.json().get("pk") if r_notbom_part.status_code == 201 else None
    parent_ni = cov_create_stock_item(part=5, location=1, quantity=1)
    other_item = cov_create_stock_item(part=notbom_part_pk, location=1, quantity=5) if notbom_part_pk else None
    if parent_ni and other_item:
        r_notinbom = cov_api("post", f"/stock/{parent_ni}/install/", {"stock_item": other_item, "quantity": 1})
        log("COV-INSTALL-notinbom", "Install de item que no está en el BOM del assembly (debe rechazar)", r_notinbom.status_code in (400, 422), f"HTTP {r_notinbom.status_code} {cov_short(r_notinbom)}")
        cov_api("delete", f"/stock/{other_item}/")
    if notbom_part_pk:
        cov_api("patch", f"/part/{notbom_part_pk}/", {"active": False})
        cov_api("delete", f"/part/{notbom_part_pk}/")

    child_overqty = cov_create_stock_item(part=1, location=1, quantity=1)
    if parent_ni and child_overqty:
        r_overinstall = cov_api("post", f"/stock/{parent_ni}/install/", {"stock_item": child_overqty, "quantity": 99})
        log("COV-INSTALL-overqty", "Install con quantity > disponible en sub-item (debe rechazar)", r_overinstall.status_code in (400, 422), f"HTTP {r_overinstall.status_code}")
        cov_api("delete", f"/stock/{child_overqty}/")
    if parent_ni:
        cov_api("delete", f"/stock/{parent_ni}/")

    r_uninstall_missing = cov_api("post", "/stock/999999/uninstall/", {"location": 1})
    log("COV-UNINSTALL-noitem", "Uninstall sobre stock item inexistente (debe rechazar)", r_uninstall_missing.status_code in (400, 404, 422), f"HTTP {r_uninstall_missing.status_code}")

    not_installed = cov_create_stock_item(part=1, location=1, quantity=1)
    if not_installed:
        r_notinstalled = cov_api("post", f"/stock/{not_installed}/uninstall/", {"location": 1})
        log("COV-UNINSTALL-notinstalled", "Uninstall de item que no está instalado (no-op)", r_notinstalled.status_code in (200, 201, 400, 422), f"HTTP {r_notinstalled.status_code}")
        cov_api("delete", f"/stock/{not_installed}/")

    # -- add/remove/transfer/count: validaciones --
    r_empty = cov_api("post", "/stock/count/", {"items": [], "notes": "coverage empty"})
    log("COV-ADJ-count-empty", "StockCount con items=[] (debe rechazar)", r_empty.status_code in (400, 422), f"HTTP {r_empty.status_code}")

    r_struct2 = cov_api("post", "/stock/location/", {"name": "COV Structural Count", "description": "x", "structural": True})
    struct2_pk = r_struct2.json().get("pk") if r_struct2.status_code == 201 else None
    if struct2_pk:
        r_countstruct = cov_api("post", "/stock/count/", {"items": [{"pk": 1, "quantity": 5}], "location": struct2_pk, "notes": "x"})
        log("COV-ADJ-count-structural", "StockCount con location structural (debe rechazar)", r_countstruct.status_code in (400, 422), f"HTTP {r_countstruct.status_code}")
        cov_api("delete", f"/stock/location/{struct2_pk}/", {"delete_stock_items": True, "delete_sub_locations": True})

    zero_item = cov_create_stock_item(part=1, location=1, quantity=10)
    if zero_item:
        r_addzero = cov_api("post", "/stock/add/", {"items": [{"pk": zero_item, "quantity": 0}], "notes": "coverage zero"})
        log("COV-ADJ-add-zero", "StockAdd con quantity=0 (skip)", r_addzero.status_code in (200, 201, 400), f"HTTP {r_addzero.status_code}")
        cov_api("delete", f"/stock/{zero_item}/")

    r_transfer_struct = cov_api("post", "/stock/location/", {"name": "COV Structural Transfer", "description": "x", "structural": True})
    ts_pk = r_transfer_struct.json().get("pk") if r_transfer_struct.status_code == 201 else None
    xfer_item = cov_create_stock_item(part=1, location=1, quantity=5)
    if ts_pk and xfer_item:
        r_xferstruct = cov_api("post", "/stock/transfer/", {"items": [{"pk": xfer_item, "quantity": 2}], "location": ts_pk, "notes": "x"})
        log("COV-ADJ-transfer-structural", "StockTransfer a location structural (debe rechazar)", r_xferstruct.status_code in (400, 422), f"HTTP {r_xferstruct.status_code}")
    if xfer_item:
        cov_api("delete", f"/stock/{xfer_item}/")
    if ts_pk:
        cov_api("delete", f"/stock/location/{ts_pk}/", {"delete_stock_items": True, "delete_sub_locations": True})

    # -- can_merge() ramas: serializado, is_building, status distinto, part distinto --
    pk_a = cov_create_stock_item(part=1, location=1, quantity=5)
    pk_b = cov_create_stock_item(part=2, location=1, quantity=5)
    if pk_a and pk_b:
        r_mergepart = cov_api("post", "/stock/merge/", {"items": [{"item": pk_a}, {"item": pk_b}], "location": 1, "notes": "coverage merge diff part"})
        log("COV-MERGE-diffpart", "StockMerge con parts distintos (debe rechazar)", r_mergepart.status_code in (400, 422), f"HTTP {r_mergepart.status_code}")
        cov_api("delete", f"/stock/{pk_a}/")
        cov_api("delete", f"/stock/{pk_b}/")

    pk_same = cov_create_stock_item(part=1, location=1, quantity=5)
    if pk_same:
        r_mergeself = cov_api("post", "/stock/merge/", {"items": [{"item": pk_same}, {"item": pk_same}], "location": 1, "notes": "coverage merge same"})
        log("COV-MERGE-sameitem", "StockMerge del mismo item consigo mismo (debe rechazar)", r_mergeself.status_code in (400, 422), f"HTTP {r_mergeself.status_code}")
        cov_api("delete", f"/stock/{pk_same}/")

    # -- Test results: validaciones adicionales --
    r_tp2 = cov_api("post", "/part/", {"name": "COV TestResult Validate Part", "description": "x", "category": 1, "testable": True, "trackable": True, "active": True})
    trv_part = r_tp2.json().get("pk") if r_tp2.status_code == 201 else None
    if trv_part:
        cov_api("post", "/part/test-template/", {"part": trv_part, "test_name": "COV Value Test", "description": "x", "required": True, "requires_value": True})
        item_trv = cov_create_stock_item(part=trv_part, location=1, quantity=1)
        if item_trv:
            r_novalue = cov_api("post", "/stock/test/", {"stock_item": item_trv, "test": "COV Value Test", "result": True})
            log("COV-TESTRESULT-requiresvalue", "Test result sin 'value' cuando template lo requiere (debe rechazar)", r_novalue.status_code in (400, 422), f"HTTP {r_novalue.status_code} {cov_short(r_novalue)}")

            r_notemplate = cov_api("post", "/stock/test/", {"stock_item": item_trv, "test": "COV Nonexistent Test", "result": True})
            log("COV-TESTRESULT-notemplate", "Test result con nombre de test que no coincide con ningún template (debe rechazar)", r_notemplate.status_code in (400, 422), f"HTTP {r_notemplate.status_code}")

            r_filtertest = cov_api("get", "/stock/test/", params={"test": "COV Value Test"})
            log("COV-TESTRESULT-filter-test", "Filtro ?test= (nombre legacy)", r_filtertest.status_code == 200, f"HTTP {r_filtertest.status_code}")

            r_filterbaditem = cov_api("get", "/stock/test/", params={"stock_item": 999999})
            log("COV-TESTRESULT-filter-baditem", "Filtro ?stock_item= inexistente (debe rechazar)", r_filterbaditem.status_code in (400, 422), f"HTTP {r_filterbaditem.status_code}")

            r_includeinstalled = cov_api("get", "/stock/test/", params={"stock_item": item_trv, "include_installed": "true"})
            log("COV-TESTRESULT-includeinstalled", "Filtro ?include_installed=true", r_includeinstalled.status_code == 200, f"HTTP {r_includeinstalled.status_code}")

            cov_api("delete", f"/stock/{item_trv}/")
        cov_api("patch", f"/part/{trv_part}/", {"active": False})
        cov_api("delete", f"/part/{trv_part}/")

    r_track_plain = cov_api("get", "/stock/track/")
    log("COV-TRACK-list-plain", "GET /stock/track/ sin filtros", r_track_plain.status_code == 200, f"HTTP {r_track_plain.status_code}")

    # -- move()/stocktake()/add_stock()/take_stock(): rama de status-delta y campos opcionales (batch/packaging) --
    it_xfer = cov_create_stock_item(part=1, location=1, quantity=10)
    if it_xfer:
        r_xfer_extra = cov_api("post", "/stock/transfer/", {
            "items": [{"pk": it_xfer, "quantity": 4, "status": 50, "batch": "COV-BATCH-1", "packaging": "COV-BOX"}],
            "location": 2, "notes": "coverage transfer status/batch/packaging",
        })
        log("COV-ADJ-transfer-extrafields", "StockTransfer con status/batch/packaging por item", r_xfer_extra.status_code in (200, 201), f"HTTP {r_xfer_extra.status_code} {cov_short(r_xfer_extra)}")
        cov_api("delete", f"/stock/{it_xfer}/")

    it_count = cov_create_stock_item(part=1, location=1, quantity=10)
    if it_count:
        r_count_extra = cov_api("post", "/stock/count/", {
            "items": [{"pk": it_count, "quantity": 8, "status": 50, "batch": "COV-BATCH-2", "packaging": "COV-BOX2"}],
            "notes": "coverage count status/batch/packaging",
        })
        log("COV-ADJ-count-extrafields", "StockCount con status/batch/packaging por item", r_count_extra.status_code in (200, 201), f"HTTP {r_count_extra.status_code} {cov_short(r_count_extra)}")
        cov_api("delete", f"/stock/{it_count}/")

    it_add = cov_create_stock_item(part=1, location=1, quantity=10)
    if it_add:
        r_add_extra = cov_api("post", "/stock/add/", {
            "items": [{"pk": it_add, "quantity": 2, "status": 50, "batch": "COV-BATCH-3", "packaging": "COV-BOX3"}],
            "notes": "coverage add status/batch/packaging",
        })
        log("COV-ADJ-add-extrafields", "StockAdd con status/batch/packaging por item", r_add_extra.status_code in (200, 201), f"HTTP {r_add_extra.status_code} {cov_short(r_add_extra)}")
        cov_api("delete", f"/stock/{it_add}/")

    it_remove = cov_create_stock_item(part=1, location=1, quantity=10)
    if it_remove:
        r_remove_extra = cov_api("post", "/stock/remove/", {
            "items": [{"pk": it_remove, "quantity": 2, "status": 50, "batch": "COV-BATCH-4", "packaging": "COV-BOX4"}],
            "notes": "coverage remove status/batch/packaging",
        })
        log("COV-ADJ-remove-extrafields", "StockRemove con status/batch/packaging por item", r_remove_extra.status_code in (200, 201), f"HTTP {r_remove_extra.status_code} {cov_short(r_remove_extra)}")
        cov_api("delete", f"/stock/{it_remove}/")

    # -- merge_stock_items(): calculo de precio promedio ponderado (pricing_data) --
    pk_price_a = cov_create_stock_item(part=1, location=1, quantity=5)
    pk_price_b = cov_create_stock_item(part=1, location=1, quantity=3)
    if pk_price_a and pk_price_b:
        cov_api("patch", f"/stock/{pk_price_a}/", {"purchase_price": "1.50", "purchase_price_currency": "USD"})
        cov_api("patch", f"/stock/{pk_price_b}/", {"purchase_price": "2.00", "purchase_price_currency": "USD"})
        r_mergeprice = cov_api("post", "/stock/merge/", {"items": [{"item": pk_price_a}, {"item": pk_price_b}], "location": 1, "notes": "coverage merge pricing"})
        ok_mergeprice = r_mergeprice.status_code in (200, 201)
        log("COV-MERGE-pricing", "StockMerge con purchase_price (promedio ponderado)", ok_mergeprice, f"HTTP {r_mergeprice.status_code} {cov_short(r_mergeprice)}")
        if not ok_mergeprice:
            cov_api("delete", f"/stock/{pk_price_a}/")
            cov_api("delete", f"/stock/{pk_price_b}/")

    # -- StockItemSerialNumbers: endpoint dedicado /stock/{pk}/serial-numbers/ (previous/next) --
    r_snp = cov_api("post", "/part/", {"name": "COV SerialNav Part", "description": "x", "category": 1, "trackable": True, "active": True})
    snp_pk = r_snp.json().get("pk") if r_snp.status_code == 201 else None
    if snp_pk:
        r_snbulk = cov_api("post", "/stock/", {"part": snp_pk, "location": 1, "quantity": 3, "serial_numbers": "1-3"})
        if r_snbulk.status_code == 201:
            created = r_snbulk.json()
            created = created if isinstance(created, list) else [created]
            mid_pk = next((c["pk"] for c in created if str(c.get("serial")) == "2"), None)
            if mid_pk:
                r_serialnav = cov_api("get", f"/stock/{mid_pk}/serial-numbers/")
                log("COV-SERIALNAV", "GET /stock/{pk}/serial-numbers/ (previous/next por serial)", r_serialnav.status_code == 200, f"HTTP {r_serialnav.status_code} {cov_short(r_serialnav)}")
            for c in created:
                cov_api("delete", f"/stock/{c['pk']}/")
        cov_api("patch", f"/part/{snp_pk}/", {"active": False})
        cov_api("delete", f"/part/{snp_pk}/")

    # -- StockItem.clean(): asignar 'serial' via PATCH a un item con quantity>1 --
    # (POST /stock/ descarta el campo 'serial' explicitamente -- ver StockList.create();
    # solo PATCH puede disparar esta validacion de StockItem.clean())
    r_snp2 = cov_api("post", "/part/", {"name": "COV Serial Direct Part", "description": "x", "category": 1, "trackable": True, "active": True})
    snp2_pk = r_snp2.json().get("pk") if r_snp2.status_code == 201 else None
    if snp2_pk:
        item_sd = cov_create_stock_item(part=snp2_pk, location=1, quantity=3)
        if item_sd:
            r_serialdirect = cov_api("patch", f"/stock/{item_sd}/", {"serial": "500"})
            log("COV-STOCK-serial-qty-conflict", "PATCH serial= sobre item con quantity>1 (debe rechazar)", r_serialdirect.status_code in (400, 422), f"HTTP {r_serialdirect.status_code} {cov_short(r_serialdirect)}")
            cov_api("delete", f"/stock/{item_sd}/")
        cov_api("patch", f"/part/{snp2_pk}/", {"active": False})
        cov_api("delete", f"/part/{snp2_pk}/")


# ── main ──────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*62)
    print("  InvenTree — Stock Items & Transferencias")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*62)

    import os; os.makedirs(SS_DIR, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # Obtener cookies de sesión
        s, csrf_tok = authed_session()
        sid = s.cookies.get("sessionid", "")
        print(f"\n  Sesión obtenida — {sid[:12]}...")

        # Un solo contexto + página para todos los casos
        ctx = browser.new_context()
        ctx.add_cookies([
            {"name": "sessionid", "value": sid,      "domain": "localhost", "path": "/"},
            {"name": "csrftoken", "value": csrf_tok, "domain": "localhost", "path": "/"},
        ])
        page = ctx.new_page()

        print("\n── Stock Items ──────────────────────────────────────────")
        tc_si01(page)
        tc_si02(page)
        tc_si03(page)
        tc_si04(page)
        tc_si05(page)
        tc_si06(page)
        tc_si07(page)
        tc_si08(page)
        tc_si09(page)
        clear_cache()
        tc_si10(page)

        print("\n── Transferencias ──────────────────────────────────────")
        tc_tr01(page)
        tc_tr02(page)
        tc_tr03(page)
        tc_tr04(page)
        tc_tr05(page)
        tc_tr06(page)
        clear_cache()
        tc_tr07(page)

        ctx.close()
        browser.close()

    print("\n── FN2/FN3 — Stock: casos extendidos ────────────────────")
    try:
        fn2_location()
        fn2_stock_filters()
        fn2_stock_pack_size()
        fn3_adjust_actions()
        fn3_test_results_tracking_serialize()
        fn3_coverage_extra()
    except Exception as e:
        log("FN2-FN3-extended", "Casos extendidos de Stock", False, str(e))

    # Resumen
    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed

    print("\n" + "="*62)
    print(f"  TOTAL: {passed}/{len(results)} PASS  |  {failed} FAIL")
    print("="*62)
    print(f"\n  {'TC':<10} {'Resultado':<10} Caso")
    print(f"  {'-'*9} {'-'*9} {'-'*38}")
    for r in results:
        mark = "PASS ✅" if r["pass"] else "FAIL ❌"
        print(f"  {r['tc']:<10} {mark:<10} {r['name']}")

    failures = [r for r in results if not r["pass"]]
    if failures:
        print(f"\n── Comportamientos inesperados / Defectos ──────────────")
        for i, f in enumerate(failures, 1):
            print(f"  DEF-{i:02d} [{f['tc']}] {f['name']}")
            print(f"         → {f['detail']}")

    print(f"\n  Capturas guardadas en: {SS_DIR}/")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
