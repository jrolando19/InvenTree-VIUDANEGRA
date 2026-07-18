#!/usr/bin/env python3
"""
Integración — test_integracion_inventree_suite.py

A diferencia de las suites funcionales (un módulo aislado) y de la suite de
sistema golden_path (el flujo de negocio COMPLETO de punta a punta), acá se
prueban puntos de contacto PUNTUALES entre exactamente dos módulos — la
"costura" específica donde uno produce datos que el otro consume.

INT-01  order → stock   : recibir una PO crea el StockItem correcto
INT-02  build → stock   : completar un Build consume el stock asignado y
                          genera el output correcto
INT-03  order → stock   : enviar una SO consume la asignación de stock
                          (allocation) correctamente
INT-04  stock → tracking: una operación de stock genera el evento de
                          tracking correcto (originalmente ST-010, en la
                          suite de sistema de permisos/trazabilidad ya
                          retirada — movido acá por ser integración puntual)
"""
import os, sys, json, time, datetime, requests
from pathlib import Path

BASE = "http://localhost:8000/api"
AUTH = ("admin", "inventree")
RESULTS_DIR = Path(os.path.abspath(__file__)).parent.parent.parent / "test_output" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SUPPLIER_PK = 1
CUSTOMER_PK = 2
LOC_A       = 1
LOC_B       = 2
PART_R_PK   = 1   # Resistencia 10k — purchaseable, no salable
SUPPLIER_PART_R_PK = 1

results  = []
counters = {"pass": 0, "fail": 0, "total": 0}


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def api(method, endpoint, data=None, params=None):
    url = f"{BASE}/{endpoint.lstrip('/')}"
    return getattr(requests, method)(url, json=data, params=params, auth=AUTH, timeout=15)


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

    results.append({"id": tc_id, "desc": description, "status": status, "detail": detail})
    return passed


def extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", [])
    return []


def first_pk(response):
    data = response.json()
    item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    return item.get("pk")


# ──────────────────────────────────────────────────────────────────
# INT-01 — order → stock: recibir una PO crea el StockItem correcto
# ──────────────────────────────────────────────────────────────────

def int_01_po_receive_creates_stock():
    print("\n── INT-01: PO recibida → StockItem correcto (order → stock) ──")

    ref = f"PO-{int(time.time()) % 9000 + 1000:04d}"
    r_po = api("post", "/order/po/", {"supplier": SUPPLIER_PK, "reference": ref})
    ok_po = r_po.status_code == 201
    po_pk = r_po.json().get("pk") if ok_po else None
    record("INT-01a", "Crear Purchase Order", ok_po, f"po_pk={po_pk}", r_po if not ok_po else None)
    if not po_pk:
        record("INT-01b", "Recibir PO genera StockItem con part/quantity correctos", False, "Sin PO")
        return

    r_line = api("post", "/order/po-line/", {
        "order": po_pk, "part": SUPPLIER_PART_R_PK, "quantity": 7,
        "purchase_price": "0.50", "purchase_price_currency": "USD",
    })
    line_pk = r_line.json().get("pk") if r_line.status_code == 201 else None
    api("post", f"/order/po/{po_pk}/issue/")

    # Snapshot de stock ANTES de recibir, para aislar el efecto de esta recepción puntual
    r_before = api("get", "/stock/", params={"part": PART_R_PK, "location": LOC_B})
    qty_before = sum(float(i.get("quantity", 0)) for i in extract_list(r_before.json()))

    r_recv = api("post", f"/order/po/{po_pk}/receive/", {
        "items": [{"line_item": line_pk, "quantity": 7, "location": LOC_B}],
        "location": LOC_B,
    })
    ok_recv = r_recv.status_code in (200, 201)

    r_after = api("get", "/stock/", params={"part": PART_R_PK, "location": LOC_B})
    qty_after = sum(float(i.get("quantity", 0)) for i in extract_list(r_after.json()))
    delta = qty_after - qty_before

    record("INT-01b", "Recibir PO genera StockItem con part/quantity correctos",
           ok_recv and delta == 7,
           f"receive HTTP {r_recv.status_code} | stock en LOC_B: antes={qty_before} después={qty_after} (delta={delta}, esperado 7)",
           r_recv if not ok_recv else None)


# ──────────────────────────────────────────────────────────────────
# INT-02 — build → stock: completar un Build consume el stock asignado
# y genera el output correcto
# ──────────────────────────────────────────────────────────────────

def int_02_build_consumes_and_outputs():
    print("\n── INT-02: Build completado → consume stock + genera output (build → stock) ──")

    ts = int(time.time()) % 100000
    r_comp = api("post", "/part/", {
        "name": f"INT Componente {ts}", "description": "x", "category": 1,
        "assembly": False, "purchaseable": True, "active": True,
    })
    comp_pk = r_comp.json().get("pk") if r_comp.status_code == 201 else None

    r_asm = api("post", "/part/", {
        "name": f"INT Ensamble {ts}", "description": "x", "category": 3,
        "assembly": True, "active": True,
    })
    asm_pk = r_asm.json().get("pk") if r_asm.status_code == 201 else None

    record("INT-02a", "Crear componente + ensamble temporales", bool(comp_pk and asm_pk),
           f"comp_pk={comp_pk} asm_pk={asm_pk}")
    if not (comp_pk and asm_pk):
        record("INT-02b", "Completar Build consume stock asignado y genera output", False, "Sin partes")
        return

    api("post", "/bom/", {"part": asm_pk, "sub_part": comp_pk, "quantity": 3})

    # Stock de sobra del componente, para poder verificar que SOLO se consume lo asignado
    r_stk = api("post", "/stock/", {"part": comp_pk, "quantity": 20, "location": LOC_A})
    stk_data = r_stk.json()
    stk_pk = (stk_data[0] if isinstance(stk_data, list) else stk_data).get("pk")

    r_build = api("post", "/build/", {
        "part": asm_pk, "quantity": 2, "title": f"INT Build {ts}", "reference": f"BO-{ts % 9000 + 1000:04d}",
    })
    build_pk = r_build.json().get("pk") if r_build.status_code == 201 else None
    record("INT-02b-setup", "Crear Build Order", bool(build_pk), f"build_pk={build_pk}",
           r_build if not build_pk else None)
    if not build_pk:
        record("INT-02b", "Completar Build consume stock asignado y genera output", False, "Sin Build Order")
        return

    api("post", f"/build/{build_pk}/auto-allocate/", {"location": LOC_A, "interchangeable": False, "substitutes": False})
    api("post", f"/build/{build_pk}/issue/")

    r_out = api("post", f"/build/{build_pk}/create-output/", {"quantity": 2, "location": LOC_A, "serial_numbers": ""})
    out_data = r_out.json()
    out_list = out_data if isinstance(out_data, list) else [out_data]
    out_pk = out_list[0].get("pk") if out_list and isinstance(out_list[0], dict) else None
    if out_pk:
        api("patch", f"/stock/{out_pk}/", {"is_building": False, "location": LOC_A})

    r_fin = api("post", f"/build/{build_pk}/finish/", {
        "accept_unallocated": True, "accept_overallocated": "accept", "accept_incomplete": True,
    })
    ok_fin = r_fin.status_code in (200, 201)

    # Verificar consumo: 20 (inicial) - 6 (3 x quantity=2) = 14 restantes del componente en LOC_A
    r_comp_stock = api("get", "/stock/", params={"part": comp_pk, "location": LOC_A})
    comp_qty_after = sum(float(i.get("quantity", 0)) for i in extract_list(r_comp_stock.json()))

    # Verificar output: debe existir StockItem del ensamble con quantity=2
    r_asm_stock = api("get", "/stock/", params={"part": asm_pk})
    asm_qty = sum(float(i.get("quantity", 0)) for i in extract_list(r_asm_stock.json()))

    consumed_ok = comp_qty_after == 14
    output_ok = asm_qty == 2
    record("INT-02b", "Completar Build consume stock asignado y genera output correcto",
           ok_fin and consumed_ok and output_ok,
           f"finish HTTP {r_fin.status_code} | componente restante={comp_qty_after} (esperado 14) | "
           f"stock de ensamble generado={asm_qty} (esperado 2)",
           r_fin if not ok_fin else None)

    api("patch", f"/part/{asm_pk}/", {"active": False})
    api("delete", f"/part/{asm_pk}/")
    api("patch", f"/part/{comp_pk}/", {"active": False})
    api("delete", f"/part/{comp_pk}/")


# ──────────────────────────────────────────────────────────────────
# INT-03 — order → stock: enviar una SO consume la asignación de
# stock (allocation) correctamente
# ──────────────────────────────────────────────────────────────────

def int_03_so_ship_consumes_allocation():
    print("\n── INT-03: SO enviada → allocation consumida correctamente (order → stock) ──")

    ts = int(time.time()) % 100000
    r_part = api("post", "/part/", {
        "name": f"INT Vendible {ts}", "description": "x", "category": 1,
        "salable": True, "active": True,
    })
    part_pk = r_part.json().get("pk") if r_part.status_code == 201 else None
    record("INT-03a", "Crear parte vendible temporal", bool(part_pk), f"part_pk={part_pk}")
    if not part_pk:
        record("INT-03b", "Enviar SO consume la allocation de stock correctamente", False, "Sin parte")
        return

    r_stk = api("post", "/stock/", {"part": part_pk, "quantity": 5, "location": LOC_A})
    stk_data = r_stk.json()
    stk_pk = (stk_data[0] if isinstance(stk_data, list) else stk_data).get("pk")

    r_so = api("post", "/order/so/", {"customer": CUSTOMER_PK})
    so_pk = r_so.json().get("pk") if r_so.status_code == 201 else None
    r_line = api("post", "/order/so-line/", {
        "order": so_pk, "part": part_pk, "quantity": 3, "sale_price": "10.00", "sale_price_currency": "USD",
    })
    line_pk = r_line.json().get("pk") if r_line.status_code == 201 else None
    api("post", f"/order/so/{so_pk}/issue/")

    r_ship = api("post", "/order/so/shipment/", {"order": so_pk})
    ship_pk = r_ship.json().get("pk") if r_ship.status_code == 201 else None

    r_alloc = api("post", f"/order/so/{so_pk}/allocate/", {
        "shipment": ship_pk, "items": [{"line_item": line_pk, "stock_item": stk_pk, "quantity": 3}],
    })
    ok_alloc = r_alloc.status_code in (200, 201)

    r_alloc_list_before = api("get", "/order/so-allocation/", params={"order": so_pk})
    alloc_count_before = len(extract_list(r_alloc_list_before.json()))

    r_send = api("post", f"/order/so/shipment/{ship_pk}/ship/", {})
    ok_send = r_send.status_code in (200, 201)

    # Al enviarse el shipment, la asignación se "completa" (deja de estar pending) —
    # y el stock disponible del item baja en la cantidad enviada.
    r_stk_after = api("get", f"/stock/{stk_pk}/")
    qty_after = r_stk_after.json().get("quantity") if r_stk_after.status_code == 200 else None

    record("INT-03b", "Enviar SO consume la allocation de stock correctamente",
           ok_alloc and ok_send and alloc_count_before > 0 and qty_after is not None and float(qty_after) == 2.0,
           f"alloc HTTP {r_alloc.status_code} | ship HTTP {r_send.status_code} | "
           f"allocations antes de enviar={alloc_count_before} | stock restante={qty_after} (esperado 2, 5-3)",
           r_send if not ok_send else None)

    api("post", f"/order/so/{so_pk}/complete/")
    api("patch", f"/part/{part_pk}/", {"active": False})
    api("delete", f"/part/{part_pk}/")


# ──────────────────────────────────────────────────────────────────
# INT-04 — stock → tracking: una operación de stock genera el
# evento de tracking correcto (movido desde ST-010)
# ──────────────────────────────────────────────────────────────────

def int_04_stock_operation_generates_tracking_event():
    print("\n── INT-04: Operación de stock → evento de tracking correcto (stock → tracking) ──")

    r_stk = api("post", "/stock/", {"part": PART_R_PK, "quantity": 5, "location": LOC_A})
    stk_data = r_stk.json()
    stk_pk = (stk_data[0] if isinstance(stk_data, list) else stk_data).get("pk")
    record("INT-04a", "Crear StockItem para generar historial", bool(stk_pk), f"stk_pk={stk_pk}")
    if not stk_pk:
        record("INT-04b", "Transferencia genera evento de tracking con campos correctos", False, "Sin StockItem")
        return

    r_transfer = api("post", "/stock/transfer/", {
        "items": [{"pk": stk_pk, "quantity": 3}], "location": LOC_B, "notes": "INT-04 transfer",
    })
    ok_transfer = r_transfer.status_code in (200, 201)

    r_track = api("get", "/stock/track/", params={"item": stk_pk})
    ok_track = r_track.status_code == 200
    events = extract_list(r_track.json())
    has_fields = bool(events) and all(k in events[0] for k in ("pk", "item", "date", "label"))

    record("INT-04b", "Transferencia genera evento de tracking con campos correctos",
           ok_transfer and ok_track and has_fields,
           f"transfer HTTP {r_transfer.status_code} | track HTTP {r_track.status_code} | "
           f"eventos={len(events)} | primer evento keys={list(events[0].keys())[:8] if events else []}",
           r_track if not (ok_track and has_fields) else None)

    api("delete", f"/stock/{stk_pk}/")


# ──────────────────────────────────────────────────────────────────
# Resumen
# ──────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "═" * 60)
    print("  RESUMEN — Pruebas de Integración")
    print("═" * 60)
    for r in results:
        tag = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {tag} {r['id']:10s} {r['desc']}")
    print()
    pct = round(100 * counters["pass"] / counters["total"], 1) if counters["total"] else 0
    print(f"  Total: {counters['total']}  PASS: {counters['pass']}  FAIL: {counters['fail']}  ({pct}%)")
    print("═" * 60 + "\n")

    out = {
        "suite":     "test_integracion_inventree_suite.py",
        "modules":   ["INT-01 order->stock", "INT-02 build->stock", "INT-03 order->stock", "INT-04 stock->tracking"],
        "timestamp": datetime.datetime.now().isoformat(),
        "summary":   counters,
        "cases":     results,
    }
    out_path = RESULTS_DIR / "integracion_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  Resultados guardados en {out_path}")


if __name__ == "__main__":
    int_01_po_receive_creates_stock()
    int_02_build_consumes_and_outputs()
    int_03_so_ship_consumes_allocation()
    int_04_stock_operation_generates_tracking_event()
    print_summary()
    sys.exit(0 if counters["fail"] == 0 else 1)
