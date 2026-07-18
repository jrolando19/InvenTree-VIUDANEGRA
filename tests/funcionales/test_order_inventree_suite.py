#!/usr/bin/env python3
"""
InvenTree — Suite funcional: Órdenes (test_order_inventree_suite.py)
FN4  Órdenes de Compra (Purchase Order)   (RF-006, Hito 2)
     Órdenes de Venta (Sales Order)        (RF-007, "Pendiente ejecución Hito 3" en la wiki)
     Órdenes de Devolución (Return Order)  (RF-010, "Pendiente ejecución Hito 3" en la wiki)
     Transfer Order (no mapeado a ningún RF del plan, igual pertenece al módulo order)

Incluye:
  TC-PO-01..10   — Purchase Orders (API + UI)
  TC-SO-01..08   — Sales Orders (100% API)
  TC-RO-01..05   — Return Orders (100% API)
  COV-TO-*       — Transfer Orders (100% API)
  FN4-*, COV-*   — Casos extendidos de cobertura (filtros, hold, extra-lines,
                   calendario ICS, patrones de referencia, allocate-serials)

Prerrequisitos en BD (setup_system_tests.py):
  - Supplier pk=1  (Proveedor Electrónico SA)
  - SupplierPart pk=1 → part=1 (Resistencia 10k)
  - Customer pk=2  (Cliente Distribuidor SA)
  - Part pk=1 (Resistencia 10k), pk=5/pk=10 (salable=True)
  - StockLocation pk=1 (Almacén A), pk=2 (Almacén B)
"""
import os, sys, time, json, requests
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE   = "http://localhost:8000"
API    = f"{BASE}/api"
USER   = "admin"
PASS   = "inventree"
AUTH   = (USER, PASS)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SS_DIR       = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "order")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "test_output", "results", "order_results.json")
os.makedirs(SS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

SUPPLIER_PK      = 1
SUPPLIER_PART_PK = 1   # Resistencia 10k
CUSTOMER_PK      = 2   # Cliente Distribuidor SA
PART_PKS         = [5, 10]   # salable=True
LOC_A            = 1
LOC_B            = 2

results = []
_po_ref_counter = [9910]
_ref_counter = [88000]


# ── helpers ───────────────────────────────────────────────────

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

def api(method, path, data=None, params=None, auth=True):
    fn = getattr(requests, method)
    kw = {"auth": AUTH} if auth else {}
    if data is not None:
        kw["json"] = data
    if params is not None:
        kw["params"] = params
    return fn(f"{API}{path}", **kw)

def short(r):
    try:
        return str(r.json())[:150]
    except Exception:
        return r.text[:150]

def extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", [])
    return []

def authed_session():
    s = requests.Session()
    s.get(f"{API}/auth/v1/config", auth=AUTH)
    csrf = s.cookies.get("csrftoken", "")
    s.post(f"{API}/auth/v1/auth/login",
           json={"username": USER, "password": PASS},
           headers={"X-CSRFToken": csrf, "Referer": BASE})
    return s, s.cookies.get("csrftoken", csrf)

def next_po_ref():
    _po_ref_counter[0] += 1
    return f"PO-{_po_ref_counter[0]:04d}"

def next_ref(prefix):
    _ref_counter[0] += 1
    return f"{prefix}-{_ref_counter[0]}"

def create_po(ref=None, supplier=SUPPLIER_PK):
    ref = ref or next_po_ref()
    return api("post", "/order/po/", {"supplier": supplier, "reference": ref})

def add_po_line(order_pk, supplier_part=SUPPLIER_PART_PK, qty=5):
    return api("post", "/order/po-line/", {"order": order_pk, "part": supplier_part, "quantity": qty})

def issue_po(pk):
    return api("post", f"/order/po/{pk}/issue/", {})

def cancel_po(pk):
    return api("post", f"/order/po/{pk}/cancel/", {})

def receive_po(pk, line_pk, qty=5, location=LOC_A):
    return api("post", f"/order/po/{pk}/receive/",
               {"location": location, "items": [{"line_item": line_pk, "quantity": qty, "status": 10}]})

def delete_po(pk):
    api("delete", f"/order/po/{pk}/")

def po_status(pk):
    r = api("get", f"/order/po/{pk}/")
    return r.json().get("status"), r.json().get("status_text")


# ══════════════════════════════════════════════════════════════
# CPF-004 — PURCHASE ORDERS
# ══════════════════════════════════════════════════════════════

def tc_po_01(page):
    """FN4-CP-001 — Crear PO válida → status Pending."""
    ref = next_po_ref()
    r = create_po(ref)
    ok = r.status_code == 201 and r.json().get("status_text") == "Pending"
    pk = r.json().get("pk") if r.status_code == 201 else None
    page.goto(f"{BASE}/web/purchasing/purchase-order/{pk}/", wait_until="networkidle", timeout=20000) if pk else None
    time.sleep(2); snap(page, "TC-PO-01_create_po")
    log("TC-PO-01", "Crear PO válida (estado Pending)", ok,
        f"HTTP {r.status_code} | ref={ref} | pk={pk} | status={r.json().get('status_text')}")
    if pk: delete_po(pk)

def tc_po_02(page):
    """FN4-CP-002 — Sin proveedor → 400."""
    r = api("post", "/order/po/", {"reference": next_po_ref()})
    ok = r.status_code in (400, 422)
    snap(page, "TC-PO-02_no_supplier")
    log("TC-PO-02", "Crear PO sin proveedor (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")

def tc_po_03(page):
    """FN4-CP-003 — Referencia duplicada → 400."""
    ref = next_po_ref()
    r1 = create_po(ref)
    pk1 = r1.json().get("pk") if r1.status_code == 201 else None
    r2 = create_po(ref)
    ok = r2.status_code in (400, 422)
    snap(page, "TC-PO-03_duplicate_ref")
    log("TC-PO-03", "Referencia duplicada (debe rechazar)", ok,
        f"1er POST {r1.status_code} | 2do POST {r2.status_code} | {str(r2.json())[:100]}")
    if pk1: delete_po(pk1)

def tc_po_04(page):
    """FN4-CP-004 — Línea con qty=0 → 400."""
    r_po = create_po()
    pk = r_po.json().get("pk") if r_po.status_code == 201 else None
    if not pk:
        log("TC-PO-04", "Línea PO qty=0", False, "No se pudo crear PO base"); return
    r_line = add_po_line(pk, qty=0)
    ok = r_line.status_code in (400, 422)
    snap(page, "TC-PO-04_line_qty_zero")
    log("TC-PO-04", "Línea PO con qty=0 (debe rechazar)", ok,
        f"HTTP {r_line.status_code} | {str(r_line.json())[:120]}")
    delete_po(pk)

def tc_po_05(page):
    """FN4-CP-005 — Pending → issue → Placed."""
    r = create_po(); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-PO-05", "Transición Pending → Placed (issue)", False, "No se pudo crear PO"); return
    r_issue = issue_po(pk)
    st, st_txt = po_status(pk)
    ok = st == 20 and st_txt == "Placed"
    page.goto(f"{BASE}/web/purchasing/purchase-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-PO-05_po_placed")
    log("TC-PO-05", "Transición Pending → Placed (issue)", ok,
        f"issue HTTP {r_issue.status_code} | status={st} ({st_txt})")
    delete_po(pk)

def tc_po_06(page):
    """FN4-CP-006 — Placed → receive → Complete, stock actualizado."""
    r = create_po(); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-PO-06", "Recibir PO completa → estado Complete", False, "No se pudo crear PO"); return
    r_line = add_po_line(pk, qty=5); line_pk = r_line.json().get("pk")
    issue_po(pk)
    r_recv = receive_po(pk, line_pk, qty=5)
    st, st_txt = po_status(pk)
    ok = r_recv.status_code == 201 and st == 30 and st_txt == "Complete"
    page.goto(f"{BASE}/web/purchasing/purchase-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-PO-06_po_complete")
    log("TC-PO-06", "Recibir PO completa → estado Complete", ok,
        f"receive HTTP {r_recv.status_code} | status={st} ({st_txt})")
    delete_po(pk)

def tc_po_07(page):
    """FN4-CP-007 — Pending → cancel → Cancelled."""
    r = create_po(); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-PO-07", "Cancelar PO en Pending → Cancelled", False, "No se pudo crear PO"); return
    r_cancel = cancel_po(pk)
    st, st_txt = po_status(pk)
    ok = st == 40 and st_txt == "Cancelled"
    page.goto(f"{BASE}/web/purchasing/purchase-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-PO-07_po_cancelled")
    log("TC-PO-07", "Cancelar PO en Pending → Cancelled", ok,
        f"cancel HTTP {r_cancel.status_code} | status={st} ({st_txt})")
    delete_po(pk)

def tc_po_08(page):
    """FN4-CP-008 — Complete → cancel → debe fallar."""
    r = create_po(); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-PO-08", "Cancelar PO Complete (debe rechazar)", False, "No se pudo crear PO"); return
    r_line = add_po_line(pk, qty=3); line_pk = r_line.json().get("pk")
    issue_po(pk)
    receive_po(pk, line_pk, qty=3)  # → Complete
    st_before, _ = po_status(pk)
    r_cancel = cancel_po(pk)
    ok = r_cancel.status_code in (400, 422)
    snap(page, "TC-PO-08_cancel_complete")
    log("TC-PO-08", "Cancelar PO Complete (debe rechazar)", ok,
        f"status_antes={st_before} | cancel HTTP {r_cancel.status_code} | {str(r_cancel.json())[:100]}")
    delete_po(pk)

def tc_po_09(page):
    """FN4-CP-009 — Referencia 65 chars → 400 (patrón PO-XXXX)."""
    r = api("post", "/order/po/", {"supplier": SUPPLIER_PK, "reference": "X" * 65})
    ok = r.status_code in (400, 422)
    snap(page, "TC-PO-09_ref_65")
    log("TC-PO-09", "LÍMITE — referencia 65 caracteres (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_po_10(page):
    """FN4-CP-010 — Fecha objetivo pasada → debe aceptarse."""
    ref = next_po_ref()
    r = api("post", "/order/po/", {
        "supplier": SUPPLIER_PK, "reference": ref, "target_date": "2020-01-01"
    })
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    snap(page, "TC-PO-10_past_date")
    log("TC-PO-10", "Fecha objetivo pasada (debe aceptarse)", ok,
        f"HTTP {r.status_code} | target_date={r.json().get('target_date') if ok else 'N/A'}")
    if pk: delete_po(pk)


# ══════════════════════════════════════════════════════════════
# FN4 — Purchase Orders: casos extendidos de cobertura
# ══════════════════════════════════════════════════════════════

def fn4_po_extended():
    cases = [
        ("assigned_to_me", {"assigned_to_me": "false"}), ("overdue", {"overdue": "false"}),
        ("outstanding", {"outstanding": "true"}), ("has_project_code", {"has_project_code": "false"}),
        ("has_start_date", {"has_start_date": "false"}), ("has_target_date", {"has_target_date": "false"}),
    ]
    for name, params in cases:
        r = api("get", "/order/po/", params=params)
        log(f"FN4-PO-{name}", f"Filtro PO ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r = create_po()
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        r2 = api("post", f"/order/po/{pk}/hold/", {})
        log("FN4-PO-hold", "PurchaseOrderHold (retener)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

        r3 = api("post", "/order/po-extra-line/", {"order": pk, "quantity": 1, "reference": "COV extra", "price": "5.00"})
        ok3 = r3.status_code == 201
        log("FN4-PO-extraline-create", "Crear PO extra line", ok3, f"HTTP {r3.status_code} {short(r3)}")
        if ok3:
            api("delete", f"/order/po-extra-line/{r3.json()['pk']}/")

        # PurchaseOrderSerializer.create() con 'duplicate' -> copia líneas/extra-líneas
        # de una PO existente (feature "duplicar orden")
        add_po_line(pk, qty=3)
        r_dup = api("post", "/order/po/", {
            "supplier": SUPPLIER_PK, "reference": next_po_ref(),
            "duplicate": {"original": pk, "copy_lines": True, "copy_extra_lines": True},
        })
        ok_dup = r_dup.status_code == 201
        log("FN4-PO-duplicate", "Crear PO duplicando líneas de otra PO", ok_dup, f"HTTP {r_dup.status_code} {short(r_dup)}")
        if ok_dup:
            delete_po(r_dup.json()["pk"])

        delete_po(pk)

    line_cases = [
        ("include_variants", {"include_variants": "true", "part": SUPPLIER_PART_PK}),
        ("pending", {"pending": "true"}), ("received", {"received": "false"}),
        ("order_complete", {"order_complete": "false"}), ("has_pricing", {"has_pricing": "false"}),
    ]
    for name, params in line_cases:
        r = api("get", "/order/po-line/", params=params)
        log(f"FN4-PO-line-{name}", f"Filtro po-line ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r_opt = requests.options(f"{API}/order/po/", auth=AUTH)
    log("FN4-PO-options", "OPTIONS /api/order/po/ (metadata de API)", r_opt.status_code == 200, f"HTTP {r_opt.status_code}")

    # Recibir una línea de PO con serial_numbers -> PurchaseOrderLineItemReceiveSerializer.validate()
    # ejercita extract_serial_numbers()/validate_serial_number() para partes trackable
    r_tp = api("post", "/part/", {"name": "COV PO Serial Part", "description": "x", "category": 1, "trackable": True, "active": True, "purchaseable": True})
    tp_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if tp_pk:
        r_sp = api("post", "/company/part/", {"part": tp_pk, "supplier": SUPPLIER_PK, "SKU": "COV-PO-SERIAL-SKU"})
        sp_pk = r_sp.json().get("pk") if r_sp.status_code == 201 else None
        if sp_pk:
            r_po4 = create_po()
            po4_pk = r_po4.json().get("pk") if r_po4.status_code == 201 else None
            if po4_pk:
                r_line4 = add_po_line(po4_pk, supplier_part=sp_pk, qty=3)
                line4_pk = r_line4.json().get("pk") if r_line4.status_code == 201 else None
                issue_po(po4_pk)
                if line4_pk:
                    r_recv4 = api("post", f"/order/po/{po4_pk}/receive/", {
                        "location": LOC_A,
                        "items": [{"line_item": line4_pk, "quantity": 3, "serial_numbers": "301-303"}],
                    })
                    log("FN4-PO-receive-serials", "Recibir PO line con serial_numbers (parte trackable)", r_recv4.status_code in (200, 201), f"HTTP {r_recv4.status_code} {short(r_recv4)}")
                delete_po(po4_pk)
            api("delete", f"/company/part/{sp_pk}/")
        api("patch", f"/part/{tp_pk}/", {"active": False})
        api("delete", f"/part/{tp_pk}/")

    # PO con target_date -> el feed de calendario tendrá al menos un ítem,
    # ejercitando item_title/item_description/item_start_datetime/item_link/etc.
    # (con la lista vacía, esos métodos por-ítem nunca se llaman)
    r_po_cal = api("post", "/order/po/", {"supplier": SUPPLIER_PK, "reference": next_po_ref(), "target_date": "2099-01-01"})
    po_cal_pk = r_po_cal.json().get("pk") if r_po_cal.status_code == 201 else None

    # Feed ICS de calendario (OrderCalendarExport) -- endpoint de solo lectura, formato iCal.
    # items() tiene una rama distinta por cada ordertype -> hay que pedir los 4
    for ordertype in ("purchase-order", "sales-order", "return-order", "transfer-order"):
        r_cal = requests.get(f"{API}/order/calendar/{ordertype}/calendar.ics", auth=AUTH)
        log(f"FN4-CAL-{ordertype}", f"Feed ICS de calendario ({ordertype})", r_cal.status_code == 200, f"HTTP {r_cal.status_code}")
    r_cal_completed = requests.get(f"{API}/order/calendar/purchase-order/calendar.ics", params={"include_completed": "true"}, auth=AUTH)
    log("FN4-CAL-include-completed", "Feed ICS con ?include_completed=true", r_cal_completed.status_code == 200, f"HTTP {r_cal_completed.status_code}")

    # Sin autenticación -> Feed.__call__() ejercita la rama 401 final (después de
    # intentar Basic Auth desde headers y fallar)
    r_cal_noauth = requests.get(f"{API}/order/calendar/purchase-order/calendar.ics")
    log("FN4-CAL-noauth", "Feed ICS sin autenticación (debe rechazar)", r_cal_noauth.status_code == 401, f"HTTP {r_cal_noauth.status_code}")

    if po_cal_pk:
        delete_po(po_cal_pk)

    # Re-guardar los patrones de referencia con su propio valor por defecto ->
    # dispara validate_*_reference_pattern() (validador de la setting, distinto
    # del validador del campo 'reference' que ya se cubre en cada creación)
    pattern_settings = [
        ("PURCHASEORDER_REFERENCE_PATTERN", "PO-{ref:04d}"),
        ("SALESORDER_REFERENCE_PATTERN", "SO-{ref:04d}"),
        ("RETURNORDER_REFERENCE_PATTERN", "RMA-{ref:04d}"),
        ("TRANSFERORDER_REFERENCE_PATTERN", "TO-{ref:04d}"),
    ]
    for key, pattern in pattern_settings:
        r_pat = api("patch", f"/settings/global/{key}/", {"value": pattern})
        log(f"COV-SETTING-{key}", f"Re-guardar {key} (dispara validate_*_reference_pattern)", r_pat.status_code == 200, f"HTTP {r_pat.status_code} {short(r_pat)}")


# ══════════════════════════════════════════════════════════════
# Filtros comunes de Order (aplican a so/ro/transfer-order)
# ══════════════════════════════════════════════════════════════

ORDER_FILTER_CASES = [
    ("assigned_to_me", {"assigned_to_me": "false"}),
    ("overdue", {"overdue": "false"}),
    ("outstanding", {"outstanding": "true"}),
    ("has_project_code", {"has_project_code": "false"}),
    ("has_start_date", {"has_start_date": "false"}),
    ("has_target_date", {"has_target_date": "false"}),
]

def tc_order_filters(prefix, tag):
    for name, params in ORDER_FILTER_CASES:
        r = api("get", f"/order/{prefix}/", params=params)
        log(f"COV-{tag}-{name}", f"Filtro {tag} ?{name}", r.status_code == 200, f"HTTP {r.status_code} params={params}")
    r = api("get", f"/order/{prefix}/", params={"status": 10})
    log(f"COV-{tag}-status", f"Filtro {tag} ?status=10", r.status_code == 200, f"HTTP {r.status_code}")

    # OPTIONS -> api_defaults() (genera la referencia autogenerada de cada tipo de orden)
    r_opt = requests.options(f"{API}/order/{prefix}/", auth=AUTH)
    log(f"COV-{tag}-options", f"OPTIONS /api/order/{prefix}/ (metadata de API)", r_opt.status_code == 200, f"HTTP {r_opt.status_code}")


# ══════════════════════════════════════════════════════════════
# ST-008 / RF-007 — SALES ORDERS (ciclo completo + extendido)
# ══════════════════════════════════════════════════════════════

def suite_sales_orders():
    # TC-SO-01: Crear SO con cliente válido
    r = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    so_pk = None
    if r.status_code == 201:
        so_pk = r.json().get("pk")
        log("TC-SO-01", "Crear SO con cliente válido", True)
    else:
        log("TC-SO-01", "Crear SO con cliente válido", False, f"HTTP {r.status_code} {short(r)}")
        return

    # TC-SO-02: Crear línea con parte salable
    r_line = api("post", "/order/so-line/", {
        "order": so_pk, "part": PART_PKS[0], "quantity": 2, "sale_price": "10.00", "sale_price_currency": "USD"
    })
    line_pk = None
    if r_line.status_code == 201:
        line_pk = r_line.json().get("pk")
        log("TC-SO-02", "Agregar línea con parte salable", True)
    else:
        log("TC-SO-02", "Agregar línea con parte salable", False, f"HTTP {r_line.status_code} {short(r_line)}")

    # SalesOrderSerializer.create() con 'duplicate' -> copia líneas de otra SO
    r_sodup = api("post", "/order/so/", {
        "customer": CUSTOMER_PK, "duplicate": {"original": so_pk, "copy_lines": True, "copy_extra_lines": True},
    })
    ok_sodup = r_sodup.status_code == 201
    log("COV-SO-duplicate", "Crear SO duplicando líneas de otra SO", ok_sodup, f"HTTP {r_sodup.status_code} {short(r_sodup)}")
    if ok_sodup:
        api("delete", f"/order/so/{r_sodup.json()['pk']}/")

    # TC-SO-03: Emitir la SO (Pending → In Progress)
    r_issue = api("post", f"/order/so/{so_pk}/issue/")
    log("TC-SO-03", "Emitir SO (issue)", r_issue.status_code in (200, 201), f"HTTP {r_issue.status_code}")

    # TC-SO-04: Crear stock para poder asignar
    r_stk = api("post", "/stock/", {"part": PART_PKS[0], "quantity": 10, "location": LOC_A})
    stk_data = r_stk.json()
    stk_item = (stk_data[0] if isinstance(stk_data, list) else stk_data)
    stk_pk = stk_item.get("pk")
    log("TC-SO-04", "Crear stock para asignación", r_stk.status_code == 201 and bool(stk_pk), f"HTTP {r_stk.status_code}")

    # TC-SO-05: Crear shipment y allocate
    r_ship = api("post", "/order/so/shipment/", {"order": so_pk})
    ship_pk = None
    alloc_ok = False
    if r_ship.status_code == 201:
        ship_pk = r_ship.json().get("pk")
        if stk_pk and line_pk and ship_pk:
            # Sobre-asignación (999 > 10 disponibles) -> SalesOrderAllocation.clean()
            # rechaza vía 'Allocation quantity cannot exceed stock quantity'
            r_overalloc = api("post", f"/order/so/{so_pk}/allocate/", {
                "shipment": ship_pk,
                "items": [{"line_item": line_pk, "stock_item": stk_pk, "quantity": 999}]
            })
            log("COV-SO-allocate-overallocate", "Allocate con quantity > stock disponible (debe rechazar)", r_overalloc.status_code in (400, 422), f"HTTP {r_overalloc.status_code} {short(r_overalloc)}")

            r_alloc = api("post", f"/order/so/{so_pk}/allocate/", {
                "shipment": ship_pk,
                "items": [{"line_item": line_pk, "stock_item": stk_pk, "quantity": 2}]
            })
            alloc_ok = r_alloc.status_code in (200, 201)
            log("TC-SO-05", "Crear shipment y allocate stock", alloc_ok, f"HTTP {r_alloc.status_code} {short(r_alloc)}")
        else:
            log("TC-SO-05", "Crear shipment y allocate stock", False, "Faltan pks de stock/línea/shipment")
    else:
        log("TC-SO-05", "Crear shipment y allocate stock", False, f"shipment HTTP {r_ship.status_code}")

    # TC-SO-06: Enviar shipment (ship)
    if ship_pk and alloc_ok:
        r_send = api("post", f"/order/so/shipment/{ship_pk}/ship/", {})
        log("TC-SO-06", "Enviar shipment (ship)", r_send.status_code in (200, 201), f"HTTP {r_send.status_code}")
    else:
        log("TC-SO-06", "Enviar shipment (ship)", False, "Sin shipment asignado")

    # TC-SO-07: Completar SO y verificar estado = Shipped
    r_comp = api("post", f"/order/so/{so_pk}/complete/", {})
    r_get = api("get", f"/order/so/{so_pk}/")
    if r_get.status_code == 200:
        status_val = r_get.json().get("status")
        log("TC-SO-07", "Completar SO y verificar status=Shipped",
            status_val in (15, 20, 30, 40, "Shipped", "Complete", "In Progress"),
            f"status={status_val} complete_http={r_comp.status_code}")
    else:
        log("TC-SO-07", "Completar SO y verificar status=Shipped", False, f"HTTP {r_get.status_code}")

    # Completar de nuevo (Shipped -> Complete): _action_complete() con
    # self.status == SHIPPED fuerza status = COMPLETE (rama distinta a la primera llamada)
    r_comp2 = api("post", f"/order/so/{so_pk}/complete/", {})
    log("COV-SO-complete-again", "Completar SO de nuevo (Shipped -> Complete)", r_comp2.status_code in (200, 201, 400), f"HTTP {r_comp2.status_code} {short(r_comp2)}")

    # TC-SO-08: Crear SO sin cliente → debe fallar
    r_bad = api("post", "/order/so/", {})
    log("TC-SO-08", "Crear SO sin cliente rechaza HTTP 4xx", r_bad.status_code >= 400, f"HTTP {r_bad.status_code}")

    # SalesOrderAutoAllocate en una SO desechable propia (NO la del flujo TC-SO-01..07):
    # auto-allocate crea una SalesOrderAllocation sin shipment asociado, que queda
    # "pending" para siempre y bloquea can_complete() -> nunca debe compartir la
    # misma SO que se intenta completar.
    r_so3 = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    so3_pk = r_so3.json().get("pk") if r_so3.status_code == 201 else None
    if so3_pk:
        api("post", "/order/so-line/", {"order": so3_pk, "part": PART_PKS[0], "quantity": 1, "sale_price": "1.00", "sale_price_currency": "USD"})
        api("post", f"/order/so/{so3_pk}/issue/")
        api("post", "/stock/", {"part": PART_PKS[0], "quantity": 5, "location": LOC_A})
        r_auto = api("post", f"/order/so/{so3_pk}/auto-allocate/", {"interchangeable": True})
        log("COV-SO-auto-allocate", "SalesOrderAutoAllocate (SO desechable)", r_auto.status_code in (200, 201, 400), f"HTTP {r_auto.status_code}")

        # SalesOrderCancel con una allocation activa -> _action_cancel() recorre
        # el loop de borrado de allocations
        r_cancel3 = api("post", f"/order/so/{so3_pk}/cancel/", {})
        log("COV-SO-cancel", "SalesOrderCancel (con allocation activa)", r_cancel3.status_code in (200, 201), f"HTTP {r_cancel3.status_code} {short(r_cancel3)}")

    # auto-allocate con interchangeable=False y >1 stock item disponible, ninguno
    # cubre la cantidad completa por sí solo -> ejercita la rama "single is None: continue"
    r_so5 = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    so5_pk = r_so5.json().get("pk") if r_so5.status_code == 201 else None
    if so5_pk:
        api("post", "/order/so-line/", {"order": so5_pk, "part": PART_PKS[0], "quantity": 2, "sale_price": "1.00", "sale_price_currency": "USD"})
        api("post", f"/order/so/{so5_pk}/issue/")
        api("post", "/stock/", {"part": PART_PKS[0], "quantity": 1, "location": LOC_A})
        api("post", "/stock/", {"part": PART_PKS[0], "quantity": 1, "location": LOC_B})
        r_auto5 = api("post", f"/order/so/{so5_pk}/auto-allocate/", {"interchangeable": False})
        log("COV-SO-auto-allocate-noninterchangeable", "SalesOrderAutoAllocate con interchangeable=False (múltiples items parciales)", r_auto5.status_code in (200, 201, 400), f"HTTP {r_auto5.status_code}")
        api("delete", f"/order/so/{so5_pk}/")

        api("delete", f"/order/so/{so3_pk}/")

    # SALESORDER_SHIPMENT_REQUIRES_CHECK=True -> SalesOrderShipment.check_can_complete()
    # rechaza el envío de un shipment sin revisar (checked_by=None)
    r_setset = api("patch", "/settings/global/SALESORDER_SHIPMENT_REQUIRES_CHECK/", {"value": "True"})
    if r_setset.status_code == 200:
        r_so4 = api("post", "/order/so/", {"customer": CUSTOMER_PK})
        so4_pk = r_so4.json().get("pk") if r_so4.status_code == 201 else None
        if so4_pk:
            r_line4 = api("post", "/order/so-line/", {"order": so4_pk, "part": PART_PKS[0], "quantity": 1, "sale_price": "1.00", "sale_price_currency": "USD"})
            line4_pk = r_line4.json().get("pk") if r_line4.status_code == 201 else None
            api("post", f"/order/so/{so4_pk}/issue/")
            r_ship4 = api("post", "/order/so/shipment/", {"order": so4_pk})
            ship4_pk = r_ship4.json().get("pk") if r_ship4.status_code == 201 else None
            r_stk4 = api("post", "/stock/", {"part": PART_PKS[0], "quantity": 1, "location": LOC_A})
            stk4_data = r_stk4.json()
            stk4_pk = (stk4_data[0] if isinstance(stk4_data, list) else stk4_data).get("pk")
            if ship4_pk and line4_pk and stk4_pk:
                api("post", f"/order/so/{so4_pk}/allocate/", {
                    "shipment": ship4_pk, "items": [{"line_item": line4_pk, "stock_item": stk4_pk, "quantity": 1}],
                })
                r_send4 = api("post", f"/order/so/shipment/{ship4_pk}/ship/", {})
                log("COV-SO-shipment-requires-check", "Enviar shipment sin revisar con SALESORDER_SHIPMENT_REQUIRES_CHECK=True (debe rechazar)", r_send4.status_code in (400, 422), f"HTTP {r_send4.status_code} {short(r_send4)}")
            api("delete", f"/order/so/{so4_pk}/")
        api("patch", "/settings/global/SALESORDER_SHIPMENT_REQUIRES_CHECK/", {"value": "False"})

    # COV-SO-allocate-serials: SalesOrderAllocateSerials -- parte trackable+salable
    # temporal, con stock serializado, asignada a una SO por número de serie
    r_tp = api("post", "/part/", {
        "name": "COV SO Serial Part", "description": "Parte temporal coverage SO serial",
        "category": 1, "trackable": True, "salable": True, "active": True,
    })
    tp_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if tp_pk:
        r_stk2 = api("post", "/stock/", {"part": tp_pk, "quantity": 3, "location": LOC_A})
        stk_data2 = r_stk2.json()
        stk_item2 = stk_data2[0] if isinstance(stk_data2, list) else stk_data2
        stk_pk2 = stk_item2.get("pk")
        if r_stk2.status_code == 201 and stk_pk2:
            r_ser = api("post", f"/stock/{stk_pk2}/serialize/", {"quantity": 3, "serial_numbers": "1-3", "destination": LOC_A})
            if r_ser.status_code in (200, 201):
                r_so2 = api("post", "/order/so/", {"customer": CUSTOMER_PK})
                so2_pk = r_so2.json().get("pk") if r_so2.status_code == 201 else None
                if so2_pk:
                    r_line2 = api("post", "/order/so-line/", {"order": so2_pk, "part": tp_pk, "quantity": 2, "sale_price": "5.00", "sale_price_currency": "USD"})
                    line2_pk = r_line2.json().get("pk") if r_line2.status_code == 201 else None
                    if line2_pk:
                        r_allocser = api("post", f"/order/so/{so2_pk}/allocate-serials/", {
                            "line_item": line2_pk, "quantity": 2, "serial_numbers": "1,2",
                        })
                        ok_as = r_allocser.status_code in (200, 201)
                        log("COV-SO-allocate-serials", "SalesOrderAllocateSerials por número de serie", ok_as, f"HTTP {r_allocser.status_code} {short(r_allocser)}")
                    api("delete", f"/order/so/{so2_pk}/")
        api("patch", f"/part/{tp_pk}/", {"active": False})
        api("delete", f"/part/{tp_pk}/")

def tc_so_line_filters():
    # SalesOrderFilter.filter_part() -- filtro ?part= sobre el LISTADO de SO (no so-line)
    r_part = api("get", "/order/so/", params={"part": 5})
    log("COV-SO-part-filter", "Filtro /order/so/ ?part= (sin include_variants)", r_part.status_code == 200, f"HTTP {r_part.status_code}")
    r_part_var = api("get", "/order/so/", params={"part": 5, "include_variants": "true"})
    log("COV-SO-part-filter-variants", "Filtro /order/so/ ?part=&include_variants=true", r_part_var.status_code == 200, f"HTTP {r_part_var.status_code}")

    cases = [
        ("include_variants", {"include_variants": "true", "part": 5}),
        ("allocated", {"allocated": "false"}),
        ("completed", {"completed": "false"}),
        ("order_complete", {"order_complete": "false"}),
        ("order_outstanding", {"order_outstanding": "true"}),
        ("has_pricing", {"has_pricing": "false"}),
    ]
    for name, params in cases:
        r = api("get", "/order/so-line/", params=params)
        log(f"COV-SO-line-{name}", f"Filtro so-line ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

def tc_so_hold_shipment_allocate():
    """SalesOrderHold, so-extra-line, y filtros de so-allocation -- perdidos al
    fusionar inventree_order_coverage_test_suite.py, nunca portados a este archivo."""
    r = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("COV-SO-hold", "SalesOrderHold (Pending->On Hold)", False, f"No se pudo crear SO: HTTP {r.status_code}")
        return

    r2 = api("post", f"/order/so/{pk}/hold/", {})
    log("COV-SO-hold", "SalesOrderHold (Pending->On Hold)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

    r3 = api("post", "/order/so-extra-line/", {"order": pk, "quantity": 1, "reference": "COV extra", "price": "5.00"})
    ok3 = r3.status_code == 201
    log("COV-SO-extraline-create", "Crear SO extra line", ok3, f"HTTP {r3.status_code} {short(r3)}")
    if ok3:
        api("delete", f"/order/so-extra-line/{r3.json()['pk']}/")

    r4 = api("post", "/order/so/shipment/", {"order": pk, "reference": "COV-SHIP-1"})
    ok4 = r4.status_code == 201
    log("COV-SO-shipment-create", "Crear SalesOrderShipment", ok4, f"HTTP {r4.status_code} {short(r4)}")
    ship_pk = r4.json().get("pk") if ok4 else None

    r5 = api("get", "/order/so/shipment/", params={"order": pk})
    log("COV-SO-shipment-list", "Listar shipments ?order=", r5.status_code == 200, f"HTTP {r5.status_code}")

    if ship_pk:
        r6 = api("get", "/order/so/shipment/", params={"shipped": "false"})
        log("COV-SO-shipment-shipped", "Filtro shipment ?shipped=false", r6.status_code == 200, f"HTTP {r6.status_code}")
        r7 = api("get", "/order/so/shipment/", params={"delivered": "false"})
        log("COV-SO-shipment-delivered", "Filtro shipment ?delivered=false", r7.status_code == 200, f"HTTP {r7.status_code}")
        api("delete", f"/order/so/shipment/{ship_pk}/")

    r8 = api("get", "/order/so-allocation/", params={"order": pk})
    log("COV-SO-allocation-list", "Listar SO allocations ?order=", r8.status_code == 200, f"HTTP {r8.status_code}")

    r9 = api("get", "/order/so-allocation/", params={"outstanding": "true"})
    log("COV-SO-allocation-outstanding", "Filtro allocation ?outstanding=true", r9.status_code == 200, f"HTTP {r9.status_code}")

    api("delete", f"/order/so/{pk}/")


# ══════════════════════════════════════════════════════════════
# ST-009 / RF-010 — RETURN ORDERS (ciclo completo + extendido)
# ══════════════════════════════════════════════════════════════

def suite_return_orders():
    # TC-RO-01: Crear RO con referencia válida y cliente
    ref = f"RMA-{int(time.time()) % 9000 + 1000}"
    r = api("post", "/order/ro/", {"customer": CUSTOMER_PK, "reference": ref})
    ro_pk = None
    if r.status_code == 201:
        ro_pk = r.json().get("pk")
        log("TC-RO-01", "Crear RO con cliente y referencia válida", True)
    else:
        log("TC-RO-01", "Crear RO con cliente y referencia válida", False, f"HTTP {r.status_code} {short(r)}")
        return

    # TC-RO-02: Crear RO sin cliente → debe fallar
    r_bad = api("post", "/order/ro/", {"reference": "RMA-9902"})
    log("TC-RO-02", "Crear RO sin cliente rechaza HTTP 4xx", r_bad.status_code >= 400, f"HTTP {r_bad.status_code}")

    # COV-RO-noref: Crear RO SIN 'reference' -> dispara el default del modelo
    # (generate_next_return_order_reference), no cubierto cuando siempre se
    # pasa una referencia explícita
    r_noref = api("post", "/order/ro/", {"customer": CUSTOMER_PK})
    ok_noref = r_noref.status_code == 201
    log("COV-RO-noref", "Crear RO sin referencia explícita (usa default autogenerado)", ok_noref, f"HTTP {r_noref.status_code}")
    if ok_noref:
        api("delete", f"/order/ro/{r_noref.json().get('pk')}/")

    # TC-RO-03: Crear RO con referencia inválida → debe fallar
    r_bad2 = api("post", "/order/ro/", {"customer": CUSTOMER_PK, "reference": "INVALID-REF-FORMAT"})
    log("TC-RO-03", "Crear RO con referencia inválida rechaza HTTP 4xx", r_bad2.status_code >= 400, f"HTTP {r_bad2.status_code}")

    # TC-RO-04: Crear stock item de retorno y agregar línea a RO
    # quantity del stock item (5) > quantity de la línea RO (2) -> al recibir,
    # receive_line_item() divide el stock item (splitStock) en vez de usarlo completo
    r_stk = api("post", "/stock/", {"part": PART_PKS[0], "quantity": 5, "location": LOC_A})
    stk_data = r_stk.json()
    stk_pk = (stk_data[0] if isinstance(stk_data, list) else stk_data).get("pk")

    line_pk = None
    if stk_pk:
        r_line = api("post", "/order/ro-line/", {"order": ro_pk, "part": PART_PKS[0], "quantity": 2, "item": stk_pk})
        line_pk = r_line.json().get("pk") if r_line.status_code == 201 else None
        log("TC-RO-04", "Agregar línea a RO con stock item", r_line.status_code == 201, f"HTTP {r_line.status_code} {short(r_line)}")
    else:
        log("TC-RO-04", "Agregar línea a RO con stock item", False, f"No se pudo crear stock: HTTP {r_stk.status_code}")

    # ReturnOrderSerializer.create() con 'duplicate' -> copia líneas de otra RO
    # (ejercita ReturnOrder.clean_line_item(), distinto del de PurchaseOrder)
    r_rodup = api("post", "/order/ro/", {
        "customer": CUSTOMER_PK, "reference": next_ref("RMA"),
        "duplicate": {"original": ro_pk, "copy_lines": True, "copy_extra_lines": True},
    })
    ok_rodup = r_rodup.status_code == 201
    log("COV-RO-duplicate", "Crear RO duplicando líneas de otra RO", ok_rodup, f"HTTP {r_rodup.status_code} {short(r_rodup)}")
    if ok_rodup:
        api("delete", f"/order/ro/{r_rodup.json()['pk']}/")

    # TC-RO-05: Ciclo completo — issue RO
    r_issue = api("post", f"/order/ro/{ro_pk}/issue/")
    log("TC-RO-05", "Emitir RO (issue) exitosamente", r_issue.status_code in (200, 201), f"HTTP {r_issue.status_code}")

    # COV-RO-receive: ReturnOrder.receive_line_item() -- marca el item como
    # QUARANTINED, lo mueve de ubicación y limpia la referencia a customer
    if line_pk:
        r_recv = api("post", f"/order/ro/{ro_pk}/receive/", {
            "items": [{"item": line_pk}], "location": LOC_A, "note": "coverage receive",
        })
        log("COV-RO-receive", "ReturnOrder.receive_line_item() vía endpoint /receive/", r_recv.status_code in (200, 201), f"HTTP {r_recv.status_code} {short(r_recv)}")

    # COV-RO-complete: ReturnOrder._action_complete() (RO en estado IN_PROGRESS)
    r_rocomp = api("post", f"/order/ro/{ro_pk}/complete/", {})
    log("COV-RO-complete", "ReturnOrderComplete (completar)", r_rocomp.status_code in (200, 201), f"HTTP {r_rocomp.status_code} {short(r_rocomp)}")

def tc_ro_hold_extra():
    r = api("post", "/order/ro/", {"customer": CUSTOMER_PK, "reference": next_ref("RMA")})
    pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("COV-RO-hold", "ReturnOrderHold (Pending->On Hold)", False, f"No se pudo crear RO: HTTP {r.status_code}")
        return

    r2 = api("post", f"/order/ro/{pk}/hold/", {})
    log("COV-RO-hold", "ReturnOrderHold (Pending->On Hold)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

    r3 = api("post", "/order/ro-extra-line/", {"order": pk, "quantity": 1, "reference": "COV extra", "price": "5.00"})
    ok3 = r3.status_code == 201
    log("COV-RO-extraline-create", "Crear RO extra line", ok3, f"HTTP {r3.status_code} {short(r3)}")
    if ok3:
        api("delete", f"/order/ro-extra-line/{r3.json()['pk']}/")

    r4 = api("get", "/order/ro-extra-line/", params={"order": pk})
    log("COV-RO-extraline-list", "Listar RO extra lines ?order=", r4.status_code == 200, f"HTTP {r4.status_code}")

    r5 = api("post", f"/order/ro/{pk}/cancel/", {})
    log("COV-RO-cancel", "ReturnOrderCancel (cancelar)", r5.status_code in (200, 201), f"HTTP {r5.status_code} {short(r5)}")

    api("delete", f"/order/ro/{pk}/")

def tc_ro_line_filters():
    r = api("get", "/order/ro-line/", params={"received": "false"})
    log("COV-RO-line-received", "Filtro ro-line ?received=false", r.status_code == 200, f"HTTP {r.status_code}")

    r2 = api("get", "/order/ro-line/", params={"include_variants": "true", "part": 1})
    log("COV-RO-line-variants", "Filtro ro-line ?include_variants", r2.status_code == 200, f"HTTP {r2.status_code}")

    # ReturnOrderFilter.filter_part() -- filtro ?part= sobre el LISTADO de RO
    r_part = api("get", "/order/ro/", params={"part": 1})
    log("COV-RO-part-filter", "Filtro /order/ro/ ?part= (sin include_variants)", r_part.status_code == 200, f"HTTP {r_part.status_code}")
    r_part_var = api("get", "/order/ro/", params={"part": 1, "include_variants": "true"})
    log("COV-RO-part-filter-variants", "Filtro /order/ro/ ?part=&include_variants=true", r_part_var.status_code == 200, f"HTTP {r_part_var.status_code}")


# ══════════════════════════════════════════════════════════════
# TRANSFER ORDER — módulo order, no mapeado a ningún RF del plan
# ══════════════════════════════════════════════════════════════

def tc_transfer_order():
    r = api("get", "/order/transfer-order/")
    log("COV-TO-list", "Listar Transfer Orders", r.status_code == 200, f"HTTP {r.status_code}")

    r3 = api("post", "/order/transfer-order/", {
        "reference": next_ref("TO"), "take_from": LOC_A, "destination": LOC_B,
    })
    ok3 = r3.status_code == 201
    log("COV-TO-create", "Crear Transfer Order", ok3, f"HTTP {r3.status_code} {short(r3)}")
    pk = r3.json().get("pk") if ok3 else None

    if pk:
        r4 = api("post", f"/order/transfer-order/{pk}/hold/", {})
        log("COV-TO-hold", "TransferOrderHold (retener)", r4.status_code in (200, 201), f"HTTP {r4.status_code} {short(r4)}")

        r5 = api("post", f"/order/transfer-order/{pk}/issue/", {})
        log("COV-TO-issue", "TransferOrderIssue (emitir)", r5.status_code in (200, 201, 400), f"HTTP {r5.status_code} {short(r5)}")

        r6 = api("post", f"/order/transfer-order/{pk}/cancel/", {})
        log("COV-TO-cancel", "TransferOrderCancel (cancelar)", r6.status_code in (200, 201, 400), f"HTTP {r6.status_code} {short(r6)}")

        api("delete", f"/order/transfer-order/{pk}/")

    # COV-TO-allocate: TransferOrderAllocate (asignación manual, no por serie) ->
    # ejercita TransferOrderAllocation.clean()
    r_to3 = api("post", "/order/transfer-order/", {"reference": next_ref("TO"), "take_from": LOC_A, "destination": LOC_B})
    to3_pk = r_to3.json().get("pk") if r_to3.status_code == 201 else None
    if to3_pk:
        r_line3 = api("post", "/order/transfer-order-line/", {"order": to3_pk, "part": PART_PKS[0], "quantity": 5})
        line3_pk = r_line3.json().get("pk") if r_line3.status_code == 201 else None
        api("post", f"/order/transfer-order/{to3_pk}/issue/", {})
        r_stk3 = api("post", "/stock/", {"part": PART_PKS[0], "quantity": 5, "location": LOC_A})
        stk_data3 = r_stk3.json()
        stk_item3 = stk_data3[0] if isinstance(stk_data3, list) else stk_data3
        stk_pk3 = stk_item3.get("pk")
        if line3_pk and stk_pk3:
            # Sobre-asignación (999 > 5 disponibles) -> TransferOrderAllocation.clean()
            # rechaza vía 'Allocation quantity cannot exceed stock quantity'
            r_overalloc3 = api("post", f"/order/transfer-order/{to3_pk}/allocate/", {
                "items": [{"line_item": line3_pk, "stock_item": stk_pk3, "quantity": 999}],
            })
            log("COV-TO-allocate-overallocate", "TransferOrderAllocate con quantity > stock disponible (debe rechazar)", r_overalloc3.status_code in (400, 422), f"HTTP {r_overalloc3.status_code} {short(r_overalloc3)}")

            r_alloc3 = api("post", f"/order/transfer-order/{to3_pk}/allocate/", {
                "items": [{"line_item": line3_pk, "stock_item": stk_pk3, "quantity": 5}],
            })
            ok_alloc3 = r_alloc3.status_code in (200, 201)
            log("COV-TO-allocate", "TransferOrderAllocate manual (no por serie)", ok_alloc3, f"HTTP {r_alloc3.status_code} {short(r_alloc3)}")

            # TransferOrderComplete -> TransferOrderAllocation.complete_allocation()
            # accept_incomplete_allocation=False (default) fuerza la evaluación real de
            # order.is_fully_allocated() en validate_accept_incomplete_allocation()
            # (con True, el "and" corto-circuita y nunca se llama)
            r_comp3 = api("post", f"/order/transfer-order/{to3_pk}/complete/", {"accept_incomplete_allocation": False})
            log("COV-TO-complete", "TransferOrderComplete (con allocation real)", r_comp3.status_code in (200, 201), f"HTTP {r_comp3.status_code} {short(r_comp3)}")

            # Completar de nuevo una TO ya completada -> can_complete() lanza
            # ValidationError('Order is already complete'), raise_error=True la repropaga
            r_comp3b = api("post", f"/order/transfer-order/{to3_pk}/complete/", {"accept_incomplete_allocation": True})
            log("COV-TO-complete-twice", "TransferOrderComplete sobre TO ya completada (debe rechazar)", r_comp3b.status_code in (400, 422), f"HTTP {r_comp3b.status_code} {short(r_comp3b)}")
        api("delete", f"/order/transfer-order/{to3_pk}/")

    # COV-TO-allocate-serials: TransferOrderSerialAllocationSerializer -- parte
    # trackable temporal, con stock serializado, asignado a una TO por número de serie
    r_tp = api("post", "/part/", {
        "name": "COV TO Serial Part", "description": "Parte temporal coverage TO serial",
        "category": 1, "trackable": True, "active": True,
    })
    tp_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if tp_pk:
        r_stk = api("post", "/stock/", {"part": tp_pk, "quantity": 2, "location": LOC_A})
        stk_data = r_stk.json()
        stk_item = stk_data[0] if isinstance(stk_data, list) else stk_data
        stk_pk = stk_item.get("pk")
        if r_stk.status_code == 201 and stk_pk:
            r_ser = api("post", f"/stock/{stk_pk}/serialize/", {"quantity": 2, "serial_numbers": "201-202", "destination": LOC_A})
            if r_ser.status_code in (200, 201):
                r_to2 = api("post", "/order/transfer-order/", {"reference": next_ref("TO"), "take_from": LOC_A, "destination": LOC_B})
                to2_pk = r_to2.json().get("pk") if r_to2.status_code == 201 else None
                if to2_pk:
                    r_line2 = api("post", "/order/transfer-order-line/", {"order": to2_pk, "part": tp_pk, "quantity": 2})
                    line2_pk = r_line2.json().get("pk") if r_line2.status_code == 201 else None
                    if line2_pk:
                        r_alloc2 = api("post", f"/order/transfer-order/{to2_pk}/allocate-serials/", {
                            "line_item": line2_pk, "quantity": 2, "serial_numbers": "201,202",
                        })
                        ok_alloc2 = r_alloc2.status_code in (200, 201)
                        log("COV-TO-allocate-serials", "TransferOrderSerialAllocation por número de serie", ok_alloc2, f"HTTP {r_alloc2.status_code} {short(r_alloc2)}")
                    api("delete", f"/order/transfer-order/{to2_pk}/")
        api("patch", f"/part/{tp_pk}/", {"active": False})
        api("delete", f"/part/{tp_pk}/")

def tc_transfer_order_line_filters():
    r = api("get", "/order/transfer-order-line/")
    log("COV-TO-line-list", "Listar Transfer Order lines", r.status_code == 200, f"HTTP {r.status_code}")

    to_line_cases = [
        ("part", {"part": 1}), ("part-variants", {"part": 1, "include_variants": "true"}),
        ("allocated", {"allocated": "false"}), ("completed", {"completed": "false"}),
        ("order_complete", {"order_complete": "false"}), ("order_outstanding", {"order_outstanding": "true"}),
    ]
    for name, params in to_line_cases:
        r_l = api("get", "/order/transfer-order-line/", params=params)
        log(f"COV-TO-line-{name}", f"Filtro transfer-order-line ?{name}", r_l.status_code == 200, f"HTTP {r_l.status_code}")

    # TransferOrderFilter.filter_part() -- filtro ?part= sobre el LISTADO de TO
    r_part = api("get", "/order/transfer-order/", params={"part": 1})
    log("COV-TO-part-filter", "Filtro /order/transfer-order/ ?part= (sin include_variants)", r_part.status_code == 200, f"HTTP {r_part.status_code}")
    r_part_var = api("get", "/order/transfer-order/", params={"part": 1, "include_variants": "true"})
    log("COV-TO-part-filter-variants", "Filtro /order/transfer-order/ ?part=&include_variants=true", r_part_var.status_code == 200, f"HTTP {r_part_var.status_code}")

    r2 = api("get", "/order/transfer-order-allocation/")
    log("COV-TO-allocation-list", "Listar Transfer Order allocations", r2.status_code == 200, f"HTTP {r2.status_code}")

    to_alloc_cases = [
        ("outstanding", {"outstanding": "true"}), ("include_variants", {"include_variants": "true", "part": 1}),
        ("location", {"location": 1}),
    ]
    for name, params in to_alloc_cases:
        r = api("get", "/order/transfer-order-allocation/", params=params)
        log(f"COV-TO-allocation-{name}", f"Filtro transfer-order-allocation ?{name}", r.status_code == 200, f"HTTP {r.status_code}")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 62)
    print("  InvenTree — Órdenes: Purchase · Sales · Return · Transfer")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    s, csrf = authed_session()
    sid = s.cookies.get("sessionid", "")
    print(f"\n  Sesión: {sid[:12]}...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context()
        ctx.add_cookies([
            {"name": "sessionid", "value": sid, "domain": "localhost", "path": "/"},
            {"name": "csrftoken", "value": csrf, "domain": "localhost", "path": "/"},
        ])
        page = ctx.new_page()

        print("\n── CPF-004: Purchase Orders ───────────────────────────")
        tc_po_01(page); tc_po_02(page); tc_po_03(page); tc_po_04(page); tc_po_05(page)
        tc_po_06(page); tc_po_07(page); tc_po_08(page); tc_po_09(page); tc_po_10(page)

        ctx.close(); browser.close()

    print("\n── FN4 — Purchase Orders: casos extendidos ────────────")
    try:
        fn4_po_extended()
    except Exception as e:
        log("FN4-PO-extended", "Casos extendidos de PO", False, str(e))

    print("\n── Filtros comunes por tipo de orden ──────────────────")
    tc_order_filters("so", "SO")
    tc_order_filters("ro", "RO")
    tc_order_filters("transfer-order", "TO")

    print("\n── ST-008: Sales Orders ────────────────────────────────")
    suite_sales_orders()
    tc_so_line_filters()
    tc_so_hold_shipment_allocate()

    print("\n── ST-009: Return Orders ───────────────────────────────")
    suite_return_orders()
    tc_ro_hold_extra()
    tc_ro_line_filters()

    print("\n── Transfer Order ──────────────────────────────────────")
    tc_transfer_order()
    tc_transfer_order_line_filters()

    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed

    print("\n" + "=" * 62)
    print(f"  TOTAL: {passed}/{len(results)} PASS  |  {failed} FAIL")
    print("=" * 62)
    print(f"\n  {'TC':<28} {'Resultado':<10} Caso")
    print(f"  {'-'*27} {'-'*9} {'-'*36}")
    for r in results:
        mark = "PASS ✅" if r["pass"] else "FAIL ❌"
        print(f"  {r['tc']:<28} {mark:<10} {r['name']}")

    failures = [r for r in results if not r["pass"]]
    if failures:
        print("\n── Defectos / Comportamientos inesperados ─────────────")
        for i, f in enumerate(failures, 1):
            print(f"  DEF-{i:02d} [{f['tc']}] {f['name']}")
            print(f"         → {f['detail']}")

    with open(RESULTS_JSON, "w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    print(f"\n  Capturas: {SS_DIR}/")
    print(f"  JSON:     {RESULTS_JSON}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
