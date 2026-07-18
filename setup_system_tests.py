#!/usr/bin/env python3
"""
setup_system_tests.py — Inicializa la base de datos de InvenTree para pruebas de sistema.

Carga fixtures/system_test_base.yaml (única fuente de verdad de los datos base)
vía `manage.py loaddata`, y garantiza que existan:
  - Usuarios                : admin / inventree (superuser), testviewer / viewer123 (sin permisos)
  - Categorías de partes    : pk 1 (Electrónicos), pk 3 (Ensambles)
  - Partes                  : pk 1 (Resistencia 10k), 2 (Capacitor 100uF), 3 (LED Rojo),
                              pk 5 (PCB Sensor v1 — assembly con BOM),
                              pk 10 (Módulo Ensamble Test — assembly sin BOM)
  - Ubicaciones de stock    : pk 1-4 (Almacén A/B/C, Cajón 1)
  - Proveedor               : pk 1 (Proveedor Electrónico SA)
  - Cliente                 : pk 2 (Cliente Distribuidor SA)
  - SupplierParts           : pk 1-3 vinculando partes 1/2/3 al proveedor 1
  - BOM de PCB Sensor v1    : 10x Resistencia, 2x Capacitor, 3x LED

Uso:
    python setup_system_tests.py          # setup completo (carga el fixture)
    python setup_system_tests.py --clean  # limpia stock + ordenes de prueba antes del setup
    python setup_system_tests.py --verify # solo verifica sin modificar
"""
import os, sys, argparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PATH = os.path.join(PROJECT_ROOT, "fixtures", "system_test_base.yaml")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "backend", "InvenTree"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "InvenTree.settings")

import django
django.setup()

from django.core.management import call_command
from django.contrib.auth.models import User
from part.models import Part, PartCategory
from part.models import BomItem
from stock.models import StockItem, StockLocation
from company.models import Company, SupplierPart

OK   = "  ✅"
FAIL = "  ❌"
INFO = "  ℹ️ "

# ═══════════════════════════════════════════════════════════════
# Datos base
# ═══════════════════════════════════════════════════════════════

CATEGORIES = [
    {"pk": 1, "name": "Electrónicos", "description": "Componentes electrónicos generales"},
    {"pk": 3, "name": "Ensambles",    "description": "Módulos y ensambles de componentes"},
]

PARTS = [
    {"pk": 1,  "name": "Resistencia 10k",      "description": "Resistencia 10 kΩ 1/4W 5%",                    "category_pk": 1, "assembly": False, "purchaseable": True,  "salable": False},
    {"pk": 2,  "name": "Capacitor 100uF",       "description": "Capacitor electrolítico 100µF 25V",             "category_pk": 1, "assembly": False, "purchaseable": True,  "salable": False},
    {"pk": 3,  "name": "LED Rojo",              "description": "LED rojo 5mm 20mA",                             "category_pk": 1, "assembly": False, "purchaseable": True,  "salable": False},
    {"pk": 5,  "name": "PCB Sensor v1",         "description": "Placa de circuito para módulo sensor",          "category_pk": 3, "assembly": True,  "purchaseable": False, "salable": True},
    {"pk": 10, "name": "Módulo Ensamble Test",  "description": "Ensamble de prueba sin BOM — Build Order tests", "category_pk": 3, "assembly": True,  "purchaseable": False, "salable": True},
]

CUSTOMER = {"pk": 2, "name": "Cliente Distribuidor SA", "is_customer": True}

REGULAR_USER = {"pk": 2, "username": "testviewer", "password": "viewer123", "email": "viewer@inventree.local"}

LOCATIONS = [
    {"pk": 1, "name": "Almacén A", "description": "Almacén principal A",       "parent_pk": None},
    {"pk": 2, "name": "Almacén B", "description": "Almacén secundario B",      "parent_pk": None},
    {"pk": 3, "name": "Almacén C", "description": "Almacén terciario C",       "parent_pk": None},
    {"pk": 4, "name": "Cajón 1",   "description": "Cajón dentro de Almacén A", "parent_pk": 1},
]

SUPPLIER = {"pk": 1, "name": "Proveedor Electrónico SA", "is_supplier": True}

SUPPLIER_PARTS = [
    {"pk": 1, "part_pk": 1, "supplier_pk": 1, "SKU": "RES-10K-001"},
    {"pk": 2, "part_pk": 2, "supplier_pk": 1, "SKU": "CAP-100UF-001"},
    {"pk": 3, "part_pk": 3, "supplier_pk": 1, "SKU": "LED-RED-001"},
]

# BOM para pk=5 (PCB Sensor v1)
BOM_ITEMS = [
    {"part_pk": 5, "sub_part_pk": 1, "quantity": 10},
    {"part_pk": 5, "sub_part_pk": 2, "quantity": 2},
    {"part_pk": 5, "sub_part_pk": 3, "quantity": 3},
]


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def section(title):
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def load_base_fixture():
    """Carga fixtures/system_test_base.yaml (admin, testviewer, categorías,
    partes, ubicaciones, proveedor, cliente, supplier parts y BOM)."""
    try:
        call_command("loaddata", FIXTURE_PATH, verbosity=0)
        print(f"{OK}  Fixture base cargado desde {os.path.relpath(FIXTURE_PATH, PROJECT_ROOT)}")
        return True
    except Exception as e:
        print(f"{FAIL}  Error cargando fixture base: {e}"); return False


def clean_test_data():
    """Limpia stock items y órdenes de prueba (PO/Build con referencia de test)."""
    from order.models import PurchaseOrder
    from build.models import Build

    n = StockItem.objects.count()
    StockItem.objects.all().delete()
    print(f"{OK}  {n} stock items eliminados")

    po_qs = PurchaseOrder.objects.filter(reference__startswith="PO-99")
    n_po = po_qs.count()
    po_qs.delete()
    print(f"{OK}  {n_po} Purchase Orders de prueba (PO-99xx) eliminadas")

    b_qs = Build.objects.filter(reference__startswith="BO-99")
    n_b = b_qs.count()
    b_qs.delete()
    print(f"{OK}  {n_b} Build Orders de prueba (BO-99xx) eliminadas")


def verify():
    all_ok = True
    section("VERIFICACIÓN DE DATOS BASE")

    from django.contrib.auth import authenticate
    try:
        u = User.objects.get(pk=1, username="admin")
        valid = authenticate(username="admin", password="inventree") is not None
        print(f"{OK}  admin pk=1 superuser={u.is_superuser} pass={'✅' if valid else '❌'}")
        if not valid: all_ok = False
    except User.DoesNotExist:
        print(f"{FAIL}  Usuario admin NO EXISTE"); all_ok = False

    for cat in CATEGORIES:
        try:
            PartCategory.objects.get(pk=cat["pk"])
            print(f"{OK}  Categoría pk={cat['pk']} '{cat['name']}'")
        except PartCategory.DoesNotExist:
            print(f"{FAIL}  Categoría pk={cat['pk']} FALTA"); all_ok = False

    for p in PARTS:
        try:
            obj = Part.objects.get(pk=p["pk"])
            flag = "assembly" if obj.assembly else "componente"
            print(f"{OK}  Parte pk={p['pk']} '{obj.name}' ({flag}, active={obj.active})")
            if not obj.active: all_ok = False
        except Part.DoesNotExist:
            print(f"{FAIL}  Parte pk={p['pk']} FALTA"); all_ok = False

    for loc in LOCATIONS:
        try:
            StockLocation.objects.get(pk=loc["pk"])
            print(f"{OK}  Ubicación pk={loc['pk']} '{loc['name']}'")
        except StockLocation.DoesNotExist:
            print(f"{FAIL}  Ubicación pk={loc['pk']} FALTA"); all_ok = False

    try:
        Company.objects.get(pk=1, is_supplier=True)
        print(f"{OK}  Proveedor pk=1 'Proveedor Electrónico SA'")
    except Company.DoesNotExist:
        print(f"{FAIL}  Proveedor pk=1 FALTA"); all_ok = False

    try:
        Company.objects.get(pk=CUSTOMER["pk"], is_customer=True)
        print(f"{OK}  Cliente pk={CUSTOMER['pk']} '{CUSTOMER['name']}'")
    except Company.DoesNotExist:
        print(f"{FAIL}  Cliente pk={CUSTOMER['pk']} FALTA"); all_ok = False

    try:
        u = User.objects.get(pk=REGULAR_USER["pk"])
        print(f"{OK}  Usuario testviewer pk={REGULAR_USER['pk']} is_superuser={u.is_superuser}")
    except User.DoesNotExist:
        print(f"{FAIL}  Usuario testviewer pk={REGULAR_USER['pk']} FALTA"); all_ok = False

    for sp in SUPPLIER_PARTS:
        try:
            SupplierPart.objects.get(pk=sp["pk"])
            print(f"{OK}  SupplierPart pk={sp['pk']} SKU={sp['SKU']}")
        except SupplierPart.DoesNotExist:
            print(f"{FAIL}  SupplierPart pk={sp['pk']} FALTA"); all_ok = False

    bom_count = BomItem.objects.filter(part_id=5).count()
    print(f"{OK}  BOM de PCB Sensor v1: {bom_count} ítems" if bom_count >= 3
          else f"{FAIL}  BOM de PCB Sensor v1 incompleto ({bom_count} ítems)")
    if bom_count < 3: all_ok = False

    salable_ok = Part.objects.get(pk=5).salable
    print(f"{OK}  PCB Sensor v1 salable=True" if salable_ok else f"{FAIL}  PCB Sensor v1 salable=False")
    if not salable_ok: all_ok = False

    print(f"{INFO} Stock items: {StockItem.objects.count()}")
    return all_ok


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Setup BD InvenTree para pruebas de sistema")
    parser.add_argument("--clean",  action="store_true", help="Limpiar stock y órdenes de prueba")
    parser.add_argument("--verify", action="store_true", help="Solo verificar sin modificar")
    args = parser.parse_args()

    print("\n" + "═" * 60)
    print("  InvenTree — Setup de Pruebas de Sistema")
    print("═" * 60)

    if args.verify:
        ok = verify()
        print("\n" + "═" * 60)
        print("  ✅  LISTO" if ok else "  ❌  FALTAN DATOS")
        print("═" * 60 + "\n")
        sys.exit(0 if ok else 1)

    results = []

    section("LIMPIEZA")
    if args.clean:
        clean_test_data()
    else:
        print(f"{INFO} Stock items: {StockItem.objects.count()} (--clean para limpiar)")

    section("FIXTURE BASE")
    results.append(load_base_fixture())

    section("RESULTADO FINAL")
    ok = verify()
    results.append(ok)

    print("\n" + "═" * 60)
    if all(results):
        print("  ✅  SETUP COMPLETO — Base de datos lista para pruebas")
        print("\n  Menú interactivo (recomendado): python start_inventree.py")
        print("    3) Pruebas funcionales — Hito 2, FN1-FN9 (una por módulo o todas, con coverage)")
        print("    4) Pruebas de Integración (order↔stock, build↔stock, stock↔tracking)")
        print("    5) Pruebas de Sistema (golden path / seguridad / desempeño, una o todas)")
        print("\n  Suites individuales (equivalente por CLI):")
        print("    python tests/funcionales/test_part_inventree_suite.py              (FN1 Partes + FN6 Categorías + FN5 BOM)")
        print("    python tests/funcionales/test_stock_inventree_suite.py             (FN2/FN3 Stock)")
        print("    python tests/funcionales/test_order_inventree_suite.py             (FN4 PO + SO/RO/Transfer Order)")
        print("    python tests/funcionales/test_build_inventree_suite.py             (FN8 Build Orders)")
        print("    python tests/funcionales/test_company_inventree_suite.py           (FN7 Proveedores)")
        print("    python tests/funcionales/test_users_inventree_suite.py             (FN9 Autenticación)")
        print("    python tests/integracion/test_integracion_inventree_suite.py       (Integración)")
        print("    python tests/sistema/test_sistema_golden_path_inventree_suite.py   (Sistema — E2E)")
        print("    python tests/sistema/test_sistema_seguridad_inventree_suite.py     (Sistema — Seguridad)")
        print("    python tests/sistema/test_sistema_desempeno_inventree_suite.py     (Sistema — Desempeño)")
        print("\n  O todas juntas por CLI: python start_inventree.py --tests [--coverage]")
    else:
        print("  ❌  SETUP INCOMPLETO — Revisa los errores anteriores")
    print("═" * 60 + "\n")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
