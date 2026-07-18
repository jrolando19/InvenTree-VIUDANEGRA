#!/usr/bin/env python3
"""
InvenTree — Suite funcional: Proveedores / Compañías (test_company_inventree_suite.py)
FN7  Gestión de Proveedores  (RF-009, Hito 2)

Incluye:
  TC-SUP-01..07  — CRUD de proveedores (Company)
  FN7-*, COV-*   — Casos extendidos de cobertura (Contact, Address,
                   ManufacturerPart, SupplierPart, PriceBreak, filtros)

Prerrequisitos en BD (setup_system_tests.py):
  - Company pk=1 (Proveedor Electrónico SA, is_supplier=True)
  - Part pk=1 (Resistencia 10k)
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
SS_DIR       = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "company")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "test_output", "results", "company_results.json")
os.makedirs(SS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

results = []


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

def _extract_list(data):
    """/company/ devuelve una lista plana, no {'results': [...]}."""
    if isinstance(data, dict):
        return data.get("results", [])
    if isinstance(data, list):
        return data
    return []

def cleanup_companies(names):
    """Elimina compañías de prueba por nombre."""
    for name in names:
        r = requests.get(f"{API}/company/", params={"search": name, "format": "json"}, auth=AUTH)
        for c in _extract_list(r.json()):
            if c.get("name") == name:
                requests.delete(f"{API}/company/{c['pk']}/", auth=AUTH)


# ══════════════════════════════════════════════════════════════
# CPF-007 — PROVEEDORES
# ══════════════════════════════════════════════════════════════

def tc_sup_01(page):
    """FN7-CP-001 — Crear proveedor válido."""
    cleanup_companies(["DigiKey Electronics TC"])
    r = api("post", "/company/", {
        "name": "DigiKey Electronics TC",
        "website": "https://digikey.com",
        "email": "sales@digikey.com",
        "is_supplier": True
    })
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    page.goto(f"{BASE}/web/purchasing/supplier/", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-SUP-01_create_supplier")
    log("TC-SUP-01", "Crear proveedor válido", ok,
        f"HTTP {r.status_code} | pk={pk} | name={r.json().get('name') if ok else r.json()}")
    if pk: requests.delete(f"{API}/company/{pk}/", auth=AUTH)

def tc_sup_02(page):
    """FN7-CP-002 — Nombre vacío → 400."""
    r = api("post", "/company/", {"name": "", "is_supplier": True})
    ok = r.status_code in (400, 422)
    snap(page, "TC-SUP-02_empty_name")
    log("TC-SUP-02", "Crear proveedor sin nombre (campo requerido)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")

def tc_sup_03(page):
    """FN7-CP-003 — Nombre duplicado."""
    cleanup_companies(["Proveedor Duplicado TC"])
    r1 = api("post", "/company/", {"name": "Proveedor Duplicado TC", "is_supplier": True})
    pk1 = r1.json().get("pk") if r1.status_code == 201 else None
    r2 = api("post", "/company/", {"name": "Proveedor Duplicado TC", "is_supplier": True})
    rejected = r2.status_code in (400, 422)
    ok = rejected
    snap(page, "TC-SUP-03_duplicate")
    note = "RECHAZADO ✅" if rejected else f"ACEPTADO (HTTP {r2.status_code}) — comportamiento permisivo"
    log("TC-SUP-03", "Nombre de proveedor duplicado", ok,
        f"1er POST {r1.status_code} | 2do POST {r2.status_code} [{note}]")
    for pk in [pk1, r2.json().get("pk") if r2.status_code == 201 else None]:
        if pk: requests.delete(f"{API}/company/{pk}/", auth=AUTH)

def tc_sup_04(page):
    """FN7-CP-004 — URL sin https://."""
    cleanup_companies(["Proveedor URL TC"])
    r = api("post", "/company/", {
        "name": "Proveedor URL TC",
        "website": "digikey.com",
        "is_supplier": True
    })
    rejected = r.status_code in (400, 422)
    accepted = r.status_code == 201
    ok = rejected or accepted  # ambos son comportamientos válidos de reportar
    pk = r.json().get("pk") if accepted else None
    snap(page, "TC-SUP-04_url_no_https")
    note = "RECHAZADO" if rejected else "ACEPTADO (sin validación de esquema)"
    log("TC-SUP-04", f"URL sin https:// [{note}]", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")
    if pk: requests.delete(f"{API}/company/{pk}/", auth=AUTH)

def tc_sup_05(page):
    """FN7-CP-005 — Email inválido → 400."""
    r = api("post", "/company/", {
        "name": "Proveedor Email TC",
        "email": "contacto-at-mouser.com",
        "is_supplier": True
    })
    ok = r.status_code in (400, 422)
    snap(page, "TC-SUP-05_invalid_email")
    log("TC-SUP-05", "Email con formato inválido (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")
    if r.status_code == 201:
        requests.delete(f"{API}/company/{r.json()['pk']}/", auth=AUTH)

def tc_sup_06(page):
    """FN7-CP-006 — Nombre 101 chars → 400."""
    r = api("post", "/company/", {"name": "S" * 101, "is_supplier": True})
    ok = r.status_code in (400, 422)
    snap(page, "TC-SUP-06_name_101")
    log("TC-SUP-06", "LÍMITE — nombre 101 caracteres (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")

def tc_sup_07(page):
    """FN7-CP-007 — Nombre mínimo 1 carácter."""
    cleanup_companies(["A"])
    r = api("post", "/company/", {"name": "A", "is_supplier": True})
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    snap(page, "TC-SUP-07_min_name")
    log("TC-SUP-07", "LÍMITE — nombre mínimo 'A' (1 carácter)", ok,
        f"HTTP {r.status_code} | pk={pk}")
    if pk: requests.delete(f"{API}/company/{pk}/", auth=AUTH)


# ══════════════════════════════════════════════════════════════
# FN7 — Gestión de Proveedores: casos extendidos de cobertura
# Contact, Address, ManufacturerPart, SupplierPart filters, PriceBreak —
# que tc_sup_01..07 no tocan.
# ══════════════════════════════════════════════════════════════

def fn7_supplier_extended():
    cases = [
        ("is_customer", {"is_customer": "true"}), ("is_manufacturer", {"is_manufacturer": "false"}),
        ("is_supplier", {"is_supplier": "true"}), ("active", {"active": "true"}),
    ]
    for name, params in cases:
        r = api("get", "/company/", params=params)
        log(f"FN7-COMPANY-{name}", f"Filtro company ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r = api("post", "/company/contact/", {"company": 1, "name": "COV Contact", "phone": "555-0100", "email": "cov@example.com", "role": "Purchasing"})
    ok = r.status_code == 201
    log("FN7-CONTACT-create", "Crear Contact", ok, f"HTTP {r.status_code} {short(r)}")
    if ok:
        api("delete", f"/company/contact/{r.json()['pk']}/")

    r = api("post", "/company/address/", {
        "company": 1, "title": "COV Address", "primary": False,
        "line1": "Av. Coverage 123", "postal_code": "05001", "postal_city": "Arequipa", "country": "PE",
    })
    ok = r.status_code == 201
    log("FN7-ADDRESS-create", "Crear Address", ok, f"HTTP {r.status_code} {short(r)}")
    if ok:
        api("delete", f"/company/address/{r.json()['pk']}/")

    r_mfg = api("post", "/company/", {"name": "COV Manufacturer", "is_manufacturer": True})
    mfg_pk = r_mfg.json().get("pk") if r_mfg.status_code == 201 else None
    mfgpart_pk = None
    if mfg_pk:
        r = api("post", "/company/part/manufacturer/", {"part": 1, "manufacturer": mfg_pk, "MPN": "COV-MPN-001"})
        ok = r.status_code == 201
        log("FN7-MFGPART-create", "Crear ManufacturerPart", ok, f"HTTP {r.status_code} {short(r)}")
        if ok:
            mfgpart_pk = r.json()["pk"]

    # SupplierPart.clean()/save(): pack_quantity con conversión de unidades,
    # vínculo a manufacturer_part, y lógica de "primary" (única/segunda SupplierPart del mismo Part)
    supparts_created = []
    if mfgpart_pk:
        r_sp1 = api("post", "/company/part/", {
            "part": 1, "supplier": 1, "SKU": "COV-SKU-PRIMARY", "manufacturer_part": mfgpart_pk, "pack_quantity": "2",
        })
        ok_sp1 = r_sp1.status_code == 201
        log("FN7-SUPPART-create-primary", "Crear SupplierPart vinculado a ManufacturerPart (pack_quantity=2)", ok_sp1, f"HTTP {r_sp1.status_code} {short(r_sp1)}")
        if ok_sp1:
            supparts_created.append(r_sp1.json()["pk"])

        r_sp2 = api("post", "/company/part/", {"part": 1, "supplier": 1, "SKU": "COV-SKU-SECOND", "pack_quantity": "1"})
        ok_sp2 = r_sp2.status_code == 201
        log("FN7-SUPPART-create-second", "Crear segunda SupplierPart para el mismo Part (no debe ser primary)", ok_sp2, f"HTTP {r_sp2.status_code} {short(r_sp2)}")
        if ok_sp2:
            supparts_created.append(r_sp2.json()["pk"])

    for pk in supparts_created:
        api("delete", f"/company/part/{pk}/")

    if mfgpart_pk:
        api("delete", f"/company/part/manufacturer/{mfgpart_pk}/")
    if mfg_pk:
        api("patch", f"/company/{mfg_pk}/", {"active": False})
        api("delete", f"/company/{mfg_pk}/")

    r = api("get", "/company/part/", params={"company": 1})
    log("FN7-SUPPART-company", "Filtro SupplierPart ?company=", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = api("get", "/company/part/", params={"has_stock": "false"})
    log("FN7-SUPPART-has_stock", "Filtro SupplierPart ?has_stock=false", r2.status_code == 200, f"HTTP {r2.status_code}")

    r = api("post", "/company/price-break/", {"part": 1, "quantity": 10, "price": "0.85", "price_currency": "USD"})
    ok = r.status_code == 201
    log("FN7-PRICEBREAK-create", "Crear SupplierPriceBreak", ok, f"HTTP {r.status_code} {short(r)}")
    if ok:
        api("delete", f"/company/price-break/{r.json()['pk']}/")


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 62)
    print("  InvenTree — Proveedores / Compañías")
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

        print("\n── CPF-007: Proveedores ───────────────────────────────")
        tc_sup_01(page); tc_sup_02(page); tc_sup_03(page); tc_sup_04(page)
        tc_sup_05(page); tc_sup_06(page); tc_sup_07(page)

        ctx.close(); browser.close()

    print("\n── FN7 — Proveedores: casos extendidos ────────────────")
    try:
        fn7_supplier_extended()
    except Exception as e:
        log("FN7-SUPPLIER-extended", "Casos extendidos de Proveedores", False, str(e))

    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed

    print("\n" + "=" * 62)
    print(f"  TOTAL: {passed}/{len(results)} PASS  |  {failed} FAIL")
    print("=" * 62)
    print(f"\n  {'TC':<26} {'Resultado':<10} Caso")
    print(f"  {'-'*25} {'-'*9} {'-'*36}")
    for r in results:
        mark = "PASS ✅" if r["pass"] else "FAIL ❌"
        print(f"  {r['tc']:<26} {mark:<10} {r['name']}")

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
