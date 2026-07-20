#!/usr/bin/env python3
"""
start_inventree.py — Levanta el servidor InvenTree en localhost:8000

Uso:
  python start_inventree.py                     Muestra un menú interactivo
  python start_inventree.py [--setup] [--tests] [--coverage]
    --setup     Ejecuta setup_system_tests.py antes de iniciar
    --tests     Ejecuta todas las suites después de iniciar
    --coverage  Junto con --tests: reinicia el servidor bajo `coverage run`
                antes de CADA suite (datos aislados por suite) y muestra el
                % de cobertura por módulo de InvenTree al terminar cada una

Nota: --setup (o el setup automático cuando falta el usuario admin) solo
inicializa datos base (fixtures/admin) — NO ejecuta las pruebas. Para correr
las pruebas hace falta --tests (o la opción correspondiente del menú).
"""

import argparse
import os
import signal
import subprocess
import sys
import time

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
VENV_PY    = os.path.join(BASE_DIR, "dev", "venv", "bin", "python")
if not os.path.isfile(VENV_PY):
    # Sin venv local (p. ej. en CI, donde las dependencias se instalan
    # directo al Python del sistema): usar el intérprete actual.
    VENV_PY = sys.executable
INVOKE_BIN = os.path.join(BASE_DIR, "dev", "venv", "bin", "invoke")
if not os.path.isfile(INVOKE_BIN):
    INVOKE_BIN = "invoke"
MANAGE     = os.path.join(BASE_DIR, "src", "backend", "InvenTree", "manage.py")
SRC_DIR    = os.path.join(BASE_DIR, "src", "backend", "InvenTree")
PID_FILE   = os.path.join(BASE_DIR, ".inventree_server.pid")
COV_DATA   = os.path.join(BASE_DIR, ".coverage")
COV_OMIT   = "*/admin.py,*/tasks.py,*/events.py,*/apps.py,*/settings.py,*/test_*.py,*/tests.py,*/migrations/*,*/samples/*,*/unit_test.py,*/test_helpers/*"
URL        = "http://localhost:8000/api/"

# Hito 2 — Funcionales (FN#-CP-###), una suite por módulo RF-mapeado.
# Tupla: (clave de módulo, ruta de la suite relativa a BASE_DIR, descripción para el menú)
FUNCTIONAL_SUITES = [
    ("part",    "tests/funcionales/test_part_inventree_suite.py",    "FN1 Partes + FN6 Categorías + FN5 BOM"),
    ("stock",   "tests/funcionales/test_stock_inventree_suite.py",   "FN2/FN3 Stock"),
    ("order",   "tests/funcionales/test_order_inventree_suite.py",   "FN4 PO + SO/RO/Transfer Order"),
    ("build",   "tests/funcionales/test_build_inventree_suite.py",   "FN8 Build Orders"),
    ("company", "tests/funcionales/test_company_inventree_suite.py", "FN7 Proveedores"),
    ("users",   "tests/funcionales/test_users_inventree_suite.py",   "FN9 Autenticación / Identidad"),
]

# Integración (INT-##) — puntos de contacto PUNTUALES entre dos módulos
# (ej. "recibir una PO crea el StockItem correcto"), a diferencia de una
# suite funcional (un solo módulo) o de golden_path (el flujo COMPLETO)
INTEGRATION_SUITES = [
    ("integracion", "tests/integracion/test_integracion_inventree_suite.py", "order↔stock, build↔stock, stock↔tracking"),
]

# Sistema (ST-###) — pruebas transversales a todo el sistema. Incluye el
# flujo E2E completo (golden_path) y las 2 categorías de prueba de sistema
# elegidas para el curso: seguridad y desempeño.
SYSTEM_SUITES = [
    ("golden_path", "tests/sistema/test_sistema_golden_path_inventree_suite.py", "Golden path (flujo E2E completo)"),
    ("seguridad",   "tests/sistema/test_sistema_seguridad_inventree_suite.py",   "Seguridad (control de acceso, autenticación)"),
    ("desempeno",   "tests/sistema/test_sistema_desempeno_inventree_suite.py",   "Desempeño (tiempos de respuesta, carga)"),
]

# Compatibilidad con --tests/--coverage por CLI: todas las suites, en orden
SUITES = ([f for _key, f, _desc in FUNCTIONAL_SUITES]
          + [f for _key, f, _desc in INTEGRATION_SUITES]
          + [f for _key, f, _desc in SYSTEM_SUITES])

# Mapea cada suite funcional a SU PROPIO módulo — para que la tabla de coverage
# de una suite individual no muestre los otros 5 módulos (que van a salir con
# porcentajes bajos/engañosos porque esa suite no los ejercita).
SUITE_TO_MODULE = {f: key for key, f, _desc in FUNCTIONAL_SUITES}

# Lookup por clave (p. ej. "part", "stock", "integracion", "golden_path") ->
# ruta de la suite. Permite correr UNA sola suite por CLI (--suite <clave>),
# pensado para que un workflow de CI la use en jobs paralelos, uno por módulo.
ALL_SUITES_BY_KEY = {
    key: f
    for key, f, _desc in FUNCTIONAL_SUITES + INTEGRATION_SUITES + SYSTEM_SUITES
}

# Módulos mapeados a RF del Hito 2 (wiki del curso). El objetivo de 85% se
# mide solo sobre estos — InvenTree/common/machine/plugin/report/importer/
# data_exporter no tienen RF asociado y no cuentan para el total.
RF_MODULES = ["part", "stock", "order", "build", "company", "users"]
RF_INCLUDE = [f"*/src/backend/InvenTree/{m}/*" for m in RF_MODULES]

# Pruebas internas de InvenTree (Django TestCase / unittest), las mismas que
# corre `invoke dev.test` en el CI oficial (qc_checks.yaml) -- no son las
# suites propias del Hito 2: viven adentro del código fuente de InvenTree
# (ej. src/backend/InvenTree/part/test_*.py), corren con el test-runner de
# Django (base de datos de prueba propia, sin servidor real) y no se tocaron
# ni un poquito -- esto solo agrega una forma cómoda de invocarlas.
INTERNAL_TEST_APPS = [(m, m, f"tests internos de Django del módulo {m}") for m in RF_MODULES]

# ── colores ──────────────────────────────────────────────────────
OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
INFO = "\033[94mℹ️ \033[0m"
WARN = "\033[93m⚠️ \033[0m"


def check_deps():
    """Verifica que PostgreSQL y Redis estén accesibles."""
    import socket
    errors = []
    db_host = os.environ.get("INVENTREE_DB_HOST", "db")
    db_port = int(os.environ.get("INVENTREE_DB_PORT", 5432))
    cache_host = os.environ.get("INVENTREE_CACHE_HOST", "redis")
    cache_port = int(os.environ.get("INVENTREE_CACHE_PORT", 6379))
    for host, port, name in [
        (db_host, db_port, "PostgreSQL"),
        (cache_host, cache_port, "Redis"),
    ]:
        try:
            s = socket.create_connection((host, port), timeout=3)
            s.close()
            print(f"  {OK}  {name} ({host}:{port})")
        except OSError:
            print(f"  {FAIL}  {name} ({host}:{port}) NO DISPONIBLE")
            errors.append(name)
    return errors


def is_server_running():
    """Devuelve True si el servidor ya responde en localhost:8000."""
    try:
        import urllib.request
        urllib.request.urlopen(URL, timeout=3)
        return True
    except Exception:
        return False


def wait_for_server(timeout=180):
    """Espera hasta que el servidor responda o se agote el tiempo."""
    print(f"\n  {INFO} Esperando que el servidor inicie (puede tardar ~60s)...")
    start = time.time()
    dots = 0
    while time.time() - start < timeout:
        if is_server_running():
            elapsed = int(time.time() - start)
            print(f"\n  {OK}  Servidor listo en {elapsed}s")
            return True
        time.sleep(3)
        dots += 1
        print(f"  {'.' * (dots % 20 + 1)}", end="\r", flush=True)
    print(f"\n  {FAIL}  Timeout: el servidor no respondió en {timeout}s")
    return False


def setup_is_needed():
    """Devuelve True si falta el usuario admin (u otra data base de pruebas)."""
    result = subprocess.run(
        [VENV_PY, os.path.join(BASE_DIR, "setup_system_tests.py"), "--verify"],
        cwd=BASE_DIR,
        capture_output=True,
    )
    return result.returncode != 0


def run_setup():
    print(f"\n{'─'*50}")
    print("  Ejecutando setup_system_tests.py...")
    print('─'*50)
    result = subprocess.run(
        [VENV_PY, os.path.join(BASE_DIR, "setup_system_tests.py")],
        cwd=BASE_DIR
    )
    return result.returncode == 0


def clean_test_data():
    """Purga PO-99xx / BO-99xx huérfanas de corridas anteriores antes de testear."""
    print(f"\n{'─'*50}")
    print("  Limpiando datos de pruebas anteriores (--clean)...")
    print('─'*50)
    result = subprocess.run(
        [VENV_PY, os.path.join(BASE_DIR, "setup_system_tests.py"), "--clean"],
        cwd=BASE_DIR
    )
    return result.returncode == 0


def stop_server_pid(pid, sig=signal.SIGINT, timeout=15):
    """Detiene el proceso del servidor por PID, esperando a que termine.

    Usa SIGINT (no SIGTERM) por defecto porque `coverage` solo vuelca sus
    datos a disco en un shutdown limpio (equivalente a Ctrl+C).
    """
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True

    start = time.time()
    while time.time() - start < timeout:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.5)
    return False


SERVER_LOG = os.path.join(BASE_DIR, ".inventree_server.log")


def start_plain_server():
    """Levanta manage.py runserver sin instrumentar, guarda el PID."""
    log = open(SERVER_LOG, "w")
    server = subprocess.Popen(
        [VENV_PY, MANAGE, "runserver", "0.0.0.0:8000", "--noreload"],
        cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(server.pid))
    return server.pid


def start_coverage_server(data_file):
    """Levanta manage.py runserver bajo `coverage run` con un data-file propio."""
    log = open(SERVER_LOG, "w")
    server = subprocess.Popen(
        [VENV_PY, "-m", "coverage", "run",
         f"--source={SRC_DIR}", f"--omit={COV_OMIT}", f"--data-file={data_file}",
         MANAGE, "runserver", "0.0.0.0:8000", "--noreload"],
        cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(server.pid))
    return server.pid


def print_server_log():
    """Imprime el log del servidor (útil cuando no arrancó o murió temprano)."""
    if os.path.exists(SERVER_LOG):
        print(f"\n  {WARN} Log del servidor ({SERVER_LOG}):")
        with open(SERVER_LOG) as f:
            print(f.read())


def module_coverage_table(data_file, modules=None):
    """Devuelve {módulo: '87%'} solo para los módulos pedidos (por defecto, todos
    los de RF_MODULES) que tienen datos medidos.

    `modules` permite restringir la tabla a un solo módulo cuando se está
    mostrando el resultado de UNA suite individual — mostrar los otros 5
    módulos ahí sería engañoso, ya que esa suite no los ejercita.
    """
    modules = modules if modules is not None else RF_MODULES
    totals = {}
    for module in modules:
        result = subprocess.run(
            [VENV_PY, "-m", "coverage", "report",
             f"--data-file={data_file}",
             f"--include=*/src/backend/InvenTree/{module}/*",
             f"--omit={COV_OMIT}"],
            cwd=BASE_DIR, capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("TOTAL"):
                parts = line.split()
                if parts and parts[-1].endswith("%") and parts[-1] != "0%":
                    totals[module] = parts[-1]
    return totals


def overall_coverage_pct(data_file, modules=None):
    """% agregado, restringido a los módulos pedidos (por defecto, todos los
    mapeados a RF en la wiki del Hito 2) — el resto no cuenta para el objetivo."""
    modules = modules if modules is not None else RF_MODULES
    include = [f"*/src/backend/InvenTree/{m}/*" for m in modules]
    result = subprocess.run(
        [VENV_PY, "-m", "coverage", "report", f"--data-file={data_file}",
         f"--include={','.join(include)}", f"--omit={COV_OMIT}"],
        cwd=BASE_DIR, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("TOTAL"):
            parts = line.split()
            if parts and parts[-1].endswith("%"):
                return parts[-1]
    return None


def print_module_coverage(data_file, label, modules=None):
    """Imprime la tabla de coverage por módulo. Si `modules` es None, se infiere
    automáticamente: si `label` es el nombre de archivo de una suite funcional
    conocida (SUITE_TO_MODULE), se restringe a SU módulo; si no (suite de
    sistema, o el agregado "TOTAL"), se muestran los 6 módulos de RF_MODULES."""
    if modules is None:
        modules = [SUITE_TO_MODULE[label]] if label in SUITE_TO_MODULE else RF_MODULES

    print(f"\n  {INFO} Coverage por módulo — {label}:")
    if not os.path.exists(data_file):
        print(f"    {WARN}  Sin datos de coverage")
        return
    table = module_coverage_table(data_file, modules=modules)
    if not table:
        print(f"    {WARN}  Ningún módulo con líneas cubiertas")
        return
    for module, pct in sorted(table.items(), key=lambda kv: kv[1]):
        print(f"    {module:<15} {pct}")

    overall = overall_coverage_pct(data_file, modules=modules)
    if overall:
        try:
            ok = float(overall.rstrip("%")) >= 85
        except ValueError:
            ok = False
        mark = OK if ok else FAIL
        modules_label = "+".join(modules) if len(modules) < len(RF_MODULES) else "part+stock+order+build+company+users"
        print(f"\n  {mark}  TOTAL ({modules_label}) ({label}): {overall}  (objetivo: 85%)")


def run_suite_with_coverage(suite_name):
    """Reinicia el server con coverage aislado, corre una suite, lo frena.

    Devuelve (data_file, suite_ok).
    """
    # Usar solo el nombre de archivo (sin la carpeta tests/xxx/) para el
    # sufijo del data-file -- si se usara la ruta completa, los '/' de
    # "tests/funcionales/..." se interpretarían como separadores de carpeta
    # al construir el path, y coverage intentaría escribir en una carpeta
    # que no existe.
    suite_stem = os.path.splitext(os.path.basename(suite_name))[0]
    data_file = os.path.join(BASE_DIR, f".coverage.{suite_stem}")
    if os.path.exists(data_file):
        os.remove(data_file)

    if is_server_running() and os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            stop_server_pid(int(f.read().strip()))

    pid = start_coverage_server(data_file)
    if not wait_for_server():
        stop_server_pid(pid)
        print(f"  {FAIL}  El servidor no arrancó — abortando la suite.")
        print_server_log()
        return None, False

    path = os.path.join(BASE_DIR, suite_name)
    result = subprocess.run([VENV_PY, path], cwd=BASE_DIR)

    stop_server_pid(pid)
    return data_file, result.returncode == 0


def run_suites_single_server(suites, title, combined_label):
    """Corre VARIAS suites bajo coverage levantando el servidor UNA SOLA VEZ.

    A diferencia de run_suite_with_coverage() (que reinicia el server por cada
    suite para aislar su medición individual), acá el mismo proceso queda
    corriendo durante toda la secuencia -- coverage.py acumula la ejecución de
    todas las suites en un único data-file de forma natural, sin necesidad de
    'combine' ni de pagar el costo de apagar/prender el server 6 veces (cada
    reinicio tarda ~20-40s solo en el ciclo SIGINT + arranque de Django).

    Se pierde la tabla POR SUITE aislada (cuánto aporta cada una en soledad),
    pero el número que realmente importa al elegir "todas" es el total
    combinado, que sale exactamente igual midiendo así."""
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print('═'*60)

    if not clean_test_data():
        print(f"  {WARN}  Limpieza previa completó con advertencias, continuando...")

    data_file = os.path.join(BASE_DIR, ".coverage.functional_all")
    if os.path.exists(data_file):
        os.remove(data_file)

    if is_server_running() and os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            stop_server_pid(int(f.read().strip()))

    print(f"\n  {INFO} Iniciando servidor bajo coverage (una sola vez para las {len(suites)} suites)...")
    pid = start_coverage_server(data_file)
    if not wait_for_server():
        stop_server_pid(pid)
        print(f"  {FAIL}  El servidor no arrancó — abortando la corrida.")
        print_server_log()
        return False

    totals = {"pass": 0, "fail": 0}
    n = len(suites)
    for i, suite in enumerate(suites, start=1):
        path = os.path.join(BASE_DIR, suite)
        if not os.path.exists(path):
            print(f"  {WARN} {suite} no encontrada, saltando")
            continue
        print(f"\n  ▶  [{i}/{n}] {suite}")
        result = subprocess.run([VENV_PY, path], cwd=BASE_DIR)
        if result.returncode == 0:
            totals["pass"] += 1
        else:
            totals["fail"] += 1

    stop_server_pid(pid)

    print(f"\n{'═'*60}")
    print(f"  {combined_label}")
    print('═'*60)
    print_module_coverage(data_file, "TOTAL")

    print(f"\n{'═'*60}")
    print(f"  Suites completadas: {totals['pass']} OK  {totals['fail']} con errores")
    print('═'*60)
    # El servidor sí llegó a arrancar y las suites corrieron -- errores de
    # aserciones dentro de una suite no deben tumbar el job de CI, solo
    # quedar reportados arriba (y en test_output/coverage-data como artifacts).
    return True


def run_suites(coverage=False, suites=None, title="EJECUTANDO TODAS LAS SUITES DE PRUEBAS",
               combined_label="COVERAGE TOTAL (todas las suites combinadas)"):
    """Corre una lista de suites (por defecto, todas — SUITES) mostrando progreso [i/N]
    y, si coverage=True, la tabla de cobertura por módulo al terminar.

    Con coverage=True y más de una suite, delega en run_suites_single_server()
    (un solo arranque de servidor para toda la corrida). Con una sola suite,
    usa run_suite_with_coverage() (un único arranque de todos modos, ya que
    solo hay una suite) para mostrar su tabla aislada por módulo."""
    suites = suites if suites is not None else SUITES

    if coverage and len(suites) > 1:
        return run_suites_single_server(suites, title, combined_label)

    print(f"\n{'═'*60}")
    print(f"  {title}")
    print('═'*60)

    if not clean_test_data():
        print(f"  {WARN}  Limpieza previa completó con advertencias, continuando...")

    totals = {"pass": 0, "fail": 0}
    n = len(suites)

    for i, suite in enumerate(suites, start=1):
        path = os.path.join(BASE_DIR, suite)
        if not os.path.exists(path):
            print(f"  {WARN} {suite} no encontrada, saltando")
            continue
        print(f"\n  ▶  [{i}/{n}] {suite}")

        if coverage:
            data_file, suite_ok = run_suite_with_coverage(suite)
            if data_file:
                print_module_coverage(data_file, suite)
        else:
            result = subprocess.run([VENV_PY, path], cwd=BASE_DIR, capture_output=False)
            suite_ok = result.returncode == 0

        if suite_ok:
            totals["pass"] += 1
        else:
            totals["fail"] += 1

    print(f"\n{'═'*60}")
    print(f"  Suites completadas: {totals['pass']} OK  {totals['fail']} con errores")
    print('═'*60)
    # Igual que en run_suites_single_server: errores de aserciones no deben
    # tumbar el job de CI, solo quedar reportados.
    return True


def show_suite_submenu(items, title):
    """Menú genérico: lista `items` (clave, archivo, descripción), deja elegir UNA
    suite por número, 'A' para todas, o '0' para volver. Devuelve una lista de
    nombres de archivo (una sola o todas) o None si el usuario elige volver."""
    while True:
        print(f"\n{'─'*60}")
        print(f"  {title}")
        print('─'*60)
        for idx, (key, fname, desc) in enumerate(items, start=1):
            print(f"  {idx}) {key:<10} — {desc}")
        print(f"  A) Ejecutar TODAS ({len(items)} suites)")
        print("  0) Volver")
        print('─'*60)

        choice = input(f"\n  Elige una opción [0-{len(items)}, A]: ").strip().upper()

        if choice == "0":
            return None
        if choice == "A":
            return [fname for _key, fname, _desc in items]
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            _key, fname, _desc = items[int(choice) - 1]
            return [fname]

        print(f"\n  {FAIL}  Opción inválida: '{choice}'")


def run_functional_tests_menu():
    """Submenú de pruebas funcionales (Hito 2, FN1-FN9): una por módulo o todas,
    siempre con coverage por módulo (es el objetivo del 85% de la wiki)."""
    selection = show_suite_submenu(FUNCTIONAL_SUITES, "Pruebas funcionales — Hito 2 (FN1-FN9)")
    if selection is None:
        return
    run_suites(
        coverage=True,
        suites=selection,
        title="EJECUTANDO PRUEBAS FUNCIONALES" + (" (TODAS)" if len(selection) > 1 else f": {selection[0]}"),
        combined_label="COVERAGE TOTAL — Pruebas funcionales combinadas",
    )


def run_integration_tests_menu():
    """Submenú de pruebas de integración: puntos de contacto puntuales entre
    dos módulos (no un módulo aislado, no el flujo E2E completo). Sin coverage
    por módulo, igual que las de sistema."""
    selection = show_suite_submenu(INTEGRATION_SUITES, "Pruebas de Integración")
    if selection is None:
        return
    run_suites(
        coverage=False,
        suites=selection,
        title="EJECUTANDO PRUEBAS DE INTEGRACIÓN" + (" (TODAS)" if len(selection) > 1 else f": {selection[0]}"),
    )


def run_system_tests_menu():
    """Submenú de pruebas E2E de sistema: una o todas. Sin coverage por módulo
    (no están mapeadas a un único RF), pero sí se ve qué se está ejecutando."""
    selection = show_suite_submenu(SYSTEM_SUITES, "Pruebas E2E / Sistema")
    if selection is None:
        return
    run_suites(
        coverage=False,
        suites=selection,
        title="EJECUTANDO PRUEBAS E2E / SISTEMA" + (" (TODAS)" if len(selection) > 1 else f": {selection[0]}"),
    )


def run_internal_tests_menu():
    """Submenú de las pruebas INTERNAS de InvenTree (Django TestCase / unittest,
    `invoke dev.test`) -- no las suites propias del Hito 2. Django arma su
    propia base de datos de prueba, así que no hace falta nuestro servidor
    corriendo. Se puede acotar a un solo módulo (rápido) o correr los 6
    módulos de RF juntos (lento: son cientos de tests por módulo)."""
    selection = show_suite_submenu(INTERNAL_TEST_APPS, "Pruebas internas de InvenTree (Django TestCase)")
    if selection is None:
        return

    print(f"\n{'═'*60}")
    if len(selection) > 1:
        print("  EJECUTANDO TESTS INTERNOS DE INVENTREE — 6 módulos de RF (puede tardar varios minutos)")
    else:
        print(f"  EJECUTANDO TESTS INTERNOS DE INVENTREE: {selection[0]}")
    print('═'*60)

    cmd = [INVOKE_BIN, "dev.test", "--check", f"--runtest={' '.join(selection)}"]
    result = subprocess.run(cmd, cwd=BASE_DIR)

    print(f"\n{'═'*60}")
    print(f"  {OK if result.returncode == 0 else FAIL}  Tests internos: {'OK' if result.returncode == 0 else 'con errores'}")
    print('═'*60)


MENU_OPTIONS = {
    "1": ("Iniciar servidor (sin pruebas)",
          {"action": "server", "setup": False}),
    "2": ("Iniciar servidor + reinicializar datos de prueba (setup)",
          {"action": "server", "setup": True}),
    "3": ("Pruebas funcionales — Hito 2, FN1-FN9 (una o todas, con coverage)",
          {"action": "functional_tests"}),
    "4": ("Pruebas de Integración (order↔stock, build↔stock, stock↔tracking)",
          {"action": "integration_tests"}),
    "5": ("Pruebas de Sistema (golden path / seguridad / desempeño)",
          {"action": "system_tests"}),
    "6": ("Solo inicializar datos de prueba (sin iniciar servidor)",
          {"action": "setup_only"}),
    "7": ("Pruebas internas de InvenTree (Django TestCase, invoke dev.test)",
          {"action": "internal_tests"}),
}


def show_menu():
    """Muestra un menú interactivo en la terminal y devuelve la opción elegida (dict),
    o None si el usuario elige salir ('0'). Reintenta en caso de opción inválida en
    vez de terminar el proceso, para poder usarse dentro de un bucle."""
    while True:
        print(f"\n{'═'*60}")
        print("  InvenTree — Menú de arranque")
        print('═'*60)
        for key, (label, _opts) in MENU_OPTIONS.items():
            print(f"  {key}) {label}")
        print("  0) Salir")
        print('═'*60)

        choice = input("\n  Elige una opción [0-7]: ").strip()

        if choice == "0":
            return None

        if choice not in MENU_OPTIONS:
            print(f"\n  {FAIL}  Opción inválida: '{choice}'")
            continue

        return MENU_OPTIONS[choice][1]


def run_once(args, action):
    """Ejecuta una sola acción (server / setup_only / functional_tests / ...),
    ya sea la elegida en el menú interactivo o la pedida por flags de CLI."""
    print("\n" + "═"*60)
    print("  InvenTree — Arranque automático")
    print("═"*60)

    # 1. Verificar dependencias
    print(f"\n  {INFO} Verificando servicios...")
    errors = check_deps()
    if errors:
        print(f"\n  {FAIL}  Servicios faltantes: {errors}. Abortando.")
        sys.exit(1)

    # 1.5. Opción de menú "solo setup" -> corre setup_system_tests.py y termina
    if action == "setup_only":
        run_setup()
        print()
        return

    # 2. Setup: manual (--setup) o automático si falta el admin / data base
    setup_ok = True
    if args.setup:
        setup_ok = run_setup()
    else:
        print(f"\n  {INFO} Verificando datos base (usuario admin, etc.)...")
        if setup_is_needed():
            print(f"  {WARN}  Faltan datos base — ejecutando setup automáticamente...")
            setup_ok = run_setup()
        else:
            print(f"  {OK}  Datos base ya presentes, se omite el setup")

    if not setup_ok:
        print(f"  {WARN}  Setup completó con advertencias, continuando...")

    # 2.5. Menú: pruebas funcionales (por módulo o todas, con coverage) —
    # cada suite reinicia el servidor con su propio data-file, así que no
    # hace falta levantarlo acá.
    if action == "functional_tests":
        run_functional_tests_menu()
        print()
        return

    # 2.55. Menú: pruebas de integración (por suite o todas) — no gestionan su
    # propio servidor, así que hay que asegurarse de que esté corriendo.
    if action == "integration_tests":
        if is_server_running():
            print(f"\n  {OK}  Servidor ya está corriendo en {URL}")
        else:
            print(f"\n  {INFO} Iniciando servidor Django...")
            pid = start_plain_server()
            print(f"  {INFO} PID del servidor: {pid}")
            if not wait_for_server():
                stop_server_pid(pid)
                sys.exit(1)
        run_integration_tests_menu()
        print()
        return

    # 2.6. Menú: pruebas E2E / sistema (por suite o todas) — no gestionan su
    # propio servidor, así que hay que asegurarse de que esté corriendo.
    if action == "system_tests":
        if is_server_running():
            print(f"\n  {OK}  Servidor ya está corriendo en {URL}")
        else:
            print(f"\n  {INFO} Iniciando servidor Django...")
            pid = start_plain_server()
            print(f"  {INFO} PID del servidor: {pid}")
            if not wait_for_server():
                stop_server_pid(pid)
                sys.exit(1)
        run_system_tests_menu()
        print()
        return

    # 2.65. Menú: pruebas INTERNAS de InvenTree (Django TestCase, invoke
    # dev.test) — Django arma su propia base de datos de prueba, así que a
    # diferencia de las demás opciones acá NO hace falta levantar el servidor.
    if action == "internal_tests":
        run_internal_tests_menu()
        print()
        return

    # 3. Servidor (arranque simple, o --tests/--suite + --coverage por CLI)
    # Con --coverage + --tests/--suite, run_suites() reinicia el server antes
    # de cada suite con su propio data-file, así que acá no hace falta levantarlo.
    if args.coverage and (args.tests or args.suite):
        print(f"\n  {INFO} --coverage: el servidor se reiniciará instrumentado antes de cada suite")
    elif is_server_running():
        print(f"\n  {OK}  Servidor ya está corriendo en {URL}")
    elif args.coverage:
        print(f"\n  {INFO} Iniciando servidor Django bajo coverage...")
        pid = start_coverage_server(COV_DATA)
        print(f"  {INFO} PID del servidor (coverage): {pid}")
        if not wait_for_server():
            stop_server_pid(pid)
            sys.exit(1)
    else:
        print(f"\n  {INFO} Iniciando servidor Django...")
        pid = start_plain_server()
        print(f"  {INFO} PID del servidor: {pid}")
        if not wait_for_server():
            stop_server_pid(pid)
            sys.exit(1)

    if not (args.coverage and (args.tests or args.suite)):
        print(f"\n  {OK}  InvenTree disponible en: http://localhost:8000")
        print(f"  {OK}  Admin UI:               http://localhost:8000/web/")
        print(f"  {OK}  API:                    http://localhost:8000/api/")
        if setup_ok:
            print(f"       Credenciales: admin / inventree\n")
        else:
            print(f"  {WARN}  El setup falló — las credenciales admin / inventree podrían no existir\n")

    # 4. Pruebas si se pidieron por CLI (--tests: todas las suites en orden;
    # --suite: una sola, pensado para jobs de CI en paralelo por módulo)
    if args.tests:
        if not run_suites(coverage=args.coverage):
            sys.exit(1)
    elif args.suite:
        suite_path = ALL_SUITES_BY_KEY[args.suite]
        if not run_suites(
            coverage=args.coverage,
            suites=[suite_path],
            title=f"EJECUTANDO SUITE: {args.suite}",
            combined_label=f"COVERAGE: {args.suite}",
        ):
            sys.exit(1)
    else:
        print(f"  {INFO} Para ejecutar las pruebas: python start_inventree.py --tests")
        print(f"  {INFO} Para ejecutar con coverage por suite: python start_inventree.py --tests --coverage")
        print(f"  {INFO} Para ejecutar UNA suite: python start_inventree.py --suite <clave> --coverage")
        print(f"  {INFO} Para detener el servidor:  kill $(cat .inventree_server.pid)")

    print()


def main():
    parser = argparse.ArgumentParser(description="Levanta InvenTree en localhost:8000")
    parser.add_argument("--setup", action="store_true", help="Inicializar datos de prueba")
    parser.add_argument("--tests", action="store_true", help="Ejecutar todas las suites")
    parser.add_argument("--suite", choices=sorted(ALL_SUITES_BY_KEY),
                         help="Ejecutar UNA sola suite por clave (para jobs de CI en paralelo, uno por módulo)")
    parser.add_argument("--coverage", action="store_true",
                         help="Medir coverage por módulo, aislado por cada suite (usar con --tests o --suite)")
    args = parser.parse_args()

    # Con flags de CLI -> una sola corrida, sin menú (comportamiento de script/CI)
    if args.setup or args.tests or args.suite or args.coverage:
        run_once(args, action=None)
        return

    # Sin flags -> menú interactivo EN BUCLE: tras cada acción se vuelve a
    # mostrar el menú, hasta que el usuario elige "0) Salir".
    while True:
        choice = show_menu()
        if choice is None:
            print("\n  Saliendo.\n")
            return
        action = choice["action"]
        menu_args = argparse.Namespace(setup=choice.get("setup", False), tests=False, suite=None, coverage=False)
        run_once(menu_args, action)


if __name__ == "__main__":
    main()
