#!/usr/bin/env python3
"""
Sistema — test_sistema_seguridad_inventree_suite.py
Prueba de sistema de tipo SEGURIDAD (una de las 2 categorías de prueba de
sistema elegidas para el curso, junto con desempeño).

No es una prueba funcional de un módulo ni de integración entre dos módulos:
evalúa una preocupación TRANSVERSAL — el control de acceso — a través de
TODA la superficie de la API, sin importar qué módulo esté detrás.

SEC-01..03  Usuario sin permisos no puede eliminar/crear partes (control con admin)
SEC-04      Acceso sin autenticación rechazado en múltiples módulos
SEC-05      Token inválido/revocado/inexistente rechazado
SEC-06      Usuario sin permisos no puede modificar/crear stock
SEC-07      Usuario sin permisos no puede listar/crear usuarios (escalación)
SEC-08      Endpoint de plugins requiere autenticación
"""
import datetime
import json
import os
from pathlib import Path

import requests

BASE       = "http://localhost:8000/api"
AUTH_ADMIN = ("admin", "inventree")
AUTH_USER  = ("testviewer", "viewer123")   # usuario sin permisos (is_superuser=False)
PART_PK    = 1   # Resistencia 10k — parte existente

RESULTS_DIR = Path(os.path.abspath(__file__)).parent.parent.parent / "test_output" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

results  = []
counters = {"pass": 0, "fail": 0, "total": 0}


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def api(method, endpoint, data=None, params=None, auth=AUTH_ADMIN, headers=None):
    url = f"{BASE}/{endpoint.lstrip('/')}"
    return getattr(requests, method)(url, json=data, params=params, auth=auth, headers=headers, timeout=15)


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
            print(f"       → HTTP {response.status_code} {response.text[:200]}")
        except Exception:
            pass

    results.append({"id": tc_id, "desc": description, "status": status, "detail": detail})
    return passed


# ──────────────────────────────────────────────────────────────────
# SEC-01..03 — Control de permisos básico (partes)
# ──────────────────────────────────────────────────────────────────

def sec_01_03_part_permissions():
    print("\n── SEC-01..03: Control de permisos sobre partes ──")

    r = api("delete", f"/part/{PART_PK}/", auth=AUTH_USER)
    record("SEC-01", "Usuario sin permisos no puede eliminar parte (HTTP 401/403)",
           r.status_code in (401, 403), f"HTTP {r.status_code} (esperado 401/403)")

    r2 = api("post", "/part/", {"name": "SEC No-Perm Part", "category": 1}, auth=AUTH_USER)
    record("SEC-02", "Usuario sin permisos no puede crear parte (HTTP 401/403)",
           r2.status_code in (401, 403), f"HTTP {r2.status_code} (esperado 401/403)")

    r3 = api("get", f"/part/{PART_PK}/", auth=AUTH_ADMIN)
    record("SEC-03", "Admin puede leer parte con normalidad (control positivo)",
           r3.status_code == 200 and r3.json().get("pk") == PART_PK, f"HTTP {r3.status_code}")


# ──────────────────────────────────────────────────────────────────
# SEC-04 — Acceso sin autenticación rechazado en TODOS los módulos RF
# ──────────────────────────────────────────────────────────────────

MODULE_LIST_ENDPOINTS = [
    ("part", "/part/"),
    ("stock", "/stock/"),
    ("order-po", "/order/po/"),
    ("order-so", "/order/so/"),
    ("build", "/build/"),
    ("company", "/company/"),
    ("user", "/user/"),
]

def sec_04_unauthenticated_rejected_across_modules():
    print("\n── SEC-04: Acceso sin autenticación rechazado en cada módulo ──")

    for name, endpoint in MODULE_LIST_ENDPOINTS:
        r = requests.get(f"{BASE}{endpoint}", timeout=15)
        record(f"SEC-04-{name}", f"GET {endpoint} sin autenticación rechazado",
               r.status_code in (401, 403), f"HTTP {r.status_code} (esperado 401/403)")


# ──────────────────────────────────────────────────────────────────
# SEC-05 — Token inválido / inexistente rechazado
# ──────────────────────────────────────────────────────────────────

def sec_05_invalid_token_rejected():
    print("\n── SEC-05: Token inválido/inexistente rechazado ──")

    r = requests.get(f"{BASE}/user/me/", headers={"Authorization": "Token this-token-does-not-exist-000000"}, timeout=15)
    record("SEC-05a", "Token inexistente rechazado (HTTP 401)", r.status_code == 401, f"HTTP {r.status_code}")

    r2 = requests.get(f"{BASE}/user/me/", headers={"Authorization": "Token "}, timeout=15)
    record("SEC-05b", "Token vacío rechazado (HTTP 401)", r2.status_code == 401, f"HTTP {r2.status_code}")

    r3 = requests.get(f"{BASE}/user/me/", headers={"Authorization": "Bearer not-a-real-scheme"}, timeout=15)
    record("SEC-05c", "Esquema de autenticación no soportado rechazado (HTTP 401)", r3.status_code == 401, f"HTTP {r3.status_code}")


# ──────────────────────────────────────────────────────────────────
# SEC-06 — Usuario sin permisos no puede modificar/crear stock
# ──────────────────────────────────────────────────────────────────

def sec_06_stock_permissions():
    print("\n── SEC-06: Control de permisos sobre stock ──")

    r = api("post", "/stock/", {"part": PART_PK, "quantity": 5, "location": 1}, auth=AUTH_USER)
    record("SEC-06a", "Usuario sin permisos no puede crear StockItem (HTTP 401/403)",
           r.status_code in (401, 403), f"HTTP {r.status_code}")

    # Crear un item real como admin, e intentar borrarlo/transferirlo como usuario sin permisos
    r_admin = api("post", "/stock/", {"part": PART_PK, "quantity": 5, "location": 1}, auth=AUTH_ADMIN)
    data = r_admin.json()
    stk_pk = (data[0] if isinstance(data, list) else data).get("pk") if r_admin.status_code == 201 else None

    if stk_pk:
        r_del = api("delete", f"/stock/{stk_pk}/", auth=AUTH_USER)
        record("SEC-06b", "Usuario sin permisos no puede eliminar StockItem ajeno (HTTP 401/403)",
               r_del.status_code in (401, 403), f"HTTP {r_del.status_code}")
        api("delete", f"/stock/{stk_pk}/", auth=AUTH_ADMIN)
    else:
        record("SEC-06b", "Usuario sin permisos no puede eliminar StockItem ajeno (HTTP 401/403)",
               False, "No se pudo crear StockItem de prueba como admin")


# ──────────────────────────────────────────────────────────────────
# SEC-07 — Usuario sin permisos no puede escalar (listar/crear usuarios)
# ──────────────────────────────────────────────────────────────────

def sec_07_user_escalation_blocked():
    print("\n── SEC-07: Usuario sin permisos no puede administrar usuarios ──")

    r = api("post", "/user/", {"username": "sec_escalation_attempt", "email": "x@example.com"}, auth=AUTH_USER)
    record("SEC-07a", "Usuario sin permisos no puede crear otro usuario (HTTP 401/403)",
           r.status_code in (401, 403), f"HTTP {r.status_code}")

    r2 = api("patch", "/user/1/", {"is_superuser": True}, auth=AUTH_USER)
    record("SEC-07b", "Usuario sin permisos no puede otorgarse superuser (HTTP 401/403/404)",
           r2.status_code in (401, 403, 404), f"HTTP {r2.status_code}")


# ──────────────────────────────────────────────────────────────────
# SEC-08 — Endpoint de plugins requiere autenticación
# ──────────────────────────────────────────────────────────────────

def sec_08_plugins_require_auth():
    print("\n── SEC-08: Endpoint de plugins requiere autenticación ──")

    r = requests.get(f"{BASE}/plugins/", timeout=15)
    record("SEC-08", "GET /api/plugins/ sin autenticación rechazado",
           r.status_code in (401, 403), f"HTTP {r.status_code}")


# ──────────────────────────────────────────────────────────────────
# Resumen
# ──────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "═" * 60)
    print("  RESUMEN — Prueba de Sistema: Seguridad")
    print("═" * 60)
    for r in results:
        tag = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {tag} {r['id']:12s} {r['desc']}")
    print()
    pct = round(100 * counters["pass"] / counters["total"], 1) if counters["total"] else 0
    print(f"  Total: {counters['total']}  PASS: {counters['pass']}  FAIL: {counters['fail']}  ({pct}%)")
    print("═" * 60 + "\n")

    out = {
        "suite":     "test_sistema_seguridad_inventree_suite.py",
        "tipo":      "Seguridad",
        "timestamp": datetime.datetime.now().isoformat(),
        "summary":   counters,
        "cases":     results,
    }
    out_path = RESULTS_DIR / "seguridad_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  Resultados guardados en {out_path}")


if __name__ == "__main__":
    import sys
    sec_01_03_part_permissions()
    sec_04_unauthenticated_rejected_across_modules()
    sec_05_invalid_token_rejected()
    sec_06_stock_permissions()
    sec_07_user_escalation_blocked()
    sec_08_plugins_require_auth()
    print_summary()
    sys.exit(0 if counters["fail"] == 0 else 1)
