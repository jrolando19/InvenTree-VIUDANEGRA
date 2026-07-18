#!/usr/bin/env python3
"""
Sistema — test_sistema_desempeno_inventree_suite.py
Prueba de sistema de tipo DESEMPEÑO / PERFORMANCE (una de las 2 categorías de
prueba de sistema elegidas para el curso, junto con seguridad).

Mide tiempo de respuesta de endpoints críticos contra umbrales de aceptación,
y comportamiento bajo carga (requests concurrentes, operaciones en lote) — no
es una prueba funcional (no valida reglas de negocio, solo tiempos).

PERF-01  Tiempo de respuesta: listar partes
PERF-02  Tiempo de respuesta: crear un stock item
PERF-03  Carga concurrente: N requests simultáneas al mismo endpoint
PERF-04  Latencia p95 en una secuencia de requests al mismo endpoint
PERF-05  Rendimiento de operación en lote: crear N stock items
"""
import datetime
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = "http://localhost:8000/api"
AUTH = ("admin", "inventree")
PART_PK = 1

RESULTS_DIR = Path(os.path.abspath(__file__)).parent.parent.parent / "test_output" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Umbrales de aceptación (segundos). Generosos a propósito -- el objetivo es
# detectar una regresión real (endpoint colgado, N+1 queries, etc.), no medir
# performance de producción sobre un servidor de desarrollo sin optimizar.
THRESHOLD_SINGLE_REQUEST = 2.0
THRESHOLD_P95            = 1.5
THRESHOLD_CONCURRENT_TOTAL = 10.0
THRESHOLD_BULK_AVG       = 1.0

results  = []
counters = {"pass": 0, "fail": 0, "total": 0}


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def api(method, endpoint, data=None, params=None):
    url = f"{BASE}/{endpoint.lstrip('/')}"
    return getattr(requests, method)(url, json=data, params=params, auth=AUTH, timeout=30)


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


def extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", [])
    return []


# ──────────────────────────────────────────────────────────────────
# PERF-01 — Tiempo de respuesta: listar partes
# ──────────────────────────────────────────────────────────────────

def perf_01_list_parts_response_time():
    print("\n── PERF-01: Tiempo de respuesta al listar partes ──")

    start = time.perf_counter()
    r = api("get", "/part/", params={"limit": 100})
    elapsed = time.perf_counter() - start

    ok = r.status_code == 200 and elapsed < THRESHOLD_SINGLE_REQUEST
    record("PERF-01", f"GET /part/?limit=100 responde en < {THRESHOLD_SINGLE_REQUEST}s",
           ok, f"HTTP {r.status_code} | tiempo={elapsed:.3f}s (umbral {THRESHOLD_SINGLE_REQUEST}s)",
           r if r.status_code != 200 else None)


# ──────────────────────────────────────────────────────────────────
# PERF-02 — Tiempo de respuesta: crear un stock item
# ──────────────────────────────────────────────────────────────────

def perf_02_create_stock_response_time():
    print("\n── PERF-02: Tiempo de respuesta al crear un StockItem ──")

    start = time.perf_counter()
    r = api("post", "/stock/", {"part": PART_PK, "quantity": 5, "location": 1})
    elapsed = time.perf_counter() - start

    ok = r.status_code == 201 and elapsed < THRESHOLD_SINGLE_REQUEST
    record("PERF-02", f"POST /stock/ responde en < {THRESHOLD_SINGLE_REQUEST}s",
           ok, f"HTTP {r.status_code} | tiempo={elapsed:.3f}s (umbral {THRESHOLD_SINGLE_REQUEST}s)",
           r if r.status_code != 201 else None)

    if r.status_code == 201:
        data = r.json()
        pk = (data[0] if isinstance(data, list) else data).get("pk")
        if pk:
            api("delete", f"/stock/{pk}/")


# ──────────────────────────────────────────────────────────────────
# PERF-03 — Carga concurrente: N requests simultáneas
# ──────────────────────────────────────────────────────────────────

def _timed_get(endpoint, params=None):
    start = time.perf_counter()
    r = requests.get(f"{BASE}{endpoint}", params=params, auth=AUTH, timeout=30)
    return time.perf_counter() - start, r.status_code


def perf_03_concurrent_load():
    print("\n── PERF-03: Carga concurrente (10 requests simultáneas) ──")

    n = 10
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as executor:
        futures = [executor.submit(_timed_get, "/part/", {"limit": 20}) for _ in range(n)]
        outcomes = [f.result() for f in as_completed(futures)]
    total_elapsed = time.perf_counter() - start

    all_ok = all(status == 200 for _elapsed, status in outcomes)
    avg_individual = statistics.mean(elapsed for elapsed, _status in outcomes)

    ok = all_ok and total_elapsed < THRESHOLD_CONCURRENT_TOTAL
    record("PERF-03", f"{n} GET /part/ concurrentes: todas exitosas y total < {THRESHOLD_CONCURRENT_TOTAL}s",
           ok,
           f"exitosas={sum(1 for _e, s in outcomes if s == 200)}/{n} | "
           f"tiempo_total={total_elapsed:.3f}s | tiempo_individual_promedio={avg_individual:.3f}s")


# ──────────────────────────────────────────────────────────────────
# PERF-04 — Latencia p95 en una secuencia de requests
# ──────────────────────────────────────────────────────────────────

def perf_04_p95_latency():
    print("\n── PERF-04: Latencia p95 sobre 20 requests secuenciales ──")

    n = 20
    timings = []
    failures = 0
    for _ in range(n):
        elapsed, status = _timed_get("/part/", {"limit": 20})
        timings.append(elapsed)
        if status != 200:
            failures += 1

    timings_sorted = sorted(timings)
    p95_index = max(0, int(round(0.95 * len(timings_sorted))) - 1)
    p95 = timings_sorted[p95_index]

    ok = failures == 0 and p95 < THRESHOLD_P95
    record("PERF-04", f"p95 de {n} requests a GET /part/ < {THRESHOLD_P95}s",
           ok,
           f"p95={p95:.3f}s (umbral {THRESHOLD_P95}s) | min={min(timings):.3f}s max={max(timings):.3f}s | fallos={failures}/{n}")


# ──────────────────────────────────────────────────────────────────
# PERF-05 — Rendimiento de operación en lote: crear N stock items
# ──────────────────────────────────────────────────────────────────

def perf_05_bulk_create_performance():
    print("\n── PERF-05: Rendimiento de creación en lote (20 StockItems) ──")

    n = 20
    created_pks = []
    start = time.perf_counter()
    failures = 0
    for _ in range(n):
        r = api("post", "/stock/", {"part": PART_PK, "quantity": 1, "location": 1})
        if r.status_code == 201:
            data = r.json()
            pk = (data[0] if isinstance(data, list) else data).get("pk")
            if pk:
                created_pks.append(pk)
        else:
            failures += 1
    total_elapsed = time.perf_counter() - start
    avg = total_elapsed / n

    ok = failures == 0 and avg < THRESHOLD_BULK_AVG
    record("PERF-05", f"Crear {n} StockItems en lote: promedio < {THRESHOLD_BULK_AVG}s/item",
           ok,
           f"total={total_elapsed:.3f}s | promedio={avg:.3f}s/item (umbral {THRESHOLD_BULK_AVG}s) | fallos={failures}/{n}")

    for pk in created_pks:
        api("delete", f"/stock/{pk}/")


# ──────────────────────────────────────────────────────────────────
# Resumen
# ──────────────────────────────────────────────────────────────────

def print_summary():
    print("\n" + "═" * 60)
    print("  RESUMEN — Prueba de Sistema: Desempeño")
    print("═" * 60)
    for r in results:
        tag = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {tag} {r['id']:10s} {r['desc']}")
    print()
    pct = round(100 * counters["pass"] / counters["total"], 1) if counters["total"] else 0
    print(f"  Total: {counters['total']}  PASS: {counters['pass']}  FAIL: {counters['fail']}  ({pct}%)")
    print("═" * 60 + "\n")

    out = {
        "suite":     "test_sistema_desempeno_inventree_suite.py",
        "tipo":      "Desempeño",
        "timestamp": datetime.datetime.now().isoformat(),
        "summary":   counters,
        "cases":     results,
    }
    out_path = RESULTS_DIR / "desempeno_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"  Resultados guardados en {out_path}")


if __name__ == "__main__":
    import sys
    perf_01_list_parts_response_time()
    perf_02_create_stock_response_time()
    perf_03_concurrent_load()
    perf_04_p95_latency()
    perf_05_bulk_create_performance()
    print_summary()
    sys.exit(0 if counters["fail"] == 0 else 1)
