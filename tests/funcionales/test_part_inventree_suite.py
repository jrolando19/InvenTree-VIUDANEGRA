#!/usr/bin/env python3
"""
InvenTree — Suite funcional: Partes (test_part_inventree_suite.py)
FN1  Gestión de Partes      (RF-002, Hito 2)
FN6  Categorías de Partes   (RF-... , Hito 2)
FN5  BOM (Lista de Materiales) (Hito 2)

Incluye:
  TC-P01..P08    — CRUD de partes (API + UI)
  TC-CAT-01..07  — Categorías de partes
  TC-BOM-01..08  — Ítems de BOM
  FN1-*          — Casos extendidos de cobertura (filtros, pricing, stocktake,
                   test-templates, related parts, revisiones, IPN regex, etc.)

Prerrequisitos en BD (setup_system_tests.py):
  - Part pk=1 (Resistencia 10k, assembly=False)
  - Part pk=5 (PCB Sensor v1, assembly=True, BOM con 3 ítems)
  - Part pk=10 (Módulo Ensamble Test, assembly=True, sin BOM)
  - PartCategory pk=1 (Electrónicos)
"""
import os, sys, json, time, requests
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE   = "http://localhost:8000"
API    = f"{BASE}/api"
USER   = "admin"
PASS   = "inventree"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SS_DIR       = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "part")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "test_output", "results", "part_results.json")
os.makedirs(SS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

ASSEMBLY_PK      = 5   # PCB Sensor v1 (con BOM)
NON_ASSEMBLY_PK  = 1   # Resistencia 10k

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
    kw = {"auth": (USER, PASS)} if auth else {}
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
    s.get(f"{API}/auth/v1/config", auth=(USER, PASS))
    csrf = s.cookies.get("csrftoken", "")
    s.post(f"{API}/auth/v1/auth/login",
           json={"username": USER, "password": PASS},
           headers={"X-CSRFToken": csrf, "Referer": BASE})
    return s, s.cookies.get("csrftoken", csrf)

# ══════════════════════════════════════════════════════════════
# CPF-001 — PARTES: CRUD (API + UI)
# ══════════════════════════════════════════════════════════════

def tc_partes_flow(page):
    """TC-P01..P08 — Ciclo CRUD completo de una parte."""
    created_pk = None

    r = api("get", "/part/", params={"format": "json"})
    data = r.json()
    count = len(data) if isinstance(data, list) else data.get("count", 0)
    log("TC-P01", "Listar partes (GET /api/part/)", r.status_code == 200, f"HTTP {r.status_code} — {count} partes en BD")

    page.goto(f"{BASE}/web/part/", wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    snap(page, "TC-P02_list_parts_ui")
    on_parts = "/part" in page.url and "/login" not in page.url
    log("TC-P02", "Listar partes (UI /web/part/)", on_parts, f"URL: {page.url}")

    r = api("post", "/part/", {
        "name": "Parte Prueba Funcional", "description": "Creada por suite de pruebas automatizadas", "active": True,
    })
    ok = r.status_code in (200, 201)
    if ok:
        created_pk = r.json().get("pk")
    log("TC-P03", "Crear parte (POST /api/part/)", ok, f"HTTP {r.status_code} — ID: {created_pk}")

    if created_pk:
        r = api("get", f"/part/{created_pk}/", params={"format": "json"})
        ok = r.status_code == 200
        name = r.json().get("name", "") if ok else ""
        log("TC-P04", "Ver detalle de parte (GET /api/part/{id}/)", ok, f"HTTP {r.status_code} — nombre: '{name}'")

        page.goto(f"{BASE}/web/part/{created_pk}/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        snap(page, "TC-P04_part_detail_ui")
        on_part = str(created_pk) in page.url and "/login" not in page.url
        log("TC-P04b", "Ver detalle de parte (UI /web/part/{id}/)", on_part, f"URL: {page.url}")
    else:
        log("TC-P04", "Ver detalle de parte (GET /api/part/{id}/)", False, "TC-P03 falló")

    if created_pk:
        r = api("patch", f"/part/{created_pk}/", {"description": "Descripción editada por prueba funcional"})
        ok = r.status_code in (200, 201)
        new_desc = r.json().get("description", "") if ok else ""
        log("TC-P05", "Editar parte (PATCH /api/part/{id}/)", ok, f"HTTP {r.status_code} — '{new_desc[:60]}'")
    else:
        log("TC-P05", "Editar parte (PATCH /api/part/{id}/)", False, "TC-P03 falló")

    r = api("get", "/part/", params={"search": "Prueba", "format": "json"})
    data = r.json()
    found = len(data) if isinstance(data, list) else data.get("count", 0)
    ok = r.status_code == 200 and found > 0
    log("TC-P06", "Buscar partes (?search=Prueba)", ok, f"HTTP {r.status_code} — {found} resultado(s)")

    if created_pk:
        r_deact = api("patch", f"/part/{created_pk}/", {"active": False})
        r_del = api("delete", f"/part/{created_pk}/")
        r_check = api("get", f"/part/{created_pk}/", params={"format": "json"})
        ok = r_del.status_code in (200, 204) and r_check.status_code == 404
        log("TC-P07", "Eliminar parte (PATCH deactivate → DELETE)", ok,
            f"Deactivate:{r_deact.status_code} DELETE:{r_del.status_code} GET:{r_check.status_code}")
    else:
        log("TC-P07", "Eliminar parte", False, "TC-P03 falló")

    r = requests.get(f"{API}/part/", params={"format": "json"})
    ok = r.status_code in (401, 403)
    log("TC-P08", "Acceso sin autenticación rechazado", ok, f"HTTP {r.status_code}")


# ══════════════════════════════════════════════════════════════
# CPF-006 — CATEGORÍAS DE PARTES
# ══════════════════════════════════════════════════════════════

def _extract_list(data):
    """/part/category/ devuelve una lista plana, no {'results': [...]}."""
    if isinstance(data, dict):
        return data.get("results", [])
    if isinstance(data, list):
        return data
    return []

def cleanup_cats(names):
    """Elimina categorías de prueba por nombre."""
    for name in names:
        r = requests.get(f"{API}/part/category/", params={"search": name, "format": "json"}, auth=(USER, PASS))
        for c in _extract_list(r.json()):
            if c.get("name") == name:
                requests.delete(f"{API}/part/category/{c['pk']}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))

def tc_cat_01(page):
    """FN6-CP-001 — Crear categoría raíz válida."""
    cleanup_cats(["Componentes Electrónicos TC"])
    r = api("post", "/part/category/", {
        "name": "Componentes Electrónicos TC",
        "description": "Resistencias, condensadores y LEDs"
    })
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    page.goto(f"{BASE}/web/part/category/index/subcategories", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-CAT-01_root_category")
    log("TC-CAT-01", "Crear categoría raíz válida", ok,
        f"HTTP {r.status_code} | pk={pk} | name={r.json().get('name') if ok else r.json()}")
    if pk: requests.delete(f"{API}/part/category/{pk}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))

def tc_cat_02(page):
    """FN6-CP-002 — Nombre vacío → 400."""
    r = api("post", "/part/category/", {"name": "", "description": "sin nombre"})
    ok = r.status_code in (400, 422)
    snap(page, "TC-CAT-02_empty_name")
    log("TC-CAT-02", "Crear categoría sin nombre (campo requerido)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")

def tc_cat_03(page):
    """FN6-CP-003 — Nombre 101 chars → 400."""
    r = api("post", "/part/category/", {"name": "C" * 101, "description": "test"})
    ok = r.status_code in (400, 422)
    snap(page, "TC-CAT-03_name_101")
    log("TC-CAT-03", "LÍMITE — nombre 101 caracteres (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")

def tc_cat_04(page):
    """FN6-CP-004 — Nombre duplicado en mismo nivel."""
    cleanup_cats(["Cat Duplicada TC"])
    r1 = api("post", "/part/category/", {"name": "Cat Duplicada TC"})
    pk1 = r1.json().get("pk") if r1.status_code == 201 else None
    r2 = api("post", "/part/category/", {"name": "Cat Duplicada TC"})
    rejected = r2.status_code in (400, 422)
    ok = rejected
    snap(page, "TC-CAT-04_duplicate_name")
    note = "RECHAZADO ✅" if rejected else f"ACEPTADO (HTTP {r2.status_code}) — comportamiento permisivo"
    log("TC-CAT-04", "Nombre duplicado en mismo nivel", ok,
        f"1er POST {r1.status_code} | 2do POST {r2.status_code} [{note}]")
    for pk in [pk1, r2.json().get("pk") if r2.status_code == 201 else None]:
        if pk: requests.delete(f"{API}/part/category/{pk}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))

def tc_cat_05(page):
    """FN6-CP-005 — Subcategoría con padre existente."""
    cleanup_cats(["Electrónicos Padre TC", "Pasivos TC"])
    r_parent = api("post", "/part/category/", {"name": "Electrónicos Padre TC"})
    pk_parent = r_parent.json().get("pk") if r_parent.status_code == 201 else None
    if not pk_parent:
        log("TC-CAT-05", "Crear subcategoría con padre", False, "No se pudo crear padre"); return

    r = api("post", "/part/category/", {"name": "Pasivos TC", "parent": pk_parent})
    ok = r.status_code == 201 and r.json().get("parent") == pk_parent
    pk_child = r.json().get("pk") if r.status_code == 201 else None
    page.goto(f"{BASE}/web/part/category/{pk_parent}/subcategories", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-CAT-05_subcategory")
    log("TC-CAT-05", "Crear subcategoría con padre existente", ok,
        f"HTTP {r.status_code} | child_pk={pk_child} | parent={r.json().get('parent') if r.status_code==201 else 'N/A'}")

    # PartCategoryDetail.update() con 'starred' -> ejercita self.get_object().set_starred()
    r_star = requests.patch(f"{API}/part/category/{pk_parent}/", json={"starred": True}, auth=(USER, PASS))
    log("COV-CAT-starred", "PATCH categoría con starred=True", r_star.status_code == 200, f"HTTP {r_star.status_code}")

    for pk in [pk_child, pk_parent]:
        if pk: requests.delete(f"{API}/part/category/{pk}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))

def tc_cat_06(page):
    """FN6-CP-006 — Nombre mínimo 1 carácter."""
    cleanup_cats(["X"])
    r = api("post", "/part/category/", {"name": "X"})
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    snap(page, "TC-CAT-06_min_name")
    log("TC-CAT-06", "LÍMITE — nombre mínimo 'X' (1 carácter)", ok,
        f"HTTP {r.status_code} | pk={pk}")
    if pk: requests.delete(f"{API}/part/category/{pk}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))

def tc_cat_07(page):
    """FN6-CP-007 — Descripción 251 caracteres."""
    r = api("post", "/part/category/", {"name": "CatDescLarga TC", "description": "D" * 251})
    ok = r.status_code in (400, 422)
    pk = r.json().get("pk") if r.status_code == 201 else None
    snap(page, "TC-CAT-07_desc_251")
    log("TC-CAT-07", "LÍMITE — descripción 251 caracteres (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:120]}")
    if pk: requests.delete(f"{API}/part/category/{pk}/", json={"delete_parts": False, "delete_child_categories": False}, auth=(USER, PASS))


# ══════════════════════════════════════════════════════════════
# CPF-005 — BOM (Lista de Materiales)
# ══════════════════════════════════════════════════════════════

def _bom_cleanup(part_pk, sub_part_pk):
    r2 = requests.get(f"{API}/bom/", params={"part": part_pk, "format": "json"}, auth=(USER, PASS))
    for item in (r2.json().get("results", []) if isinstance(r2.json(), dict) else []):
        if item.get("sub_part") == sub_part_pk:
            api("delete", f"/bom/{item['pk']}/")

def tc_bom_01(page):
    """FN5-CP-001 — Agregar ítem al BOM (parte assembly=5, sub=1, qty=4, attrition=5)."""
    _bom_cleanup(ASSEMBLY_PK, NON_ASSEMBLY_PK)
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": NON_ASSEMBLY_PK,
                               "quantity": 4, "attrition": 5})
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    page.goto(f"{BASE}/web/part/{ASSEMBLY_PK}/bom", wait_until="networkidle", timeout=20000)
    time.sleep(2); snap(page, "TC-BOM-01_add_bom_item")
    log("TC-BOM-01", "Agregar ítem al BOM (qty=4, attrition=5%)", ok,
        f"HTTP {r.status_code} | pk={pk} | qty={r.json().get('quantity') if ok else 'N/A'}")
    if pk: api("delete", f"/bom/{pk}/")

def tc_bom_02(page):
    """FN5-CP-002 — Referencia circular (part=5, sub_part=5) → 400."""
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": ASSEMBLY_PK, "quantity": 1})
    ok = r.status_code in (400, 422)
    snap(page, "TC-BOM-02_circular_ref")
    log("TC-BOM-02", "Referencia circular en BOM (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_bom_03(page):
    """FN5-CP-003 — Qty=0 → 400."""
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 2, "quantity": 0})
    ok = r.status_code in (400, 422)
    snap(page, "TC-BOM-03_qty_zero")
    log("TC-BOM-03", "BOM ítem qty=0 (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_bom_04(page):
    """FN5-CP-004 — Attrition negativo → 400."""
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 3, "quantity": 2, "attrition": -10})
    ok = r.status_code in (400, 422)
    snap(page, "TC-BOM-04_neg_attrition")
    log("TC-BOM-04", "BOM attrition negativo -10% (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")

def tc_bom_05(page):
    """FN5-CP-005 — Qty mínima decimal 0.001."""
    _bom_cleanup(ASSEMBLY_PK, 2)
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 2, "quantity": 0.001})
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    snap(page, "TC-BOM-05_min_qty")
    log("TC-BOM-05", "LÍMITE — BOM qty mínima 0.001", ok,
        f"HTTP {r.status_code} | qty={r.json().get('quantity') if ok else r.json()}")
    if pk: api("delete", f"/bom/{pk}/")

def tc_bom_06(page):
    """FN5-CP-006 — Attrition máximo 100%."""
    _bom_cleanup(ASSEMBLY_PK, 3)
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 3, "quantity": 1, "attrition": 100})
    ok = r.status_code == 201
    pk = r.json().get("pk") if ok else None
    snap(page, "TC-BOM-06_max_attrition")
    log("TC-BOM-06", "LÍMITE — BOM attrition máximo 100%", ok,
        f"HTTP {r.status_code} | attrition={r.json().get('attrition') if ok else r.json()}")
    if pk: api("delete", f"/bom/{pk}/")

def tc_bom_07(page):
    """FN5-CP-007 — Referencia 501 chars → 400."""
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 2, "quantity": 1,
                               "reference": "R" * 501})
    ok = r.status_code in (400, 422)
    snap(page, "TC-BOM-07_ref_501")
    log("TC-BOM-07", "LÍMITE — BOM referencia 501 caracteres (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")
    if r.status_code == 201: api("delete", f"/bom/{r.json()['pk']}/")

def tc_bom_08(page):
    """FN5-CP-008 — Sub-part inexistente (pk=9999) → 400."""
    r = api("post", "/bom/", {"part": ASSEMBLY_PK, "sub_part": 9999, "quantity": 1})
    ok = r.status_code in (400, 422)
    snap(page, "TC-BOM-08_invalid_subpart")
    log("TC-BOM-08", "BOM sub-part inexistente (debe rechazar)", ok,
        f"HTTP {r.status_code} | {str(r.json())[:150]}")


# ══════════════════════════════════════════════════════════════
# FN1 — Gestión de Partes: casos extendidos de cobertura
# Filtros de querystring y endpoints secundarios (categorías, pricing,
# stocktake, test-templates, BOM, related parts, revisiones, IPN regex).
# ══════════════════════════════════════════════════════════════

def fn1_cat_filters():
    cases = [
        ("starred", {"starred": "true"}), ("depth", {"depth": 0}),
        ("top_level", {"top_level": "true"}), ("cascade", {"cascade": "false"}),
        ("parent", {"parent": 1}), ("exclude_tree", {"exclude_tree": 1}),
    ]
    for name, params in cases:
        r = api("get", "/part/category/", params=params)
        log(f"FN1-CAT-{name}", f"Filtro categoría ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

def fn1_cat_tree():
    r = api("get", "/part/category/tree/")
    log("FN1-CAT-tree", "Árbol de categorías", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = api("get", "/part/category/tree/", params={"max_level": 1})
    log("FN1-CAT-tree-maxlevel", "Árbol ?max_level=1", r2.status_code == 200, f"HTTP {r2.status_code}")

def fn1_cat_parameter_template():
    r = api("post", "/parameter/template/", {"name": "COV-Param-Template", "units": "", "model_type": "part"})
    tpl_pk = r.json().get("pk") if r.status_code == 201 else None
    log("FN1-CAT-param-tpl-create", "Crear ParameterTemplate base", r.status_code in (200, 201), f"HTTP {r.status_code} {short(r)}")
    if tpl_pk:
        r2 = api("post", "/part/category/parameters/", {"category": 1, "template": tpl_pk, "default_value": "N/A"})
        ok2 = r2.status_code == 201
        log("FN1-CAT-param-create", "Crear CategoryParameterTemplate", ok2, f"HTTP {r2.status_code} {short(r2)}")
        cpt_pk = r2.json().get("pk") if ok2 else None
        r3 = api("get", "/part/category/parameters/")
        log("FN1-CAT-param-list", "Listar CategoryParameterTemplate", r3.status_code == 200, f"HTTP {r3.status_code}")
        if cpt_pk:
            api("delete", f"/part/category/parameters/{cpt_pk}/")
        api("delete", f"/parameter/template/{tpl_pk}/")

def fn1_part_filters():
    cases = [
        ("is_variant", {"is_variant": "false"}), ("is_revision", {"is_revision": "false"}),
        ("has_revisions", {"has_revisions": "false"}), ("has_units", {"has_units": "false"}),
        ("has_ipn", {"has_ipn": "false"}), ("low_stock", {"low_stock": "true"}),
        ("high_stock", {"high_stock": "true"}), ("has_stock", {"has_stock": "true"}),
        ("unallocated_stock", {"unallocated_stock": "true"}), ("exclude_tree", {"exclude_tree": 3}),
        ("ancestor", {"ancestor": 3}), ("variant_of", {"variant_of": 5}),
        ("in_bom", {"in_bom": 5}), ("has_pricing", {"has_pricing": "false"}),
        ("stock_to_build", {"stock_to_build": "true"}), ("depleted_stock", {"depleted_stock": "true"}),
        ("starred", {"starred": "true"}), ("related_parts", {"related_parts": 1}),
        ("exclude_related", {"exclude_related": 1}), ("cascade", {"cascade": "true", "category": 1}),
        ("category", {"category": 1}), ("convert_from", {"convert_from": 1}),
    ]
    for name, params in cases:
        r = api("get", "/part/", params=params)
        log(f"FN1-PART-{name}", f"Filtro parte ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

def fn1_part_secondary():
    r_options = requests.options(f"{API}/part/", auth=(USER, PASS))
    log("FN1-PART-options", "OPTIONS /api/part/ (metadata de API)", r_options.status_code == 200, f"HTTP {r_options.status_code}")

    # PART_IPN_REGEX: patrón de IPN requerido -> Part.validate_ipn() valida contra regex
    r_ipnset = api("patch", "/settings/global/PART_IPN_REGEX/", {"value": "^COV-"})
    if r_ipnset.status_code == 200:
        r_ipnbad = api("post", "/part/", {"name": "COV IPN Bad", "description": "x", "category": 1, "IPN": "BAD-IPN-1"})
        log("FN1-PART-ipn-regex-reject", "IPN que no matchea PART_IPN_REGEX (debe rechazar)", r_ipnbad.status_code in (400, 422), f"HTTP {r_ipnbad.status_code} {short(r_ipnbad)}")

        r_ipnok = api("post", "/part/", {"name": "COV IPN Good", "description": "x", "category": 1, "IPN": "COV-IPN-OK-1"})
        ok_ipn = r_ipnok.status_code == 201
        log("FN1-PART-ipn-regex-accept", "IPN que sí matchea PART_IPN_REGEX", ok_ipn, f"HTTP {r_ipnok.status_code} {short(r_ipnok)}")
        if ok_ipn:
            ipn_pk = r_ipnok.json()["pk"]
            api("patch", f"/part/{ipn_pk}/", {"active": False})
            api("delete", f"/part/{ipn_pk}/")
        api("patch", "/settings/global/PART_IPN_REGEX/", {"value": ""})

    # Nombre+IPN+revisión duplicados -> Part.validate_unique() / clean()
    r_dup1 = api("post", "/part/", {"name": "COV Dup Part", "description": "x", "category": 1, "IPN": "COV-DUP-1"})
    if r_dup1.status_code == 201:
        dup_pk = r_dup1.json()["pk"]
        r_dup2 = api("post", "/part/", {"name": "COV Dup Part", "description": "x", "category": 1, "IPN": "COV-DUP-1"})
        log("FN1-PART-duplicate", "Parte con name+IPN+revision duplicados (debe rechazar)", r_dup2.status_code in (400, 422), f"HTTP {r_dup2.status_code} {short(r_dup2)}")
        api("patch", f"/part/{dup_pk}/", {"active": False})
        api("delete", f"/part/{dup_pk}/")

    r = api("get", "/part/5/requirements/")
    log("FN1-PART-requirements", "Requirements de pk=5", r.status_code == 200, f"HTTP {r.status_code}")

    # existing_image inexistente -> validate_existing_image() ejercita get_part_image_directory()
    # y la rama de archivo-no-encontrado (debe rechazar)
    r_img = api("post", "/part/", {"name": "COV Img Part", "description": "x", "category": 1, "existing_image": "no_existe_este_archivo.jpg"})
    log("FN1-PART-existing-image", "Crear parte con existing_image inexistente (debe rechazar)", r_img.status_code in (400, 422), f"HTTP {r_img.status_code} {short(r_img)}")

    # validate_revision(): crear una parte como "revisión" de pk=5 (assembly) -> recorre
    # las validaciones de revision_of/revision/variant_of en Part.validate_revision()
    r_rev = api("post", "/part/", {
        "name": "COV Revision Part", "description": "Revision de pk=5", "category": 1,
        "revision_of": 5, "revision": "B", "assembly": True,
    })
    ok_rev = r_rev.status_code == 201
    log("FN1-PART-revision-create", "Crear Part como revisión de pk=5", ok_rev, f"HTTP {r_rev.status_code} {short(r_rev)}")
    if ok_rev:
        rev_pk = r_rev.json()["pk"]
        api("patch", f"/part/{rev_pk}/", {"active": False})
        api("delete", f"/part/{rev_pk}/")

    # revision_of apuntando a sí mismo (vía update) -> debe rechazar
    r_rev2 = api("post", "/part/", {"name": "COV Revision Self", "description": "x", "category": 1, "revision": "C"})
    if r_rev2.status_code == 201:
        self_pk = r_rev2.json()["pk"]
        r_self = api("patch", f"/part/{self_pk}/", {"revision_of": self_pk})
        log("FN1-PART-revision-self", "Parte como revisión de sí misma (debe rechazar)", r_self.status_code in (400, 422), f"HTTP {r_self.status_code} {short(r_self)}")
        api("patch", f"/part/{self_pk}/", {"active": False})
        api("delete", f"/part/{self_pk}/")

    r = api("get", "/part/5/pricing/")
    log("FN1-PART-pricing-get", "Pricing detail de pk=5", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = api("patch", "/part/5/pricing/", {"override_min": "10.00"})
    log("FN1-PART-pricing-patch", "PATCH pricing override_min", r2.status_code in (200, 400), f"HTTP {r2.status_code}")

    r = api("get", "/part/5/serial-numbers/")
    log("FN1-PART-serials", "Serial-numbers de parte no trackable", r.status_code in (200, 400), f"HTTP {r.status_code}")

    r = api("post", "/part/10/bom-copy/", {"part": 5, "remove_existing": False})
    log("FN1-PART-bom-copy", "Copiar BOM de pk=5 hacia pk=10", r.status_code in (200, 201), f"HTTP {r.status_code} {short(r)}")
    r_bom = requests.get(f"{API}/bom/", params={"part": 10, "format": "json"}, auth=(USER, PASS))
    for item in extract_list(r_bom.json()):
        api("delete", f"/bom/{item['pk']}/")

    r = api("put", "/part/5/bom-validate/", {"valid": True})
    log("FN1-PART-bom-validate", "Validar BOM de pk=5", r.status_code in (200, 202, 404), f"HTTP {r.status_code}")

    r = api("get", "/part/thumbs/")
    log("FN1-PART-thumbs", "Listar thumbnails de partes", r.status_code == 200, f"HTTP {r.status_code}")

def fn1_part_test_template():
    r_existing = requests.get(f"{API}/part/", params={"name": "COV Testable Part", "format": "json"}, auth=(USER, PASS))
    for item in extract_list(r_existing.json()):
        if item.get("name") == "COV Testable Part":
            api("patch", f"/part/{item['pk']}/", {"active": False})
            api("delete", f"/part/{item['pk']}/")

    r_tp = api("post", "/part/", {
        "name": "COV Testable Part", "description": "Parte temporal coverage test-templates",
        "category": 1, "testable": True, "active": True,
    })
    testable_pk = r_tp.json().get("pk") if r_tp.status_code == 201 else None
    if not testable_pk:
        log("FN1-PART-testtpl-create", "Crear PartTestTemplate", False, f"No se pudo crear parte testable: HTTP {r_tp.status_code}")
        return

    r = api("post", "/part/test-template/", {
        "part": testable_pk, "test_name": "COV Continuity Test",
        "description": "Chequeo de continuidad (coverage)", "required": True,
    })
    ok = r.status_code == 201
    log("FN1-PART-testtpl-create", "Crear PartTestTemplate en parte testable", ok, f"HTTP {r.status_code} {short(r)}")
    pk = r.json().get("pk") if ok else None

    r2 = api("get", "/part/test-template/", params={"part": testable_pk})
    log("FN1-PART-testtpl-list", "Listar test-templates ?part=", r2.status_code == 200, f"HTTP {r2.status_code}")

    if pk:
        api("delete", f"/part/test-template/{pk}/")
    api("patch", f"/part/{testable_pk}/", {"active": False})
    api("delete", f"/part/{testable_pk}/")

def fn1_part_related_stocktake_price():
    r = api("post", "/part/related/", {"part_1": 1, "part_2": 2})
    ok = r.status_code == 201
    log("FN1-PART-related-create", "Crear PartRelated (1<->2)", ok, f"HTTP {r.status_code} {short(r)}")
    pk = r.json().get("pk") if ok else None
    if pk:
        r_rel = api("get", "/part/", params={"related": 1})
        log("FN1-PART-filter-related", "Filtro /part/ ?related=1 (con relación activa)", r_rel.status_code == 200, f"HTTP {r_rel.status_code}")
        r_exrel = api("get", "/part/", params={"exclude_related": 1})
        log("FN1-PART-filter-exclude_related", "Filtro /part/ ?exclude_related=1", r_exrel.status_code == 200, f"HTTP {r_exrel.status_code}")
        api("delete", f"/part/related/{pk}/")

    r = api("post", "/part/stocktake/", {"part": 1, "quantity": 100, "item_count": 5})
    ok = r.status_code == 201
    detail = f"HTTP {r.status_code} {short(r)}"
    if r.status_code == 500:
        detail += "  [DEFECTO CONFIRMADO: PartStocktakeSerializer.Meta.read_only_fields incluye 'user', que no existe en el modelo -> 500 en todo POST]"
    log("FN1-PART-stocktake-create", "Crear PartStocktake para pk=1", ok, detail)

    r = api("post", "/part/sale-price/", {"part": 5, "quantity": 1, "price": "12.50", "price_currency": "USD"})
    ok = r.status_code == 201
    log("FN1-PART-saleprice-create", "Crear sale price break para pk=5", ok, f"HTTP {r.status_code}")
    saleprice_pk = r.json().get("pk") if ok else None

    r = api("post", "/part/internal-price/", {"part": 1, "quantity": 1, "price": "0.50", "price_currency": "USD"})
    ok = r.status_code == 201
    log("FN1-PART-intprice-create", "Crear internal price break para pk=1", ok, f"HTTP {r.status_code} {short(r)}")
    intprice_pk = r.json().get("pk") if ok else None

    # PATCH /part/<pk>/pricing/ {"update": true} llama a PartPricing.update_pricing()
    # de forma SÍNCRONA (no pasa por offload_task) -> cubre update_bom_cost,
    # update_purchase_cost, update_internal_cost, update_supplier_cost,
    # update_variant_cost, update_sale_cost, update_assemblies, update_templates.
    r_price5 = api("patch", "/part/5/pricing/", {"update": True})
    log("FN1-PART-pricing-update-bom", "Forzar recálculo de pricing (pk=5, con BOM)", r_price5.status_code == 200, f"HTTP {r_price5.status_code} {short(r_price5)}")

    # PART_INTERNAL_PRICE=True -> update_internal_cost() recorre internalpricebreaks
    # en vez de retornar de inmediato con la lista vacía por defecto.
    r_intset = api("patch", "/settings/global/PART_INTERNAL_PRICE/", {"value": "True"})
    r_price1 = api("patch", "/part/1/pricing/", {"update": True})
    log("FN1-PART-pricing-update-purchase", "Forzar recálculo de pricing (pk=1, purchase/internal/supplier)", r_price1.status_code == 200, f"HTTP {r_price1.status_code} {short(r_price1)}")
    if r_intset.status_code == 200:
        api("patch", "/settings/global/PART_INTERNAL_PRICE/", {"value": "False"})

    r_override = api("patch", "/part/1/pricing/", {"override_min": "1.00", "override_min_currency": "USD"})
    log("FN1-PART-pricing-override", "Override manual de precio mínimo (pk=1)", r_override.status_code == 200, f"HTTP {r_override.status_code} {short(r_override)}")

    r_override_max = api("patch", "/part/1/pricing/", {"override_max": "50.00", "override_max_currency": "USD", "update": True})
    log("FN1-PART-pricing-override-max", "Override manual de precio máximo + recálculo (pk=1)", r_override_max.status_code == 200, f"HTTP {r_override_max.status_code} {short(r_override_max)}")

    # PART_BOM_USE_INTERNAL_PRICE=True -> update_overall_cost() prioriza internal_cost sobre bom/buy
    r_bomintset = api("patch", "/settings/global/PART_BOM_USE_INTERNAL_PRICE/", {"value": "True"})
    if r_bomintset.status_code == 200:
        r_bomint_update = api("patch", "/part/5/pricing/", {"update": True})
        log("FN1-PART-pricing-bom-internal", "Recálculo con PART_BOM_USE_INTERNAL_PRICE=True", r_bomint_update.status_code == 200, f"HTTP {r_bomint_update.status_code}")
        api("patch", "/settings/global/PART_BOM_USE_INTERNAL_PRICE/", {"value": "False"})

    # Limpiar overrides para no contaminar otras pruebas
    api("patch", "/part/1/pricing/", {"override_min": None, "override_max": None})

    if saleprice_pk:
        api("delete", f"/part/sale-price/{saleprice_pk}/")
    if intprice_pk:
        api("delete", f"/part/internal-price/{intprice_pk}/")

    r2 = api("get", "/part/stocktake/", params={"part": 1})
    log("FN1-PART-stocktake-list", "Listar stocktakes ?part=1", r2.status_code == 200, f"HTTP {r2.status_code}")

    r3 = api("post", "/part/stocktake/generate/", {"part": 1, "generate_report": False, "generate_entry": True})
    log("FN1-PART-stocktake-generate", "Generar stocktake para pk=1", r3.status_code in (200, 201, 400), f"HTTP {r3.status_code} {short(r3)}")

    # STOCKTAKE_ENABLE=True -> perform_stocktake() ejecuta su lógica completa
    # (si no, retorna temprano y casi nada de stocktake.py se cubre)
    r_set = api("patch", "/settings/global/STOCKTAKE_ENABLE/", {"value": "True"})
    if r_set.status_code == 200:
        # Garantizar que pk=1 tenga stock_items > 0 para que el for-loop de
        # perform_stocktake() se ejecute (si no, el bloque de costeo se salta)
        api("post", "/stock/", {"part": 1, "quantity": 5, "location": 1})

        r4 = api("post", "/part/stocktake/generate/", {"part": 1, "generate_report": True, "generate_entry": True})
        log("FN1-PART-stocktake-generate-report", "Generar stocktake con reporte (pk=1, con stock)", r4.status_code in (200, 201, 400), f"HTTP {r4.status_code} {short(r4)}")

        r5 = api("post", "/part/stocktake/generate/", {"location": 1, "generate_report": False, "generate_entry": False})
        log("FN1-PART-stocktake-generate-location", "Generar stocktake filtrado por location=1", r5.status_code in (200, 201, 400), f"HTTP {r5.status_code} {short(r5)}")

        api("patch", "/settings/global/STOCKTAKE_ENABLE/", {"value": "False"})

def fn1_bom_filters():
    cases = [
        ("available_stock", {"available_stock": "true"}), ("on_order", {"on_order": "true"}),
        ("has_pricing", {"has_pricing": "false"}), ("category", {"category": 1}),
        ("uses", {"uses": 1}), ("part", {"part": 5}),
    ]
    for name, params in cases:
        r = api("get", "/bom/", params=params)
        log(f"FN1-BOM-{name}", f"Filtro BOM ?{name}", r.status_code == 200, f"HTTP {r.status_code}")

    r_bom = requests.get(f"{API}/bom/", params={"part": 5, "format": "json"}, auth=(USER, PASS))
    items = extract_list(r_bom.json())
    if items:
        bom_pk = items[0]["pk"]
        r = api("put", f"/bom/{bom_pk}/validate/", {"valid": True})
        log("FN1-BOM-validate", f"Validar BomItem pk={bom_pk}", r.status_code in (200, 201), f"HTTP {r.status_code}")

        r = api("post", "/bom/substitute/", {"bom_item": bom_pk, "part": 3})
        ok = r.status_code == 201
        log("FN1-BOM-substitute-create", "Crear BomItemSubstitute", ok, f"HTTP {r.status_code} {short(r)}")
        if ok:
            api("delete", f"/bom/substitute/{r.json()['pk']}/")


def fn1_coverage_extra():
    """Casos adicionales de cobertura FN1/FN5/FN6: filtros de categoría,
    validaciones de Part/BOM, creación extendida, locking."""

    # -- PartCategory: filtros --
    r_starred = api("get", "/part/category/", params={"starred": "false"})
    log("COV-CAT-starred-false", "Filtro category ?starred=false", r_starred.status_code == 200, f"HTTP {r_starred.status_code}")

    r_topfalse = api("get", "/part/category/", params={"top_level": "false"})
    log("COV-CAT-top_level-false", "Filtro category ?top_level=false", r_topfalse.status_code == 200, f"HTTP {r_topfalse.status_code}")

    r_parent_cascade = api("get", "/part/category/", params={"parent": 1, "cascade": "true"})
    log("COV-CAT-parent-cascade", "Filtro category ?parent=1&cascade=true", r_parent_cascade.status_code == 200, f"HTTP {r_parent_cascade.status_code}")

    r_parent_depth = api("get", "/part/category/", params={"parent": 1, "depth": 2})
    log("COV-CAT-parent-depth", "Filtro category ?parent=1&depth=2", r_parent_depth.status_code == 200, f"HTTP {r_parent_depth.status_code}")

    # -- PartCategory: clean() con parts (structural guard) + delete con hijos --
    r_catp = api("post", "/part/category/", {"name": "COV Cat WithParts", "description": "x"})
    catp_pk = r_catp.json().get("pk") if r_catp.status_code == 201 else None
    if catp_pk:
        r_partincat = api("post", "/part/", {"name": "COV Part In Cat", "description": "x", "category": catp_pk})
        partincat_pk = r_partincat.json().get("pk") if r_partincat.status_code == 201 else None
        if partincat_pk:
            r_structreject = api("patch", f"/part/category/{catp_pk}/", {"structural": True})
            log("COV-CAT-structural-reject", "PATCH category a structural=True con parts (debe rechazar)", r_structreject.status_code in (400, 422), f"HTTP {r_structreject.status_code}")
            api("patch", f"/part/{partincat_pk}/", {"active": False})
            api("delete", f"/part/{partincat_pk}/")

        r_catchild = api("post", "/part/category/", {"name": "COV Cat Child", "description": "x", "parent": catp_pk})
        catchild_pk = r_catchild.json().get("pk") if r_catchild.status_code == 201 else None
        r_catdel = api("delete", f"/part/category/{catp_pk}/", {"delete_child_categories": True, "delete_parts": False})
        log("COV-CAT-delete-withchildren", "DELETE category con delete_child_categories=True", r_catdel.status_code in (200, 204), f"HTTP {r_catdel.status_code}")

    # -- PartCategory: starred toggle --
    r_cat2 = api("post", "/part/category/", {"name": "COV Cat Starred", "description": "x"})
    cat2_pk = r_cat2.json().get("pk") if r_cat2.status_code == 201 else None
    if cat2_pk:
        r_star1 = api("patch", f"/part/category/{cat2_pk}/", {"starred": True})
        log("COV-CAT-starred-true", "PATCH category starred=True", r_star1.status_code == 200, f"HTTP {r_star1.status_code}")
        r_star2 = api("patch", f"/part/category/{cat2_pk}/", {"starred": True})
        log("COV-CAT-starred-true-again", "PATCH category starred=True (idempotente)", r_star2.status_code == 200, f"HTTP {r_star2.status_code}")
        r_star3 = api("patch", f"/part/category/{cat2_pk}/", {"starred": False})
        log("COV-CAT-starred-false-unset", "PATCH category starred=False", r_star3.status_code == 200, f"HTTP {r_star3.status_code}")
        api("delete", f"/part/category/{cat2_pk}/", {"delete_child_categories": True, "delete_parts": True})

    # -- Part: filtros de categoría --
    r_catnull = api("get", "/part/", params={"category": "null", "cascade": "false"})
    log("COV-PART-category-null", "Filtro part ?category=null&cascade=false", r_catnull.status_code == 200, f"HTTP {r_catnull.status_code}")

    r_catid_nocascade = api("get", "/part/", params={"category": 1, "cascade": "false"})
    log("COV-PART-category-nocascade", "Filtro part ?category=1&cascade=false", r_catid_nocascade.status_code == 200, f"HTTP {r_catid_nocascade.status_code}")

    r_catbad = api("get", "/part/", params={"category": 999999})
    log("COV-PART-category-notfound", "Filtro part ?category=999999 (inexistente)", r_catbad.status_code == 200, f"HTTP {r_catbad.status_code}")

    # -- Part: validate_unique (IPN duplicado) --
    r_ipnset = api("patch", "/settings/global/PART_ALLOW_DUPLICATE_IPN/", {"value": "False"})
    r_p1 = api("post", "/part/", {"name": "COV Dup IPN 1", "description": "x", "category": 1, "IPN": "COV-DUP-IPN-001"})
    p1_pk = r_p1.json().get("pk") if r_p1.status_code == 201 else None
    if p1_pk:
        r_p2 = api("post", "/part/", {"name": "COV Dup IPN 2", "description": "x", "category": 1, "IPN": "COV-DUP-IPN-001"})
        log("COV-PART-dup-ipn", "Crear Part con IPN duplicado (PART_ALLOW_DUPLICATE_IPN=False, debe rechazar)", r_p2.status_code in (400, 422), f"HTTP {r_p2.status_code} {short(r_p2)}")
        api("patch", f"/part/{p1_pk}/", {"active": False})
        api("delete", f"/part/{p1_pk}/")
    if r_ipnset.status_code == 200:
        api("patch", "/settings/global/PART_ALLOW_DUPLICATE_IPN/", {"value": "True"})

    # -- Part: clean() categoria structural --
    r_catstruct = api("post", "/part/category/", {"name": "COV Cat Structural", "description": "x", "structural": True})
    catstruct_pk = r_catstruct.json().get("pk") if r_catstruct.status_code == 201 else None
    if catstruct_pk:
        r_partstruct = api("post", "/part/", {"name": "COV Part In Structural", "description": "x", "category": catstruct_pk})
        log("COV-PART-category-structural-reject", "Crear Part en category structural (debe rechazar)", r_partstruct.status_code in (400, 422), f"HTTP {r_partstruct.status_code}")
        api("delete", f"/part/category/{catstruct_pk}/", {"delete_child_categories": True, "delete_parts": True})

    # -- Part: delete guards (locked, active) --
    r_lockset = api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "True"})
    r_plock = api("post", "/part/", {"name": "COV Locked Part", "description": "x", "category": 1})
    plock_pk = r_plock.json().get("pk") if r_plock.status_code == 201 else None
    if plock_pk:
        api("patch", f"/part/{plock_pk}/", {"locked": True})
        r_dellock = api("delete", f"/part/{plock_pk}/")
        log("COV-PART-delete-locked", "DELETE part locked=True (debe rechazar)", r_dellock.status_code in (400, 422), f"HTTP {r_dellock.status_code}")
        api("patch", f"/part/{plock_pk}/", {"locked": False})
        api("patch", f"/part/{plock_pk}/", {"active": False})
        api("delete", f"/part/{plock_pk}/")
    if r_lockset.status_code == 200:
        api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "False"})

    r_pactive = api("post", "/part/", {"name": "COV Active Part Del", "description": "x", "category": 1, "active": True})
    pactive_pk = r_pactive.json().get("pk") if r_pactive.status_code == 201 else None
    if pactive_pk:
        r_delactive = api("delete", f"/part/{pactive_pk}/")
        log("COV-PART-delete-active", "DELETE part active=True (debe rechazar)", r_delactive.status_code in (400, 422), f"HTTP {r_delactive.status_code}")
        api("patch", f"/part/{pactive_pk}/", {"active": False})
        api("delete", f"/part/{pactive_pk}/")

    # -- Part: starred toggle --
    r_pstar = api("post", "/part/", {"name": "COV Starred Part", "description": "x", "category": 1})
    pstar_pk = r_pstar.json().get("pk") if r_pstar.status_code == 201 else None
    if pstar_pk:
        r_pstar1 = api("patch", f"/part/{pstar_pk}/", {"starred": True})
        log("COV-PART-starred-true", "PATCH part starred=True", r_pstar1.status_code == 200, f"HTTP {r_pstar1.status_code}")
        r_pstar2 = api("patch", f"/part/{pstar_pk}/", {"starred": False})
        log("COV-PART-starred-false", "PATCH part starred=False", r_pstar2.status_code == 200, f"HTTP {r_pstar2.status_code}")
        api("patch", f"/part/{pstar_pk}/", {"active": False})
        api("delete", f"/part/{pstar_pk}/")

    # -- Part: create con initial_stock/duplicate --
    r_initstock = api("post", "/part/", {
        "name": "COV InitStock Part", "description": "x", "category": 1,
        "initial_stock": {"quantity": 10, "location": 1},
    })
    ok_initstock = r_initstock.status_code == 201
    log("COV-PART-create-initialstock", "POST /part/ con initial_stock", ok_initstock, f"HTTP {r_initstock.status_code} {short(r_initstock)}")
    if ok_initstock:
        api("patch", f"/part/{r_initstock.json()['pk']}/", {"active": False})
        api("delete", f"/part/{r_initstock.json()['pk']}/")

    r_dup = api("post", "/part/", {
        "name": "COV Duplicate Part", "description": "x", "category": 1,
        "duplicate": {"original": 5, "copy_bom": True, "copy_notes": True, "copy_parameters": True},
    })
    ok_dup = r_dup.status_code == 201
    log("COV-PART-create-duplicate", "POST /part/ con duplicate.copy_bom/copy_notes/copy_parameters", ok_dup, f"HTTP {r_dup.status_code} {short(r_dup)}")
    if ok_dup:
        api("patch", f"/part/{r_dup.json()['pk']}/", {"active": False})
        api("delete", f"/part/{r_dup.json()['pk']}/")

    # -- Part: create con duplicate.copy_tests (Part.copy_tests_from) --
    r_srctest = api("post", "/part/", {"name": "COV Copy Tests Src", "description": "x", "category": 1, "testable": True, "active": True})
    srctest_pk = r_srctest.json().get("pk") if r_srctest.status_code == 201 else None
    if srctest_pk:
        api("post", "/part/test-template/", {"part": srctest_pk, "test_name": "COV Copy Test", "description": "x", "required": True})
        r_duptest = api("post", "/part/", {
            "name": "COV Duplicate Tests Part", "description": "x", "category": 1, "testable": True,
            "duplicate": {"original": srctest_pk, "copy_tests": True},
        })
        ok_duptest = r_duptest.status_code == 201
        log("COV-PART-create-duplicate-tests", "POST /part/ con duplicate.copy_tests", ok_duptest, f"HTTP {r_duptest.status_code} {short(r_duptest)}")
        if ok_duptest:
            api("patch", f"/part/{r_duptest.json()['pk']}/", {"active": False})
            api("delete", f"/part/{r_duptest.json()['pk']}/")
        api("patch", f"/part/{srctest_pk}/", {"active": False})
        api("delete", f"/part/{srctest_pk}/")

    # -- Part: create con copy_category_parameters=True --
    r_ptpl = api("post", "/parameter/template/", {"name": "COV Cat Param Tpl", "units": "", "model_type": "part"})
    ptpl_pk = r_ptpl.json().get("pk") if r_ptpl.status_code == 201 else None
    if ptpl_pk:
        r_cpt = api("post", "/part/category/parameters/", {"category": 1, "template": ptpl_pk, "default_value": "N/A"})
        cpt_pk = r_cpt.json().get("pk") if r_cpt.status_code == 201 else None
        r_catparamcopy = api("post", "/part/", {
            "name": "COV CatParam Copy Part", "description": "x", "category": 1, "copy_category_parameters": True,
        })
        ok_catparamcopy = r_catparamcopy.status_code == 201
        log("COV-PART-create-copycatparams", "POST /part/ con copy_category_parameters=True", ok_catparamcopy, f"HTTP {r_catparamcopy.status_code} {short(r_catparamcopy)}")
        if ok_catparamcopy:
            api("patch", f"/part/{r_catparamcopy.json()['pk']}/", {"active": False})
            api("delete", f"/part/{r_catparamcopy.json()['pk']}/")
        if cpt_pk:
            api("delete", f"/part/category/parameters/{cpt_pk}/")
        api("delete", f"/parameter/template/{ptpl_pk}/")

    # -- Part: pricing override validate (min > max) --
    r_pricebad = api("patch", "/part/1/pricing/", {"override_min": "100.00", "override_max": "10.00"})
    detail_pricebad = f"HTTP {r_pricebad.status_code} {short(r_pricebad)}"
    if r_pricebad.status_code == 500:
        detail_pricebad += "  [DEFECTO CONFIRMADO: PartPricingSerializer.validate() compara override_min/override_max con AttributeError sobre Decimal.amount -> 500 en vez de 400]"
    log("COV-PRICING-override-minmax", "PATCH pricing con override_min > override_max (debe rechazar)", r_pricebad.status_code in (400, 422), detail_pricebad)
    api("patch", "/part/1/pricing/", {"override_min": None, "override_max": None})

    # -- BOM: check_add_to_bom (self-reference, variant tree) --
    r_bomself = api("post", "/bom/", {"part": 5, "sub_part": 5, "quantity": 1})
    log("COV-BOM-selfref", "Crear BomItem con part==sub_part (auto-referencia, debe rechazar)", r_bomself.status_code in (400, 422), f"HTTP {r_bomself.status_code} {short(r_bomself)}")

    # -- BOM: lock check --
    r_lockset2 = api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "True"})
    api("patch", "/part/5/", {"locked": True})
    r_bomlocked = api("post", "/bom/", {"part": 5, "sub_part": 3, "quantity": 2})
    log("COV-BOM-locked-assembly", "Crear BomItem en assembly locked=True (debe rechazar)", r_bomlocked.status_code in (400, 422), f"HTTP {r_bomlocked.status_code} {short(r_bomlocked)}")
    api("patch", "/part/5/", {"locked": False})
    if r_lockset2.status_code == 200:
        api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "False"})

    # -- BOM: copy_bom_from via /part/{pk}/bom-copy/ --
    r_targetassy = api("post", "/part/", {"name": "COV BOM Copy Target", "description": "x", "category": 1, "assembly": True})
    target_pk = r_targetassy.json().get("pk") if r_targetassy.status_code == 201 else None
    if target_pk:
        r_bomcopy = api("post", f"/part/{target_pk}/bom-copy/", {"part": 5, "clear": True, "copy_substitutes": True})
        log("COV-BOM-copy", "POST /part/{pk}/bom-copy/ (clear=True, copy_substitutes=True)", r_bomcopy.status_code in (200, 201, 204), f"HTTP {r_bomcopy.status_code} {short(r_bomcopy)}")
        api("patch", f"/part/{target_pk}/", {"active": False})
        api("delete", f"/part/{target_pk}/")

    # -- BOM: validate con valid=False --
    r_bomlist = api("get", "/bom/", params={"part": 5})
    bom_items = extract_list(r_bomlist.json())
    if bom_items:
        bom_pk2 = bom_items[0]["pk"]
        r_bominvalid = api("put", f"/bom/{bom_pk2}/validate/", {"valid": False})
        log("COV-BOM-validate-false", "Invalidar BomItem (valid=False)", r_bominvalid.status_code in (200, 201), f"HTTP {r_bominvalid.status_code}")
        api("put", f"/bom/{bom_pk2}/validate/", {"valid": True})

    # -- BomItemSubstitute: validate_unique (part == sub_part del BomItem) --
    if bom_items:
        bom_pk3 = bom_items[0]["pk"]
        sub_part_of_bom = bom_items[0].get("sub_part")
        if sub_part_of_bom:
            r_subdup = api("post", "/bom/substitute/", {"bom_item": bom_pk3, "part": sub_part_of_bom})
            log("COV-BOMSUB-dup", "Crear BomItemSubstitute con part==sub_part original (debe rechazar)", r_subdup.status_code in (400, 422), f"HTTP {r_subdup.status_code} {short(r_subdup)}")

    # -- Part.get_latest_serial_number()/find_conflicting_serial_numbers() via endpoint propio del part app --
    r_trkpart = api("post", "/part/", {"name": "COV SerialNum Detail Part", "description": "x", "category": 1, "trackable": True, "active": True})
    trkpart_pk = r_trkpart.json().get("pk") if r_trkpart.status_code == 201 else None
    if trkpart_pk:
        r_snd_empty = api("get", f"/part/{trkpart_pk}/serial-numbers/")
        log("COV-PART-serialnum-detail-empty", "GET /part/{pk}/serial-numbers/ sin stock serializado", r_snd_empty.status_code == 200, f"HTTP {r_snd_empty.status_code} {short(r_snd_empty)}")

        r_stkser = api("post", "/stock/", {"part": trkpart_pk, "location": 1, "quantity": 3, "serial_numbers": "1-3"})
        if r_stkser.status_code == 201:
            r_snd = api("get", f"/part/{trkpart_pk}/serial-numbers/")
            log("COV-PART-serialnum-detail", "GET /part/{pk}/serial-numbers/ (latest serial calculado)", r_snd.status_code == 200, f"HTTP {r_snd.status_code} {short(r_snd)}")

            r_conflict = api("post", "/stock/", {"part": trkpart_pk, "location": 1, "quantity": 2, "serial_numbers": "2-3"})
            log("COV-PART-serial-conflict", "POST /stock/ con serial_numbers en conflicto (via Part.find_conflicting_serial_numbers)", r_conflict.status_code in (400, 422), f"HTTP {r_conflict.status_code} {short(r_conflict)}")

            created = r_stkser.json()
            created = created if isinstance(created, list) else [created]
            for c in created:
                api("delete", f"/stock/{c['pk']}/")
        api("patch", f"/part/{trkpart_pk}/", {"active": False})
        api("delete", f"/part/{trkpart_pk}/")

    # -- BOM: bulk-delete de BomItem con assembly locked=True --
    r_lockset3 = api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "True"})
    r_bomlockassy = api("post", "/part/", {"name": "COV BOM Lock Delete Assy", "description": "x", "category": 1, "assembly": True})
    bomlockassy_pk = r_bomlockassy.json().get("pk") if r_bomlockassy.status_code == 201 else None
    if bomlockassy_pk:
        r_bomlockitem = api("post", "/bom/", {"part": bomlockassy_pk, "sub_part": 3, "quantity": 1})
        bomlockitem_pk = r_bomlockitem.json().get("pk") if r_bomlockitem.status_code == 201 else None
        if bomlockitem_pk:
            api("patch", f"/part/{bomlockassy_pk}/", {"locked": True})
            r_bomdel_locked = requests.delete(f"{API}/bom/", auth=(USER, PASS), json={"items": [bomlockitem_pk]})
            log("COV-BOM-bulkdelete-locked", "Bulk DELETE /bom/ con assembly locked=True (debe rechazar)", r_bomdel_locked.status_code in (400, 422), f"HTTP {r_bomdel_locked.status_code} {short(r_bomdel_locked)}")
            api("patch", f"/part/{bomlockassy_pk}/", {"locked": False})
            api("delete", f"/bom/{bomlockitem_pk}/")
        api("patch", f"/part/{bomlockassy_pk}/", {"active": False})
        api("delete", f"/part/{bomlockassy_pk}/")
    if r_lockset3.status_code == 200:
        api("patch", "/settings/global/PART_ENABLE_LOCKING/", {"value": "False"})

    # -- Part: create con initial_supplier (SupplierPart/ManufacturerPart nuevos) --
    r_initsup = api("post", "/part/", {
        "name": "COV InitSupplier Part", "description": "x", "category": 1,
        "initial_supplier": {"supplier": 1, "sku": "COV-INIT-SKU-001"},
    })
    ok_initsup = r_initsup.status_code == 201
    log("COV-PART-create-initialsupplier", "POST /part/ con initial_supplier (supplier+sku)", ok_initsup, f"HTTP {r_initsup.status_code} {short(r_initsup)}")
    if ok_initsup:
        api("patch", f"/part/{r_initsup.json()['pk']}/", {"active": False})
        api("delete", f"/part/{r_initsup.json()['pk']}/")

    r_initsup_bad = api("post", "/part/", {
        "name": "COV InitSupplier Bad Part", "description": "x", "category": 1,
        "initial_supplier": {"supplier": 2, "sku": "COV-INIT-SKU-BAD"},
    })
    log("COV-PART-create-initialsupplier-badsupplier", "POST /part/ con initial_supplier.supplier no-proveedor (debe rechazar)", r_initsup_bad.status_code in (400, 422), f"HTTP {r_initsup_bad.status_code} {short(r_initsup_bad)}")

    # -- part.helpers: compile_full_name_template() con template malformado (fallback IPN|name|revision) --
    r_fmtget = api("get", "/settings/global/PART_NAME_FORMAT/")
    original_fmt = r_fmtget.json().get("value") if r_fmtget.status_code == 200 else None
    r_fmtset = api("patch", "/settings/global/PART_NAME_FORMAT/", {"value": "{{unclosed"})
    if r_fmtset.status_code == 200:
        r_fmtcheck = api("get", "/part/1/")
        log("COV-PART-fullname-badtemplate", "GET /part/1/ con PART_NAME_FORMAT malformado (fallback)", r_fmtcheck.status_code == 200, f"HTTP {r_fmtcheck.status_code}")
        api("patch", "/settings/global/PART_NAME_FORMAT/", {"value": original_fmt or "{{ part.IPN }} | {{ part.name }}"})

    # -- PartPricing.update_variant_cost(): template part con variante hija con pricing --
    r_tmpl = api("post", "/part/", {"name": "COV Pricing Template", "description": "x", "category": 1, "is_template": True, "active": True})
    tmpl_pk = r_tmpl.json().get("pk") if r_tmpl.status_code == 201 else None
    if tmpl_pk:
        r_variant = api("post", "/part/", {"name": "COV Pricing Variant", "description": "x", "category": 1, "variant_of": tmpl_pk, "active": True, "salable": True})
        variant_pk = r_variant.json().get("pk") if r_variant.status_code == 201 else None
        if variant_pk:
            r_vprice = api("post", "/part/sale-price/", {"part": variant_pk, "quantity": 1, "price": "3.00", "price_currency": "USD"})
            vprice_pk = r_vprice.json().get("pk") if r_vprice.status_code == 201 else None
            api("patch", f"/part/{variant_pk}/pricing/", {"update": True})
            r_tmplupdate = api("patch", f"/part/{tmpl_pk}/pricing/", {"update": True})
            log("COV-PRICING-variant-cost", "Recalculo de pricing en template con variante con pricing", r_tmplupdate.status_code == 200, f"HTTP {r_tmplupdate.status_code}")
            if vprice_pk:
                api("delete", f"/part/sale-price/{vprice_pk}/")
            api("patch", f"/part/{variant_pk}/", {"active": False})
            api("delete", f"/part/{variant_pk}/")
        api("patch", f"/part/{tmpl_pk}/", {"active": False})
        api("delete", f"/part/{tmpl_pk}/")

    # -- PartPricing.update_supplier_cost(): SupplierPart con SupplierPriceBreak --
    r_suppart = api("post", "/company/part/", {"part": 1, "supplier": 1, "SKU": "COV-PRICING-SKU"})
    suppart_pk = r_suppart.json().get("pk") if r_suppart.status_code == 201 else None
    if suppart_pk:
        r_pb = api("post", "/company/price-break/", {"part": suppart_pk, "quantity": 1, "price": "0.25", "price_currency": "USD"})
        pb_pk = r_pb.json().get("pk") if r_pb.status_code == 201 else None
        r_supdate = api("patch", "/part/1/pricing/", {"update": True})
        log("COV-PRICING-supplier-cost", "Recalculo de pricing con SupplierPriceBreak", r_supdate.status_code == 200, f"HTTP {r_supdate.status_code}")
        if pb_pk:
            api("delete", f"/company/price-break/{pb_pk}/")
        api("delete", f"/company/part/{suppart_pk}/")

    # -- stocktake: generate con category filter --
    r_stkenable = api("patch", "/settings/global/STOCKTAKE_ENABLE/", {"value": "True"})
    if r_stkenable.status_code == 200:
        r_stkcat = api("post", "/part/stocktake/generate/", {"category": 1, "generate_report": False, "generate_entry": True})
        log("COV-STOCKTAKE-category", "Generar stocktake filtrado por category=1", r_stkcat.status_code in (200, 201, 400), f"HTTP {r_stkcat.status_code} {short(r_stkcat)}")
        api("patch", "/settings/global/STOCKTAKE_ENABLE/", {"value": "False"})


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 62)
    print("  InvenTree — Partes · Categorías · BOM")
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

        print("\n── CPF-001: Partes (CRUD) ─────────────────────────────")
        tc_partes_flow(page)

        print("\n── CPF-006: Categorías de Partes ─────────────────────")
        tc_cat_01(page); tc_cat_02(page); tc_cat_03(page); tc_cat_04(page)
        tc_cat_05(page); tc_cat_06(page); tc_cat_07(page)

        print("\n── CPF-005: BOM (Lista de Materiales) ─────────────────")
        tc_bom_01(page); tc_bom_02(page); tc_bom_03(page); tc_bom_04(page)
        tc_bom_05(page); tc_bom_06(page); tc_bom_07(page); tc_bom_08(page)

        ctx.close(); browser.close()

    print("\n── FN1 — Partes: casos extendidos ────────────────────")
    try:
        fn1_cat_filters(); fn1_cat_tree(); fn1_cat_parameter_template()
        fn1_part_filters(); fn1_part_secondary(); fn1_part_test_template()
        fn1_part_related_stocktake_price(); fn1_bom_filters(); fn1_coverage_extra()
    except Exception as e:
        log("FN1-PART-extended", "Casos extendidos de Partes", False, str(e))

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
