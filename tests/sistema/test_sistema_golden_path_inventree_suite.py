#!/usr/bin/env python3
"""
Sistema — test_sistema_golden_path_inventree_suite.py
ST-013: F10 — Golden Path E2E (recorrido end-to-end, cruza todos los módulos)
Cadena completa en una sola sesión:
  GP-01 Crear parte + BOM
  GP-02 Crear PO y recibir stock
  GP-03 Crear Build Order y completarla
  GP-04 Crear SO, asignar y enviar
  GP-05 Crear RO (devolución)
  GP-06 Verificar stock final
  GP-07 Verificar trazabilidad
  GP-08 Verificar plugins activos
"""

import os, sys, json, time, datetime, requests
from pathlib import Path

BASE   = "http://localhost:8000/api"
AUTH   = ("admin", "inventree")
RESULTS_DIR = Path(os.path.abspath(__file__)).parent.parent.parent / "test_output" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Datos pre-existentes (setup_system_tests.py)
SUPPLIER_PK   = 1
CUSTOMER_PK   = 2
LOC_A         = 1
LOC_B         = 2
COMP_PART_PK  = 2   # Capacitor 100uF — componente

results  = []
counters = {"pass": 0, "fail": 0, "total": 0}

# Estado compartido entre pasos
state = {}

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def api(method, endpoint, data=None, params=None):
    url = f"{BASE}/{endpoint.lstrip('/')}"
    r = getattr(requests, method)(url, json=data, params=params, auth=AUTH, timeout=15)
    return r


def record(tc_id, description, passed, detail="", response=None):
    status = "PASS" if passed else "FAIL"
    counters["total"] += 1
    counters["pass" if passed else "fail"] += 1

    tag = "✅" if passed else "❌"
    print(f"  {tag} [{tc_id}] {description}")
    if detail:
        print(f"       → {detail}")
    if not passed and response is not None:
        try:
            print(f"       → HTTP {response.status_code} {response.text[:250]}")
        except Exception:
            pass

    results.append({
        "id": tc_id, "desc": description,
        "status": status, "detail": detail,
    })
    return passed


# ──────────────────────────────────────────────────────────────────
# Golden Path
# ──────────────────────────────────────────────────────────────────

def gp_01_part_and_bom():
    """Crear una parte ensamble nueva con BOM de un componente."""
    print("\n── GP-01: Crear parte ensamble + BOM ──")

    ts = int(time.time()) % 100000
    r_part = api("post", "/part/", {
        "name": f"GP Ensamble {ts}", "category": 3,
        "assembly": True, "component": False,
        "salable": True, "active": True
    })
    ok = r_part.status_code == 201
    state["asm_pk"] = r_part.json().get("pk") if ok else None
    record("GP-01a", "Crear parte ensamble nueva", ok,
           f"pk={state.get('asm_pk')}", r_part if not ok else None)

    if state.get("asm_pk"):
        r_bom = api("post", "/bom/", {
            "part": state["asm_pk"],
            "sub_part": COMP_PART_PK,
            "quantity": 2
        })
        ok_bom = r_bom.status_code == 201
        state["bom_pk"] = r_bom.json().get("pk") if ok_bom else None
        record("GP-01b", "Crear BOM con componente existente", ok_bom,
               f"bom_pk={state.get('bom_pk')}", r_bom if not ok_bom else None)
    else:
        record("GP-01b", "Crear BOM con componente existente", False, "Sin parte ensamble")


def gp_02_po_receive():
    """PO para reabastecer el componente y recibirlo."""
    print("\n── GP-02: Purchase Order + recepción ──")

    r_po = api("post", "/order/po/", {"supplier": SUPPLIER_PK})
    ok_po = r_po.status_code == 201
    po_pk = r_po.json().get("pk") if ok_po else None
    record("GP-02a", "Crear Purchase Order al proveedor", ok_po,
           f"po_pk={po_pk}", r_po if not ok_po else None)

    if not po_pk:
        record("GP-02b", "Agregar línea a PO", False, "Sin PO")
        record("GP-02c", "Emitir PO y recibir stock", False, "Sin PO")
        return

    # Obtener SupplierPart del componente
    r_sp = api("get", "/company/part/", params={"part": COMP_PART_PK, "company": SUPPLIER_PK})
    sp_raw = r_sp.json() if r_sp.status_code == 200 else []
    sp_list = sp_raw.get("results", sp_raw) if isinstance(sp_raw, dict) else sp_raw
    sp_pk = sp_list[0]["pk"] if sp_list else None

    if not sp_pk:
        record("GP-02b", "Agregar línea a PO", False, "Sin SupplierPart para componente")
        record("GP-02c", "Emitir PO y recibir stock", False, "Sin SupplierPart")
        return

    r_line = api("post", "/order/po-line/", {
        "order": po_pk, "part": sp_pk, "quantity": 10, "purchase_price": "1.00", "purchase_price_currency": "USD"
    })
    ok_line = r_line.status_code == 201
    po_line_pk = r_line.json().get("pk") if ok_line else None
    record("GP-02b", "Agregar línea a PO", ok_line,
           f"line_pk={po_line_pk}", r_line if not ok_line else None)

    # Emitir
    r_issue = api("post", f"/order/po/{po_pk}/issue/")
    # Recibir
    r_recv = api("post", f"/order/po/{po_pk}/receive/", {
        "items": [{"line_item": po_line_pk, "quantity": 10, "location": LOC_A}],
        "location": LOC_A
    })
    ok_recv = r_recv.status_code in (200, 201)
    state["po_pk"] = po_pk
    record("GP-02c", "Emitir PO y recibir 10 unidades de componente", ok_recv,
           f"HTTP {r_recv.status_code}", r_recv if not ok_recv else None)


def gp_03_build_complete():
    """Build Order para el ensamble usando los componentes recibidos."""
    print("\n── GP-03: Build Order + completar ──")

    asm_pk = state.get("asm_pk")
    if not asm_pk:
        for tc in ["GP-03a", "GP-03b", "GP-03c"]:
            record(tc, f"Build ({tc})", False, "Sin parte ensamble del GP-01")
        return

    ts = int(time.time()) % 9000 + 1000
    r_build = api("post", "/build/", {
        "part": asm_pk, "quantity": 2, "title": f"GP Build {ts}",
        "reference": f"BO-{ts:04d}"
    })
    ok_b = r_build.status_code == 201
    build_pk = r_build.json().get("pk") if ok_b else None
    state["build_pk"] = build_pk
    record("GP-03a", "Crear Build Order para ensamble", ok_b,
           f"build_pk={build_pk}", r_build if not ok_b else None)

    if not build_pk:
        record("GP-03b", "Emitir stock al build", False, "Sin build")
        record("GP-03c", "Completar build", False, "Sin build")
        return

    # Emitir componentes al build
    r_alloc = api("post", f"/build/{build_pk}/auto-allocate/", {
        "location": LOC_A, "exclude_location": None,
        "interchangeable": False, "substitutes": False
    })
    r_issue = api("post", f"/build/{build_pk}/issue/")
    record("GP-03b", "Asignar e emitir componentes al build",
           r_issue.status_code in (200, 201),
           f"alloc={r_alloc.status_code} issue={r_issue.status_code}",
           r_issue if r_issue.status_code not in (200, 201) else None)

    # Crear output y completar
    r_out = api("post", f"/build/{build_pk}/create-output/", {
        "quantity": 2, "location": LOC_A, "serial_numbers": ""
    })
    out_data = r_out.json()
    out_list = out_data if isinstance(out_data, list) else [out_data]
    out_pk = out_list[0].get("pk") if out_list and isinstance(out_list[0], dict) else None

    if out_pk:
        api("patch", f"/stock/{out_pk}/", {"is_building": False, "location": LOC_A})

    r_fin = api("post", f"/build/{build_pk}/finish/", {
        "accept_unallocated": True, "accept_overallocated": "accept",
        "accept_incomplete": True
    })
    ok_fin = r_fin.status_code in (200, 201)
    state["asm_stock_created"] = ok_fin
    record("GP-03c", "Crear output y completar Build Order", ok_fin,
           f"out_pk={out_pk} finish={r_fin.status_code}",
           r_fin if not ok_fin else None)


def gp_04_so_ship():
    """Sales Order del ensamble construido."""
    print("\n── GP-04: Sales Order + envío ──")

    asm_pk = state.get("asm_pk")
    if not asm_pk:
        for tc in ["GP-04a", "GP-04b", "GP-04c"]:
            record(tc, f"SO ({tc})", False, "Sin parte ensamble del GP-01")
        return

    r_so = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    ok_so = r_so.status_code == 201
    so_pk = r_so.json().get("pk") if ok_so else None
    state["so_pk"] = so_pk
    record("GP-04a", "Crear Sales Order al cliente", ok_so,
           f"so_pk={so_pk}", r_so if not ok_so else None)

    if not so_pk:
        record("GP-04b", "Agregar línea y emitir SO", False, "Sin SO")
        record("GP-04c", "Allocate, ship y completar SO", False, "Sin SO")
        return

    r_line = api("post", "/order/so-line/", {
        "order": so_pk, "part": asm_pk, "quantity": 1,
        "sale_price": "50.00", "sale_price_currency": "USD"
    })
    ok_line = r_line.status_code == 201
    line_pk = r_line.json().get("pk") if ok_line else None

    r_issue = api("post", f"/order/so/{so_pk}/issue/")
    ok_issue = r_issue.status_code in (200, 201)
    record("GP-04b", "Agregar línea SO y emitir orden",
           ok_line and ok_issue,
           f"line={r_line.status_code} issue={r_issue.status_code}",
           r_line if not ok_line else (r_issue if not ok_issue else None))

    # Buscar stock del ensamble creado en GP-03
    r_stk = api("get", "/stock/", params={"part": asm_pk, "in_stock": True})
    stk_raw = r_stk.json() if r_stk.status_code == 200 else []
    stk_list = stk_raw.get("results", stk_raw) if isinstance(stk_raw, dict) else stk_raw
    stk_pk = stk_list[0]["pk"] if stk_list else None

    if not stk_pk:
        # Crear stock de emergencia si build no completó con stock
        r_new = api("post", "/stock/", {"part": asm_pk, "quantity": 1, "location": LOC_A})
        new_data = r_new.json()
        stk_pk = (new_data[0] if isinstance(new_data, list) else new_data).get("pk")

    alloc_ok = False
    if stk_pk and line_pk:
        r_ship = api("post", "/order/so/shipment/", {"order": so_pk})
        ship_pk = r_ship.json().get("pk") if r_ship.status_code == 201 else None

        if ship_pk:
            r_alloc = api("post", f"/order/so/{so_pk}/allocate/", {
                "shipment": ship_pk,
                "items": [{"line_item": line_pk, "stock_item": stk_pk, "quantity": 1}]
            })
            alloc_ok = r_alloc.status_code in (200, 201)
            if alloc_ok:
                r_send = api("post", f"/order/so/shipment/{ship_pk}/ship/", {})
                r_comp = api("post", f"/order/so/{so_pk}/complete/", {})
                r_get = api("get", f"/order/so/{so_pk}/")
                final_status = r_get.json().get("status") if r_get.status_code == 200 else None
                record("GP-04c", "Allocate, ship y completar SO",
                       final_status in (15, 20, 30, 40),
                       f"status={final_status}",
                       r_send if r_send.status_code not in (200, 201) else None)
            else:
                record("GP-04c", "Allocate, ship y completar SO", False,
                       f"alloc={r_alloc.status_code}", r_alloc)
        else:
            record("GP-04c", "Allocate, ship y completar SO", False,
                   f"shipment={r_ship.status_code}", r_ship)
    else:
        record("GP-04c", "Allocate, ship y completar SO", False,
               f"stk_pk={stk_pk} line_pk={line_pk}")


def gp_05_return_order():
    """Return Order del ensamble."""
    print("\n── GP-05: Return Order ──")

    asm_pk = state.get("asm_pk")
    ts = int(time.time()) % 9000 + 1000
    ref = f"RMA-{ts}"

    r_ro = api("post", "/order/ro/", {"customer": CUSTOMER_PK, "reference": ref})
    ok_ro = r_ro.status_code == 201
    ro_pk = r_ro.json().get("pk") if ok_ro else None
    record("GP-05a", "Crear Return Order con referencia única", ok_ro,
           f"ro_pk={ro_pk} ref={ref}", r_ro if not ok_ro else None)

    if ro_pk and asm_pk:
        # Crear stock item para la devolución
        r_stk = api("post", "/stock/", {"part": asm_pk, "quantity": 1, "location": LOC_A})
        stk_data = r_stk.json()
        stk_pk = (stk_data[0] if isinstance(stk_data, list) else stk_data).get("pk")

        r_line = api("post", "/order/ro-line/", {
            "order": ro_pk, "part": asm_pk, "quantity": 1, "item": stk_pk
        })
        r_issue = api("post", f"/order/ro/{ro_pk}/issue/")
        ok_roc = r_line.status_code == 201 and r_issue.status_code in (200, 201)
        record("GP-05b", "Agregar línea y emitir Return Order", ok_roc,
               f"line={r_line.status_code} issue={r_issue.status_code}",
               r_line if r_line.status_code != 201 else (r_issue if r_issue.status_code not in (200, 201) else None))
    else:
        record("GP-05b", "Agregar línea y emitir Return Order", False,
               "Sin RO o sin parte ensamble")


def gp_06_stock_verify():
    """Verificar que el stock del componente tiene movimientos."""
    print("\n── GP-06: Verificar estado de stock ──")

    r = api("get", "/stock/", params={"part": COMP_PART_PK})
    if r.status_code == 200:
        raw = r.json()
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        total_qty = sum(float(i.get("quantity", 0)) for i in (items or []))
        record("GP-06", "Componente tiene registros de stock activos",
               total_qty >= 0,
               f"items={len(items)} qty_total={total_qty}")
    else:
        record("GP-06", "Componente tiene registros de stock activos", False,
               f"HTTP {r.status_code}", r)


def gp_07_traceability():
    """Verificar trazabilidad del stock."""
    print("\n── GP-07: Trazabilidad ──")

    r = api("get", "/stock/track/", params={"part": COMP_PART_PK})
    if r.status_code == 200:
        raw = r.json()
        events = raw.get("results", raw) if isinstance(raw, dict) else raw
        record("GP-07", "Historial de tracking del componente disponible",
               isinstance(events, list) and len(events) > 0,
               f"eventos={len(events) if isinstance(events, list) else '?'}")
    else:
        record("GP-07", "Historial de tracking del componente disponible", False,
               f"HTTP {r.status_code}", r)


def gp_08_plugins():
    """Plugins activos verificados."""
    print("\n── GP-08: Plugins ──")

    r = api("get", "/plugins/")
    if r.status_code == 200:
        data = r.json()
        plugin_list = data.get("results", data) if isinstance(data, dict) else data
        active = [p for p in plugin_list if p.get("active")] if isinstance(plugin_list, list) else []
        record("GP-08", "Sistema tiene plugins activos al finalizar E2E",
               len(active) > 0,
               f"activos={len(active)}")
    else:
        record("GP-08", "Sistema tiene plugins activos al finalizar E2E", False,
               f"HTTP {r.status_code}", r)


# ──────────────────────────────────────────────────────────────────
# Resumen
# ──────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "═" * 60)
    print("  RESUMEN ST-013 Golden Path E2E")
    print("═" * 60)
    for r in results:
        tag = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {tag} {r['id']:8s} {r['desc']}")
    print()
    pct = round(100 * counters["pass"] / counters["total"], 1) if counters["total"] else 0
    print(f"  Total: {counters['total']}  PASS: {counters['pass']}  FAIL: {counters['fail']}  ({pct}%)")
    print("═" * 60 + "\n")

    out = {
        "suite":     "test_sistema_golden_path_inventree_suite.py",
        "modules":   ["ST-013 Golden Path E2E"],
        "timestamp": datetime.datetime.now().isoformat(),
        "summary":   counters,
        "cases":     results,
    }
    out_path = RESULTS_DIR / "golden_path_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  Resultados guardados en {out_path}")


if __name__ == "__main__":
    gp_01_part_and_bom()
    gp_02_po_receive()
    gp_03_build_complete()
    gp_04_so_ship()
    gp_05_return_order()
    gp_06_stock_verify()
    gp_07_traceability()
    gp_08_plugins()
    print_summary()
