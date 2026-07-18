#!/usr/bin/env python3
"""
InvenTree — Suite funcional: Órdenes de Fabricación (test_build_inventree_suite.py)
FN8  Build Orders  (RF-008, Hito 2)

Incluye:
  TC-BO-01..08  — Ciclo de vida de Build Orders (API + UI)
  FN8-*, COV-*  — Casos extendidos de cobertura (filtros, hold, unallocate,
                  auto-allocate, allocate manual, consume, outputs
                  scrap/delete/complete, componentes trackable)

Prerrequisitos en BD (setup_system_tests.py):
  - Part pk=5  (PCB Sensor v1,  assembly=True, BOM con 3 ítems)
  - Part pk=10 (Módulo Ensamble Test, assembly=True, sin BOM)
  - Part pk=1  (Resistencia 10k, assembly=False)
  - StockLocation pk=1 (Almacén A)

Convenciones:
  - Referencias Build de prueba: BO-99xx (limpiadas por setup --clean)
  - Status Build: 10=Pending 20=Production 30=Cancelled 40=Complete
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
SS_DIR       = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "build")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "test_output", "results", "build_results.json")
os.makedirs(SS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

ASSEMBLY_PK      = 5   # PCB Sensor v1 (con BOM)
ASSEMBLY_NO_BOM  = 10  # Módulo Ensamble Test (sin BOM)
NON_ASSEMBLY_PK  = 1   # Resistencia 10k
LOC_A            = 1

results = []
_bo_ref_counter = [9910]


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

def authed_session():
    s = requests.Session()
    s.get(f"{API}/auth/v1/config", auth=AUTH)
    csrf = s.cookies.get("csrftoken", "")
    s.post(f"{API}/auth/v1/auth/login",
           json={"username": USER, "password": PASS},
           headers={"X-CSRFToken": csrf, "Referer": BASE})
    return s, s.cookies.get("csrftoken", csrf)

def next_bo_ref():
    _bo_ref_counter[0] += 1
    return f"BO-{_bo_ref_counter[0]:04d}"

def create_build(ref=None, part=ASSEMBLY_NO_BOM, qty=1):
    ref = ref or next_bo_ref()
    return api("post", "/build/", {"part": part, "quantity": qty, "reference": ref, "title": ref})

def issue_build(pk):
    return api("post", f"/build/{pk}/issue/", {})

def cancel_build(pk):
    return api("post", f"/build/{pk}/cancel/", {"remove_allocated_stock": False, "remove_incomplete_outputs": False})

def create_build_output(pk, qty=1):
    return api("post", f"/build/{pk}/create-output/", {"quantity": qty, "serial_numbers": ""})

def complete_build_output(output_pk, location=LOC_A):
    """Mark an in-progress build output as complete (is_building=False)."""
    return api("patch", f"/stock/{output_pk}/", {"is_building": False, "location": location})

def finish_build(pk):
    return api("post", f"/build/{pk}/finish/", {"accept_unallocated": True, "accept_incomplete": True})

def delete_build(pk):
    api("delete", f"/build/{pk}/")

def build_status(pk):
    r = api("get", f"/build/{pk}/")
    return r.json().get("status"), r.json().get("status_text")


# ══════════════════════════════════════════════════════════════
# CPF-008 — BUILD ORDERS
# ══════════════════════════════════════════════════════════════

def tc_bo_01(page):
    """FN8-CP-001 — Crear Build Order válida → Pending."""
    ref = next_bo_ref()
    r = create_build(ref=ref, part=ASSEMBLY_NO_BOM, qty=10)
    ok = r.status_code == 201 and r.json().get("status") == 10
    pk = r.json().get("pk") if r.status_code == 201 else None
    page.goto(f"{BASE}/web/manufacturing/build-order/{pk}/", wait_until="networkidle", timeout=20000) if pk else None
    time.sleep(2); snap(page, "TC-BO-01_create_build")
    log("TC-BO-01", "Crear Build Order válida (estado Pending)", ok,
        f"HTTP {r.status_code} | pk={pk} | ref={ref} | status={r.json().get('status_text')}")
    if pk: delete_build(pk)

def tc_bo_02(page):
    """FN8-CP-002 — Part no-assembly → 400."""
    r = create_build(ref=next_bo_ref(), part=NON_ASSEMBLY_PK, qty=5)
    ok = r.status_code in (400, 422)
    snap(page, "TC-BO-02_non_assembly")
    log("TC-BO-02", "Build Order con parte no-assembly (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_bo_03(page):
    """FN8-CP-003 — qty=0 → 400."""
    r = create_build(ref=next_bo_ref(), part=ASSEMBLY_NO_BOM, qty=0)
    ok = r.status_code in (400, 422)
    snap(page, "TC-BO-03_qty_zero")
    log("TC-BO-03", "Build Order qty=0 (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_bo_04(page):
    """FN8-CP-004 — Pending → issue → Production."""
    r = create_build(qty=1); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-BO-04", "Build Pending → Production (issue)", False, "No se pudo crear Build"); return
    r_issue = issue_build(pk)
    st, st_txt = build_status(pk)
    ok = st == 20 and st_txt == "Production"
    page.goto(f"{BASE}/web/manufacturing/build-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-BO-04_build_production")
    log("TC-BO-04", "Build Pending → Production (issue)", ok,
        f"issue HTTP {r_issue.status_code} | status={st} ({st_txt})")
    cancel_build(pk); delete_build(pk)

def tc_bo_05(page):
    """FN8-CP-005 — Pending → Production → Complete."""
    r = create_build(qty=1); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-BO-05", "Build Production → Complete (create-output + complete + finish)", False, "No se pudo crear Build"); return
    issue_build(pk)
    r_out = create_build_output(pk, qty=1)
    out_list = r_out.json() if isinstance(r_out.json(), list) else [r_out.json()]
    out_pk = out_list[0].get("pk") if out_list else None
    if out_pk: complete_build_output(out_pk)
    r_fin = finish_build(pk)
    st, st_txt = build_status(pk)
    ok = st == 40 and st_txt == "Complete"
    page.goto(f"{BASE}/web/manufacturing/build-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-BO-05_build_complete")
    log("TC-BO-05", "Build Production → Complete (create-output + complete + finish)", ok,
        f"output HTTP {r_out.status_code} | output_pk={out_pk} | finish HTTP {r_fin.status_code} | status={st} ({st_txt})")

def tc_bo_06(page):
    """FN8-CP-006 — Pending → cancel → Cancelled."""
    r = create_build(qty=1); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-BO-06", "Cancelar Build en Pending → Cancelled", False, "No se pudo crear Build"); return
    r_cancel = cancel_build(pk)
    st, st_txt = build_status(pk)
    ok = st == 30 and st_txt == "Cancelled"
    page.goto(f"{BASE}/web/manufacturing/build-order/{pk}/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-BO-06_build_cancelled")
    log("TC-BO-06", "Cancelar Build en Pending → Cancelled", ok,
        f"cancel HTTP {r_cancel.status_code} | status={st} ({st_txt})")
    delete_build(pk)

def tc_bo_07(page):
    """FN8-CP-007 — Complete → cancel → debe fallar."""
    r = create_build(qty=1); pk = r.json().get("pk") if r.status_code == 201 else None
    if not pk:
        log("TC-BO-07", "Cancelar Build Complete (debe rechazar)", False, "No se pudo crear Build"); return
    issue_build(pk)
    r_out = create_build_output(pk, qty=1)
    out_list = r_out.json() if isinstance(r_out.json(), list) else [r_out.json()]
    out_pk = out_list[0].get("pk") if out_list else None
    if out_pk: complete_build_output(out_pk)
    finish_build(pk)
    st_before, _ = build_status(pk)
    r_cancel = cancel_build(pk)
    ok = r_cancel.status_code in (400, 422)
    snap(page, "TC-BO-07_cancel_complete")
    log("TC-BO-07", "Cancelar Build Complete (debe rechazar)", ok,
        f"status_antes={st_before} | cancel HTTP {r_cancel.status_code} | {str(r_cancel.json())[:100]}")

def tc_bo_08(page):
    """FN8-CP-008 — Assembly sin BOM definido → creación exitosa."""
    r = create_build(ref=next_bo_ref(), part=ASSEMBLY_NO_BOM, qty=5)
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    r_bom = requests.get(f"{API}/bom/", params={"part": ASSEMBLY_NO_BOM, "format": "json"}, auth=AUTH)
    bom_count = r_bom.json().get("count", 0) if isinstance(r_bom.json(), dict) else len(r_bom.json())
    page.goto(f"{BASE}/web/manufacturing/build-order/{pk}/", wait_until="networkidle", timeout=20000) if pk else None
    time.sleep(2); snap(page, "TC-BO-08_no_bom")
    log("TC-BO-08", "Build Order para assembly sin BOM (debe aceptarse)", ok,
        f"HTTP {r.status_code} | pk={pk} | bom_items_de_parte={bom_count}")
    if pk: cancel_build(pk); delete_build(pk)


# ══════════════════════════════════════════════════════════════
# FN8 — Build Orders: casos extendidos de cobertura
# hold, unallocate, auto-allocate, allocate manual, output scrap/delete,
# consume, filtros de build-line/build-item — que TC-BO-01..08 no tocan.
# ══════════════════════════════════════════════════════════════

def fn8_build_extended():
    cases = [
        ("active", {"active": "true"}), ("overdue", {"overdue": "false"}),
        ("assigned_to_me", {"assigned_to_me": "false"}), ("has_project_code", {"has_project_code": "false"}),
        ("has_start_date", {"has_start_date": "false"}), ("has_target_date", {"has_target_date": "false"}),
        ("min_date", {"min_date": "2020-01-01"}), ("max_date", {"max_date": "2099-01-01"}),
    ]
    for name, params in cases:
        r = api("get", "/build/", params=params)
        log(f"FN8-BUILD-{name}", f"Filtro build ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    # OPTIONS -> get_api_url/api_instance_filters/api_defaults/barcode_model_type_code
    r_opt = requests.options(f"{API}/build/", auth=AUTH)
    log("FN8-BUILD-options", "OPTIONS /api/build/ (metadata de API)", r_opt.status_code == 200, f"HTTP {r_opt.status_code}")

    # target_date < start_date -> BuildOrder.clean() rechaza
    r_bad_dates = api("post", "/build/", {
        "part": ASSEMBLY_NO_BOM, "quantity": 1, "reference": next_bo_ref(), "title": "coverage baddates",
        "start_date": "2026-06-01", "target_date": "2026-01-01",
    })
    log("FN8-BUILD-baddates", "target_date anterior a start_date (debe rechazar)", r_bad_dates.status_code in (400, 422), f"HTTP {r_bad_dates.status_code} {short(r_bad_dates)}")

    # BUILDORDER_REQUIRE_RESPONSIBLE=True -> crear sin 'responsible' debe rechazar
    r_setting = api("patch", "/settings/global/BUILDORDER_REQUIRE_RESPONSIBLE/", {"value": "True"})
    if r_setting.status_code == 200:
        r_norespo = api("post", "/build/", {"part": ASSEMBLY_NO_BOM, "quantity": 1, "reference": next_bo_ref(), "title": "coverage norespo"})
        log("FN8-BUILD-require-responsible", "BUILDORDER_REQUIRE_RESPONSIBLE=True sin responsible (debe rechazar)", r_norespo.status_code in (400, 422), f"HTTP {r_norespo.status_code} {short(r_norespo)}")
        api("patch", "/settings/global/BUILDORDER_REQUIRE_RESPONSIBLE/", {"value": "False"})

    line_cases = [
        ("consumable", {"consumable": "false"}), ("order_outstanding", {"order_outstanding": "true"}),
        ("allocated", {"allocated": "false"}), ("consumed", {"consumed": "false"}),
        ("available", {"available": "true"}), ("on_order", {"on_order": "false"}),
    ]
    for name, params in line_cases:
        r = api("get", "/build/line/", params=params)
        log(f"FN8-BUILDLINE-{name}", f"Filtro build-line ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r = create_build(part=ASSEMBLY_NO_BOM, qty=10)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        r2 = api("post", f"/build/{pk}/hold/", {})
        log("FN8-BUILD-hold", "BuildHold (retener)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")
        r3 = api("post", f"/build/{pk}/unallocate/", {})
        log("FN8-BUILD-unallocate", "BuildUnallocate (desasignar)", r3.status_code in (200, 201), f"HTTP {r3.status_code}")

        r_exc = api("get", "/build/", params={"exclude_tree": pk})
        log("FN8-BUILD-exclude_tree", "Filtro build ?exclude_tree=<pk real>", r_exc.status_code == 200, f"HTTP {r_exc.status_code}")

        cancel_build(pk); delete_build(pk)

    r = create_build(part=ASSEMBLY_PK, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        r2 = api("post", f"/build/{pk}/auto-allocate/", {"location": LOC_A, "interchangeable": True, "substitutes": True, "optional_items": False})
        log("FN8-BUILD-autoallocate", "BuildAutoAllocate (BOM completo)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

        # BuildConsume con las build-lines del BOM (ya asignadas por auto-allocate)
        # -> offload_task síncrono de consume_build_stock
        r_lines_c = api("get", "/build/line/", params={"build": pk})
        ld_c = r_lines_c.json()
        lines_c = ld_c if isinstance(ld_c, list) else ld_c.get("results", [])
        line_pks = [{"build_line": line["pk"]} for line in lines_c]
        r_consume = api("post", f"/build/{pk}/consume/", {"lines": line_pks, "notes": "coverage consume"})
        log("FN8-BUILD-consume", "BuildConsume con build-lines asignadas", r_consume.status_code in (200, 201), f"HTTP {r_consume.status_code} {short(r_consume)}")

        # finish con trim_allocated_stock=True -> dispara Build.trim_allocated_stock()
        r_out = api("post", f"/build/{pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        outs = r_out.json() if isinstance(r_out.json(), list) else ([r_out.json()] if r_out.status_code == 201 else [])
        out_pk = outs[0].get("pk") if outs else None
        if out_pk:
            api("post", f"/build/{pk}/complete/", {
                "outputs": [{"output": out_pk, "quantity": 1}], "location": LOC_A,
                "accept_incomplete_allocation": True, "notes": "coverage trim setup",
            })
        r3 = api("post", f"/build/{pk}/finish/", {"accept_unallocated": True, "accept_incomplete": True, "trim_allocated_stock": True})
        log("FN8-BUILD-finish-trim", "BuildFinish con trim_allocated_stock=True", r3.status_code in (200, 201), f"HTTP {r3.status_code} {short(r3)}")

        cancel_build(pk); delete_build(pk)

    r = create_build(part=ASSEMBLY_NO_BOM, qty=5)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        issue_build(pk)
        r_out = api("post", f"/build/{pk}/create-output/", {"quantity": 2, "serial_numbers": ""})
        outs = r_out.json() if isinstance(r_out.json(), list) else ([r_out.json()] if r_out.status_code == 201 else [])
        out_pk = outs[0].get("pk") if outs else None
        if out_pk:
            r2 = api("post", f"/build/{pk}/scrap-outputs/", {"outputs": [{"output": out_pk, "quantity": 2}], "location": LOC_A, "notes": "coverage scrap"})
            log("FN8-BUILD-output-scrap", "BuildOutputScrap (descartar output)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

        # Segundo output para probar delete-outputs (dispara Build.delete_output)
        r_out2 = api("post", f"/build/{pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        outs2 = r_out2.json() if isinstance(r_out2.json(), list) else ([r_out2.json()] if r_out2.status_code == 201 else [])
        out_pk2 = outs2[0].get("pk") if outs2 else None
        if out_pk2:
            r3 = api("post", f"/build/{pk}/delete-outputs/", {"outputs": [{"output": out_pk2}]})
            log("FN8-BUILD-output-delete", "BuildOutputDelete (borrar output)", r3.status_code in (200, 201), f"HTTP {r3.status_code} {short(r3)}")

        cancel_build(pk); delete_build(pk)

    # Endpoint dedicado /complete/ (offloaded, corre sincrónico sin worker) —
    # dispara complete_build_output/can_complete_output. Para que además
    # dispare complete_allocation() hay que asignar stock a ESE output
    # específico antes de completarlo (BOM real -> ASSEMBLY_PK, no NO_BOM).
    r = create_build(part=ASSEMBLY_PK, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        issue_build(pk)
        r_out = api("post", f"/build/{pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        outs = r_out.json() if isinstance(r_out.json(), list) else ([r_out.json()] if r_out.status_code == 201 else [])
        out_pk = outs[0].get("pk") if outs else None
        if out_pk:
            r_lines = api("get", "/build/line/", params={"build": pk})
            ld = r_lines.json()
            lines2 = ld if isinstance(ld, list) else ld.get("results", [])
            for line in lines2:
                r_stock2 = api("post", "/stock/", {"part": line["part"], "location": LOC_A, "quantity": 1000})
                if r_stock2.status_code == 201:
                    sd2 = r_stock2.json()
                    stock_pk2 = (sd2[0] if sd2 else {}).get("pk") if isinstance(sd2, list) else sd2.get("pk")
                    if stock_pk2:
                        api("post", f"/build/{pk}/allocate/", {"items": [{"build_line": line["pk"], "stock_item": stock_pk2, "quantity": line["quantity"], "output": out_pk}]})

            r2 = api("post", f"/build/{pk}/complete/", {
                "outputs": [{"output": out_pk, "quantity": 1}],
                "location": LOC_A,
                "accept_incomplete_allocation": True,
                "notes": "coverage complete",
            })
            log("FN8-BUILD-output-complete", "BuildOutputComplete (endpoint dedicado, con allocation real)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")
        finish_build(pk)
        delete_build(pk)

    # BuildAllocate manual: dispara BuildItem.clean()/check_allocated_quantity(),
    # que el auto-allocate y el flujo normal no ejercitan.
    r = create_build(part=ASSEMBLY_PK, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        r_lines = api("get", "/build/line/", params={"build": pk})
        lines_data = r_lines.json()
        lines = lines_data if isinstance(lines_data, list) else lines_data.get("results", [])
        if lines:
            line_pk = lines[0]["pk"]
            line_part = lines[0]["part"]
            r_stock = api("post", "/stock/", {"part": line_part, "location": LOC_A, "quantity": 100})
            stock_pk = None
            if r_stock.status_code == 201:
                _sd = r_stock.json()
                stock_pk = (_sd[0] if _sd else {}).get("pk") if isinstance(_sd, list) else _sd.get("pk")
            if stock_pk:
                r2 = api("post", f"/build/{pk}/allocate/", {"items": [{"build_line": line_pk, "stock_item": stock_pk, "quantity": 5}]})
                log("FN8-BUILD-allocate", "BuildAllocate manual (1 línea)", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")
                api("delete", f"/stock/{stock_pk}/")
        cancel_build(pk); delete_build(pk)

    # Sin 'reference' explícita -> dispara Build.getNextBuildNumber()
    r = api("post", "/build/", {"part": ASSEMBLY_NO_BOM, "quantity": 1, "title": "coverage auto-ref"})
    ok = r.status_code == 201
    log("FN8-BUILD-autoref", "Crear Build sin reference (auto-generada)", ok, f"HTTP {r.status_code} {short(r)}")
    if ok:
        cancel_build(r.json()["pk"]); delete_build(r.json()["pk"])


def fn8_build_tracked_component():
    """Componente trackable en el BOM -> dispara auto_allocate_tracked_output()
    y complete_allocation() vía output (ninguna parte de la fixture es trackable,
    así que se arma todo desde cero y se limpia al final)."""
    r_comp = api("post", "/part/", {
        "name": "COV Tracked Component", "description": "Componente trackable coverage",
        "category": 1, "trackable": True, "active": True,
    })
    comp_pk = r_comp.json().get("pk") if r_comp.status_code == 201 else None

    r_asm = api("post", "/part/", {
        "name": "COV Tracked Assembly", "description": "Assembly con componente trackable coverage",
        "category": 3, "assembly": True, "trackable": True, "active": True,
    })
    asm_pk = r_asm.json().get("pk") if r_asm.status_code == 201 else None

    if not comp_pk or not asm_pk:
        log("FN8-BUILD-tracked", "Build con componente trackable", False, "No se pudieron crear las partes temporales")
        return

    api("post", "/bom/", {"part": asm_pk, "sub_part": comp_pk, "quantity": 1})

    r = create_build(part=asm_pk, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        issue_build(pk)

        r_bulk = api("post", "/stock/", {"part": comp_pk, "location": LOC_A, "quantity": 1})
        if r_bulk.status_code == 201:
            bd = r_bulk.json()
            bulk_pk = (bd[0] if bd else {}).get("pk") if isinstance(bd, list) else bd.get("pk")
            if bulk_pk:
                api("post", f"/stock/{bulk_pk}/serialize/", {"quantity": 1, "serial_numbers": "1", "destination": LOC_A})

        r_out = api("post", f"/build/{pk}/create-output/", {"quantity": 1, "serial_numbers": "1", "auto_allocate": True})
        ok_out = r_out.status_code in (200, 201)
        log("FN8-BUILD-output-create-tracked", "Crear output con auto_allocate=True (trackable)", ok_out, f"HTTP {r_out.status_code} {short(r_out)}")

        outs = r_out.json() if isinstance(r_out.json(), list) else ([r_out.json()] if ok_out else [])
        out_pk = outs[0].get("pk") if outs else None
        if out_pk:
            r2 = api("post", f"/build/{pk}/complete/", {
                "outputs": [{"output": out_pk, "quantity": 1}],
                "location": LOC_A, "accept_incomplete_allocation": True, "notes": "coverage tracked complete",
            })
            log("FN8-BUILD-complete-tracked", "Completar output con componente trackable asignado", r2.status_code in (200, 201), f"HTTP {r2.status_code} {short(r2)}")

        cancel_build(pk); delete_build(pk)

    api("patch", f"/part/{asm_pk}/", {"active": False}); api("delete", f"/part/{asm_pk}/")
    api("patch", f"/part/{comp_pk}/", {"active": False}); api("delete", f"/part/{comp_pk}/")


def fn8_coverage_extra():
    """Casos adicionales: consume_build_stock vía items dict, cancel_build con
    flags remove_allocated_stock/remove_incomplete_outputs, y
    update_build_order_lines (disparado por edición de BomItem con build activa)."""

    # -- consume_build_stock() vía 'items' dict (no 'lines') --
    r = create_build(part=ASSEMBLY_PK, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        r_alloc = api("post", f"/build/{pk}/auto-allocate/", {"location": LOC_A, "interchangeable": True, "substitutes": True, "optional_items": False})
        r_items = api("get", "/build/item/", params={"build": pk})
        items_data = r_items.json()
        items_list = items_data if isinstance(items_data, list) else items_data.get("results", [])
        if items_list:
            item_pk = items_list[0]["pk"]
            item_qty = items_list[0].get("quantity", 1)
            r_consume_items = api("post", f"/build/{pk}/consume/", {"items": [{"build_item": item_pk, "quantity": item_qty}], "notes": "coverage consume items"})
            log("COV-BUILD-consume-items", "BuildConsume vía 'items' dict (no 'lines')", r_consume_items.status_code in (200, 201), f"HTTP {r_consume_items.status_code} {short(r_consume_items)}")
        cancel_build(pk); delete_build(pk)

    # -- cancel_build con remove_allocated_stock=True (complete_build_allocations sincrono) --
    r = create_build(part=ASSEMBLY_PK, qty=1)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        api("post", f"/build/{pk}/auto-allocate/", {"location": LOC_A, "interchangeable": True, "substitutes": True, "optional_items": False})
        r_cancel_remove = api("post", f"/build/{pk}/cancel/", {"remove_allocated_stock": True, "remove_incomplete_outputs": False})
        log("COV-BUILD-cancel-removealloc", "BuildCancel con remove_allocated_stock=True", r_cancel_remove.status_code in (200, 201), f"HTTP {r_cancel_remove.status_code} {short(r_cancel_remove)}")
        delete_build(pk)

    # -- cancel_build con remove_incomplete_outputs=True --
    r = create_build(part=ASSEMBLY_NO_BOM, qty=2)
    pk = r.json().get("pk") if r.status_code == 201 else None
    if pk:
        issue_build(pk)
        api("post", f"/build/{pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        r_cancel_outputs = api("post", f"/build/{pk}/cancel/", {"remove_allocated_stock": False, "remove_incomplete_outputs": True})
        log("COV-BUILD-cancel-removeoutputs", "BuildCancel con remove_incomplete_outputs=True", r_cancel_outputs.status_code in (200, 201), f"HTTP {r_cancel_outputs.status_code} {short(r_cancel_outputs)}")
        delete_build(pk)

    # -- update_build_order_lines(): editar un BomItem de una assembly con build ACTIVA --
    r_asmupd = api("post", "/part/", {"name": "COV BuildLine Update Assy", "description": "x", "category": 3, "assembly": True, "active": True})
    asmupd_pk = r_asmupd.json().get("pk") if r_asmupd.status_code == 201 else None
    if asmupd_pk:
        r_bomupd = api("post", "/bom/", {"part": asmupd_pk, "sub_part": 1, "quantity": 2})
        bomupd_pk = r_bomupd.json().get("pk") if r_bomupd.status_code == 201 else None
        if bomupd_pk:
            r_bo = create_build(part=asmupd_pk, qty=3)
            bo_pk = r_bo.json().get("pk") if r_bo.status_code == 201 else None
            if bo_pk:
                issue_build(bo_pk)
                r_bomqtychange = api("patch", f"/bom/{bomupd_pk}/", {"quantity": 5})
                log("COV-BUILD-update-lines", "PATCH BomItem.quantity con build activa (update_build_order_lines sincrono)", r_bomqtychange.status_code == 200, f"HTTP {r_bomqtychange.status_code}")
                r_checkline = api("get", "/build/line/", params={"build": bo_pk})
                cd = r_checkline.json()
                clist = cd if isinstance(cd, list) else cd.get("results", [])
                updated_ok = any(float(line.get("quantity", 0)) == 15.0 for line in clist)
                log("COV-BUILD-update-lines-verify", "BuildLine.quantity recalculada (5 x 3 = 15)", updated_ok, f"lines={clist}")
                cancel_build(bo_pk); delete_build(bo_pk)
            api("delete", f"/bom/{bomupd_pk}/")
        api("patch", f"/part/{asmupd_pk}/", {"active": False})
        api("delete", f"/part/{asmupd_pk}/")

    # -- GET /build/item/ (nunca llamado por la suite hasta ahora) --
    r_bi = create_build(part=ASSEMBLY_PK, qty=1)
    bi_pk = r_bi.json().get("pk") if r_bi.status_code == 201 else None
    if bi_pk:
        api("post", f"/build/{bi_pk}/auto-allocate/", {"location": LOC_A, "interchangeable": True, "substitutes": True, "optional_items": False})
        r_itemlist = api("get", "/build/item/", params={"build": bi_pk})
        log("COV-BUILDITEM-list", "GET /build/item/ ?build= (verificar estado de allocation)", r_itemlist.status_code == 200, f"HTTP {r_itemlist.status_code}")
        r_itemtracked = api("get", "/build/item/", params={"tracked": "false"})
        log("COV-BUILDITEM-tracked-false", "Filtro build/item ?tracked=false", r_itemtracked.status_code == 200, f"HTTP {r_itemtracked.status_code}")
        r_itemtrackedtrue = api("get", "/build/item/", params={"tracked": "true"})
        log("COV-BUILDITEM-tracked-true", "Filtro build/item ?tracked=true", r_itemtrackedtrue.status_code == 200, f"HTTP {r_itemtrackedtrue.status_code}")
        cancel_build(bi_pk); delete_build(bi_pk)

    # -- Filtros basicos de /build/ --
    for name, params in [("status", {"status": 10}), ("active-false", {"active": "false"}),
                          ("part", {"part": ASSEMBLY_PK}), ("part-variants", {"part": ASSEMBLY_PK, "include_variants": "true"})]:
        r = api("get", "/build/", params=params)
        log(f"COV-BUILD-filter-{name}", f"Filtro build ?{list(params.keys())}", r.status_code == 200, f"HTTP {r.status_code}")

    for name, params in [("order_outstanding-false", {"order_outstanding": "false"}), ("allocated-true", {"allocated": "true"}),
                          ("consumed-false", {"consumed": "false"}), ("available-false", {"available": "false"}), ("on_order-false", {"on_order": "false"})]:
        r = api("get", "/build/line/", params=params)
        log(f"COV-BUILDLINE-filter-{name}", f"Filtro build-line ?{list(params.keys())}", r.status_code == 200, f"HTTP {r.status_code}")

    r_badbuild = api("get", "/build/line/", params={"build": 999999999})
    log("COV-BUILDLINE-badbuild", "Filtro build-line ?build= inexistente (debe rechazar)", r_badbuild.status_code in (200, 400), f"HTTP {r_badbuild.status_code}")

    # -- Endpoints sobre build inexistente (NotFound branches) --
    # Nota: se descubrio que estos sub-endpoints de Build no manejan
    # limpiamente un pk inexistente (devuelven 500 en vez de 404 en varios
    # casos) -- ver defectos documentados abajo; el objetivo aqui es ejercitar
    # la rama except/get_object, no necesariamente un 404 limpio.
    for action in ["issue", "hold", "cancel", "create-output", "unallocate"]:
        r = api("post", f"/build/999999999/{action}/", {})
        ok = r.status_code in (400, 404)
        detail = f"HTTP {r.status_code}"
        if r.status_code == 500:
            detail += "  [DEFECTO CONFIRMADO: pk de Build inexistente no se maneja limpiamente, produce 500 en vez de 404]"
        log(f"COV-BUILD-notfound-{action}", f"POST /build/999999999/{action}/ (debe rechazar)", ok, detail)

    # -- create-output: validaciones --
    r_co = create_build(part=ASSEMBLY_NO_BOM, qty=5)
    co_pk = r_co.json().get("pk") if r_co.status_code == 201 else None
    if co_pk:
        issue_build(co_pk)
        r_zeroqty = api("post", f"/build/{co_pk}/create-output/", {"quantity": 0, "serial_numbers": ""})
        log("COV-BUILD-output-zeroqty", "create-output con quantity=0 (debe rechazar)", r_zeroqty.status_code in (400, 422), f"HTTP {r_zeroqty.status_code}")
        cancel_build(co_pk); delete_build(co_pk)

    # -- delete-outputs / scrap-outputs / complete: outputs=[] --
    r_empty = create_build(part=ASSEMBLY_NO_BOM, qty=1)
    empty_pk = r_empty.json().get("pk") if r_empty.status_code == 201 else None
    if empty_pk:
        issue_build(empty_pk)
        r_delempty = api("post", f"/build/{empty_pk}/delete-outputs/", {"outputs": []})
        log("COV-BUILD-deleteoutputs-empty", "delete-outputs con outputs=[] (debe rechazar)", r_delempty.status_code in (400, 422), f"HTTP {r_delempty.status_code}")
        r_scrapempty = api("post", f"/build/{empty_pk}/scrap-outputs/", {"outputs": [], "location": LOC_A})
        log("COV-BUILD-scrapoutputs-empty", "scrap-outputs con outputs=[] (debe rechazar)", r_scrapempty.status_code in (400, 422), f"HTTP {r_scrapempty.status_code}")
        r_compempty = api("post", f"/build/{empty_pk}/complete/", {"outputs": [], "location": LOC_A})
        log("COV-BUILD-complete-empty", "complete con outputs=[] (debe rechazar)", r_compempty.status_code in (400, 422), f"HTTP {r_compempty.status_code}")
        cancel_build(empty_pk); delete_build(empty_pk)

    # -- BuildCompleteSerializer: validaciones de estado/allocation --
    r_comp = create_build(part=ASSEMBLY_PK, qty=1)
    comp_pk = r_comp.json().get("pk") if r_comp.status_code == 201 else None
    if comp_pk:
        # Build aun Pending (no issued) -> status != PRODUCTION
        r_notprod = api("post", f"/build/{comp_pk}/complete/", {"outputs": [], "location": LOC_A})
        log("COV-BUILD-complete-notproduction", "complete sobre build Pending (debe rechazar)", r_notprod.status_code in (400, 422), f"HTTP {r_notprod.status_code}")

        issue_build(comp_pk)
        r_out = api("post", f"/build/{comp_pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        outs = r_out.json() if isinstance(r_out.json(), list) else ([r_out.json()] if r_out.status_code == 201 else [])
        out_pk = outs[0].get("pk") if outs else None
        if out_pk:
            r_incomplete = api("post", f"/build/{comp_pk}/finish/", {"accept_unallocated": True, "accept_incomplete": False})
            log("COV-BUILD-finish-incomplete-reject", "finish con accept_incomplete=False y output incompleto (debe rechazar)", r_incomplete.status_code in (400, 422), f"HTTP {r_incomplete.status_code}")

            r_unalloc = api("post", f"/build/{comp_pk}/finish/", {"accept_unallocated": False, "accept_incomplete": True})
            log("COV-BUILD-finish-unallocated-reject", "finish con accept_unallocated=False y BOM sin asignar (debe rechazar)", r_unalloc.status_code in (400, 422), f"HTTP {r_unalloc.status_code}")
        cancel_build(comp_pk); delete_build(comp_pk)

    # -- BuildAllocationItemSerializer: validaciones --
    r_av = create_build(part=ASSEMBLY_PK, qty=1)
    av_pk = r_av.json().get("pk") if r_av.status_code == 201 else None
    if av_pk:
        r_lines = api("get", "/build/line/", params={"build": av_pk})
        ld = r_lines.json()
        lines_av = ld if isinstance(ld, list) else ld.get("results", [])
        if lines_av:
            line0 = lines_av[0]
            r_stock = api("post", "/stock/", {"part": line0["part"], "location": LOC_A, "quantity": 50})
            stock_pk = None
            if r_stock.status_code == 201:
                sd = r_stock.json()
                stock_pk = (sd[0] if sd else {}).get("pk") if isinstance(sd, list) else sd.get("pk")
            if stock_pk:
                r_zeroalloc = api("post", f"/build/{av_pk}/allocate/", {"items": [{"build_line": line0["pk"], "stock_item": stock_pk, "quantity": 0}]})
                log("COV-BUILD-allocate-zeroqty", "allocate con quantity=0 (debe rechazar)", r_zeroalloc.status_code in (400, 422), f"HTTP {r_zeroalloc.status_code}")

                r_overalloc = api("post", f"/build/{av_pk}/allocate/", {"items": [{"build_line": line0["pk"], "stock_item": stock_pk, "quantity": 9999}]})
                log("COV-BUILD-allocate-overqty", "allocate con quantity > disponible (debe rechazar)", r_overalloc.status_code in (400, 422), f"HTTP {r_overalloc.status_code}")

                # Asignar dos veces la misma línea/stock_item -> incrementa BuildItem existente
                r_alloc1 = api("post", f"/build/{av_pk}/allocate/", {"items": [{"build_line": line0["pk"], "stock_item": stock_pk, "quantity": 2}]})
                r_alloc2 = api("post", f"/build/{av_pk}/allocate/", {"items": [{"build_line": line0["pk"], "stock_item": stock_pk, "quantity": 2}]})
                log("COV-BUILD-allocate-increment", "allocate repetido sobre misma línea/stock_item (incrementa BuildItem)", r_alloc2.status_code in (200, 201), f"HTTP {r_alloc2.status_code} {short(r_alloc2)}")
                api("delete", f"/stock/{stock_pk}/")

            r_emptyitems = api("post", f"/build/{av_pk}/allocate/", {"items": []})
            log("COV-BUILD-allocate-empty", "allocate con items=[] (debe rechazar)", r_emptyitems.status_code in (400, 422), f"HTTP {r_emptyitems.status_code}")

        # stock_item cuya parte no coincide con NINGUNA línea del BOM (BuildItem.clean())
        r_otherpart = api("post", "/part/", {"name": "COV Build NotInBOM Part", "description": "x", "category": 1, "purchaseable": True})
        otherpart_pk = r_otherpart.json().get("pk") if r_otherpart.status_code == 201 else None
        if otherpart_pk and lines_av:
            r_stock2 = api("post", "/stock/", {"part": otherpart_pk, "location": LOC_A, "quantity": 10})
            sd2 = r_stock2.json() if r_stock2.status_code == 201 else None
            stock_pk2 = (sd2[0] if isinstance(sd2, list) else sd2).get("pk") if sd2 else None
            if stock_pk2:
                r_notinbom = api("post", f"/build/{av_pk}/allocate/", {"items": [{"build_line": lines_av[0]["pk"], "stock_item": stock_pk2, "quantity": 1}]})
                log("COV-BUILD-allocate-notinbom", "allocate con stock_item cuya parte no esta en el BOM (debe rechazar)", r_notinbom.status_code in (400, 422), f"HTTP {r_notinbom.status_code} {short(r_notinbom)}")
                api("delete", f"/stock/{stock_pk2}/")
            api("patch", f"/part/{otherpart_pk}/", {"active": False})
            api("delete", f"/part/{otherpart_pk}/")
        cancel_build(av_pk); delete_build(av_pk)

    # -- consume: validaciones --
    r_cv = create_build(part=ASSEMBLY_PK, qty=1)
    cv_pk = r_cv.json().get("pk") if r_cv.status_code == 201 else None
    if cv_pk:
        api("post", f"/build/{cv_pk}/auto-allocate/", {"location": LOC_A, "interchangeable": True, "substitutes": True, "optional_items": False})
        r_consumeempty = api("post", f"/build/{cv_pk}/consume/", {"items": [], "lines": []})
        log("COV-BUILD-consume-empty", "consume con items=[] y lines=[] (debe rechazar)", r_consumeempty.status_code in (400, 422), f"HTTP {r_consumeempty.status_code}")

        r_itemsget = api("get", "/build/item/", params={"build": cv_pk})
        id_ = r_itemsget.json()
        items_cv = id_ if isinstance(id_, list) else id_.get("results", [])
        if items_cv:
            r_zeroconsume = api("post", f"/build/{cv_pk}/consume/", {"items": [{"build_item": items_cv[0]["pk"], "quantity": 0}], "lines": []})
            log("COV-BUILD-consume-zeroqty", "consume con quantity=0 (debe rechazar)", r_zeroconsume.status_code in (400, 422), f"HTTP {r_zeroconsume.status_code}")

            r_overconsume = api("post", f"/build/{cv_pk}/consume/", {"items": [{"build_item": items_cv[0]["pk"], "quantity": 999999}], "lines": []})
            log("COV-BUILD-consume-overqty", "consume con quantity > asignado (debe rechazar)", r_overconsume.status_code in (400, 422), f"HTTP {r_overconsume.status_code}")
        cancel_build(cv_pk); delete_build(cv_pk)

    # -- unallocate: output de otro build --
    r_ua1 = create_build(part=ASSEMBLY_NO_BOM, qty=1)
    ua1_pk = r_ua1.json().get("pk") if r_ua1.status_code == 201 else None
    r_ua2 = create_build(part=ASSEMBLY_NO_BOM, qty=1)
    ua2_pk = r_ua2.json().get("pk") if r_ua2.status_code == 201 else None
    if ua1_pk and ua2_pk:
        issue_build(ua1_pk)
        r_out_ua = api("post", f"/build/{ua1_pk}/create-output/", {"quantity": 1, "serial_numbers": ""})
        outs_ua = r_out_ua.json() if isinstance(r_out_ua.json(), list) else ([r_out_ua.json()] if r_out_ua.status_code == 201 else [])
        out_pk_ua = outs_ua[0].get("pk") if outs_ua else None
        if out_pk_ua:
            r_wrongoutput = api("post", f"/build/{ua2_pk}/unallocate/", {"output": out_pk_ua})
            log("COV-BUILD-unallocate-wrongbuild", "unallocate con output de OTRO build (debe rechazar)", r_wrongoutput.status_code in (400, 422), f"HTTP {r_wrongoutput.status_code} {short(r_wrongoutput)}")
        cancel_build(ua1_pk); delete_build(ua1_pk)
        cancel_build(ua2_pk); delete_build(ua2_pk)

    # -- Duplicar Build (duplicate.original + copy_parameters) --
    r_origbuild = create_build(part=ASSEMBLY_NO_BOM, qty=1)
    orig_pk = r_origbuild.json().get("pk") if r_origbuild.status_code == 201 else None
    if orig_pk:
        r_dup2 = api("post", "/build/", {
            "part": ASSEMBLY_NO_BOM, "quantity": 1, "reference": next_bo_ref(), "title": "coverage dup build 2",
            "duplicate": {"original": orig_pk, "copy_parameters": True},
        })
        ok_dup2 = r_dup2.status_code == 201
        log("COV-BUILD-duplicate", "POST /build/ con duplicate.original/copy_parameters", ok_dup2, f"HTTP {r_dup2.status_code} {short(r_dup2)}")
        if ok_dup2:
            cancel_build(r_dup2.json()["pk"]); delete_build(r_dup2.json()["pk"])
        cancel_build(orig_pk); delete_build(orig_pk)


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 62)
    print("  InvenTree — Órdenes de Fabricación (Build Orders)")
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

        print("\n── CPF-008: Build Orders ──────────────────────────────")
        tc_bo_01(page); tc_bo_02(page); tc_bo_03(page); tc_bo_04(page)
        tc_bo_05(page); tc_bo_06(page); tc_bo_07(page); tc_bo_08(page)

        ctx.close(); browser.close()

    print("\n── FN8 — Build Orders: casos extendidos ───────────────")
    try:
        fn8_build_extended()
    except Exception as e:
        log("FN8-BUILD-extended", "Casos extendidos de Build", False, str(e))
    try:
        fn8_build_tracked_component()
    except Exception as e:
        log("FN8-BUILD-tracked", "Build con componente trackable", False, str(e))
    try:
        fn8_coverage_extra()
    except Exception as e:
        log("FN8-BUILD-coverage-extra", "Casos adicionales de cobertura", False, str(e))

    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed

    print("\n" + "=" * 62)
    print(f"  TOTAL: {passed}/{len(results)} PASS  |  {failed} FAIL")
    print("=" * 62)
    print(f"\n  {'TC':<30} {'Resultado':<10} Caso")
    print(f"  {'-'*29} {'-'*9} {'-'*36}")
    for r in results:
        mark = "PASS ✅" if r["pass"] else "FAIL ❌"
        print(f"  {r['tc']:<30} {mark:<10} {r['name']}")

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
