#!/usr/bin/env python3
"""
InvenTree — Suite funcional: Usuarios / Autenticación (test_users_inventree_suite.py)
FN9  Autenticación / Identidad  (RF-001, Hito 2)

Incluye:
  TC-L01..L06  — Login / Logout (API + UI React SPA)
  FN9-*        — Casos extendidos de cobertura (/user/me/, tokens, owner,
                 group, ruleset, set-password)

Strategy:
- API tests  : requests + Basic Auth (no session state, no rate-limit risk)
- UI tests   : Playwright con sesión inyectada vía cookies (login por requests)
- Rate limit reset (5/min) vía cache.clear() entre pruebas de login negativo
"""
import json, os, subprocess, sys
import requests
from playwright.sync_api import sync_playwright

BASE_URL   = "http://127.0.0.1:8000"
API_URL    = f"{BASE_URL}/api"
VALID_USER = "admin"
VALID_PASS = "inventree"
MANAGE     = "src/backend/InvenTree/manage.py"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SS_DIR       = os.path.join(PROJECT_ROOT, "test_output", "screenshots", "users")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "test_output", "results", "users_results.json")
os.makedirs(SS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

AUTH = (VALID_USER, VALID_PASS)
VIEWER_AUTH = ("testviewer", "viewer123")
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
    return fn(f"{API_URL}{path}", **kw)

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

def clear_rate_limits():
    """Reset allauth login rate limits (5/min) via Django cache."""
    env = {**os.environ,
           "INVENTREE_SITE_URL": BASE_URL,
           "INVENTREE_DEBUG": "True",
           "INVENTREE_DB_ENGINE": "sqlite3",
           "INVENTREE_DB_NAME": "/tmp/test_inventree.db"}
    subprocess.run([sys.executable, MANAGE, "shell", "-c",
                    "from django.core.cache import cache; cache.clear()"],
                   env=env, capture_output=True)

def get_session_cookies():
    """Login via allauth API and return (sessionid, csrftoken) tuple."""
    s = requests.Session()
    s.get(f"{API_URL}/auth/v1/config")
    csrf = s.cookies.get("csrftoken")
    s.post(f"{API_URL}/auth/v1/auth/login",
           json={"username": VALID_USER, "password": VALID_PASS},
           headers={"X-CSRFToken": csrf, "Referer": BASE_URL})
    return s.cookies.get("sessionid"), s.cookies.get("csrftoken")

def new_authed_page(browser, session_id, csrf_token):
    """Return a Playwright page pre-loaded with a valid session."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([
        {"name": "sessionid", "value": session_id, "domain": "127.0.0.1", "path": "/"},
        {"name": "csrftoken", "value": csrf_token, "domain": "127.0.0.1", "path": "/"},
    ])
    return ctx.new_page(), ctx


# ══════════════════════════════════════════════════════════════
# ST-001 / FN9 — LOGIN / LOGOUT (API + UI)
# ══════════════════════════════════════════════════════════════

def tc_l01(browser):
    """TC-L01 — Login credenciales válidas (API + captura UI)."""
    try:
        sid, ctoken = get_session_cookies()
        ok = bool(sid)
        page, ctx = new_authed_page(browser, sid, ctoken)
        page.goto(f"{BASE_URL}/web/", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        snap(page, "TC-L01_dashboard_logged_in")
        on_dash = "/login" not in page.url
        ok = ok and on_dash
        log("TC-L01", "Inicio de sesión con credenciales válidas", ok,
            f"sessionid={'OK' if sid else 'NONE'} — UI URL: {page.url}")
        ctx.close()
    except Exception as e:
        log("TC-L01", "Inicio de sesión con credenciales válidas", False, str(e))

def tc_l02(browser):
    """TC-L02 — Logout."""
    try:
        sid, ctoken = get_session_cookies()
        page, ctx = new_authed_page(browser, sid, ctoken)
        page.goto(f"{BASE_URL}/web/", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        snap(page, "TC-L02_before_logout")

        logout = page.evaluate(f"""
            async () => {{
                const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                const r = await fetch('{BASE_URL}/api/auth/v1/auth/session', {{
                    method: 'DELETE',
                    headers: {{'X-CSRFToken': csrf}},
                    credentials: 'include'
                }});
                return r.status;
            }}
        """)
        page.wait_for_timeout(800)
        snap(page, "TC-L02_after_logout")

        post = page.evaluate(f"""
            async () => {{
                const r = await fetch('{BASE_URL}/api/user/', {{credentials: 'include'}});
                return r.status;
            }}
        """)
        # allauth headless: DELETE /session returns 401 with is_authenticated=false (logout OK)
        ok = logout in (200, 204, 401) and post == 401
        log("TC-L02", "Cerrar sesión", ok,
            f"DELETE HTTP {logout} (401=logout OK en allauth) — /api/user/ post-logout: {post}")
        ctx.close()
    except Exception as e:
        log("TC-L02", "Cerrar sesión", False, str(e))

def tc_l03(browser):
    """TC-L03 — Login contraseña incorrecta."""
    clear_rate_limits()
    try:
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx2.new_page()
        page.goto(f"{BASE_URL}/api/auth/v1/config", wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        result = page.evaluate(f"""
            async () => {{
                const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                const r = await fetch('{BASE_URL}/api/auth/v1/auth/login', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'X-CSRFToken': csrf}},
                    credentials: 'include',
                    body: JSON.stringify({{username: 'admin', password: 'CLAVE_ERRONEA_999'}})
                }});
                const body = await r.json();
                return {{status: r.status, body: JSON.stringify(body)}};
            }}
        """)
        snap(page, "TC-L03_wrong_password")
        ok = result["status"] in (400, 401, 403)
        body = json.loads(result["body"]) if result.get("body") else {}
        msg = body.get("errors", [{}])[0].get("message", "") if isinstance(body, dict) else ""
        log("TC-L03", "Inicio de sesión con contraseña incorrecta", ok,
            f"HTTP {result['status']} — '{msg[:80]}'")
        ctx2.close()
    except Exception as e:
        log("TC-L03", "Inicio de sesión con contraseña incorrecta", False, str(e))

def tc_l04(browser):
    """TC-L04 — Login usuario inexistente."""
    clear_rate_limits()
    try:
        ctx4 = browser.new_context(viewport={"width": 1280, "height": 900})
        page4 = ctx4.new_page()
        page4.goto(f"{BASE_URL}/api/auth/v1/config", wait_until="domcontentloaded")
        page4.wait_for_timeout(800)
        result4 = page4.evaluate(f"""
            async () => {{
                const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                const r = await fetch('{BASE_URL}/api/auth/v1/auth/login', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json', 'X-CSRFToken': csrf}},
                    credentials: 'include',
                    body: JSON.stringify({{username: 'usuariofantasma77', password: 'clave_falsa'}})
                }});
                const body = await r.json();
                return {{status: r.status, body: JSON.stringify(body)}};
            }}
        """)
        snap(page4, "TC-L04_unknown_user")
        ok4 = result4["status"] in (400, 401, 403)
        body4 = json.loads(result4["body"]) if result4.get("body") else {}
        msg4 = body4.get("errors", [{}])[0].get("message", "") if isinstance(body4, dict) else ""
        log("TC-L04", "Inicio de sesión con usuario inexistente", ok4,
            f"HTTP {result4['status']} — '{msg4[:80]}'")
        ctx4.close()
    except Exception as e:
        log("TC-L04", "Inicio de sesión con usuario inexistente", False, str(e))

def tc_l05(browser):
    """TC-L05 — Login campos vacíos (React SPA UI)."""
    clear_rate_limits()
    try:
        ctx5 = browser.new_context(viewport={"width": 1280, "height": 900})
        page5 = ctx5.new_page()
        page5.goto(f"{BASE_URL}/web/login", wait_until="domcontentloaded")
        page5.wait_for_timeout(4000)
        snap(page5, "TC-L05_empty_form")

        btn = page5.locator("button[type='submit']")
        if btn.count() > 0:
            btn.first.click()
            page5.wait_for_timeout(2500)
        snap(page5, "TC-L05_empty_form_after_click")

        auth_st = page5.evaluate(f"""
            async () => {{
                const r = await fetch('{BASE_URL}/api/user/', {{credentials: 'include'}});
                return r.status;
            }}
        """)
        ok5 = auth_st != 200
        log("TC-L05", "Inicio de sesión con campos vacíos", ok5,
            f"/api/user/ status={auth_st} (esperado 401, 200=defecto)")
        ctx5.close()
    except Exception as e:
        log("TC-L05", "Inicio de sesión con campos vacíos", False, str(e))

def tc_l06(browser):
    """TC-L06 — Login UI React SPA — flujo visual completo."""
    clear_rate_limits()
    page6 = None
    try:
        ctx6 = browser.new_context(viewport={"width": 1280, "height": 900})
        page6 = ctx6.new_page()
        page6.goto(f"{BASE_URL}/web/login", wait_until="domcontentloaded")
        page6.wait_for_timeout(4500)
        snap(page6, "TC-L06_react_login_page")

        page6.wait_for_selector("input[aria-label='login-username']", timeout=8000)
        page6.fill("input[aria-label='login-username']", VALID_USER)
        page6.fill("input[aria-label='login-password']", VALID_PASS)
        snap(page6, "TC-L06_credentials_filled")

        page6.locator("button[type='submit']").first.click()
        page6.wait_for_timeout(5000)
        snap(page6, "TC-L06_after_submit")

        final_url = page6.url
        not_login = "/login" not in final_url
        log("TC-L06", "Inicio de sesión en UI React SPA (flujo visual)", not_login,
            f"URL final: {final_url}")
        ctx6.close()
    except Exception as e:
        if page6:
            snap(page6, "TC-L06_error")
        log("TC-L06", "Inicio de sesión en UI React SPA (flujo visual)", False, str(e))


# ══════════════════════════════════════════════════════════════
# FN9 — Autenticación / Identidad: casos extendidos de cobertura
# /user/me/, tokens, owner, group, ruleset, set-password — que
# TC-L01..L06 no tocan.
# ══════════════════════════════════════════════════════════════

def fn9_me():
    r = api("get", "/user/me/")
    log("FN9-ME-detail", "GET /user/me/", r.status_code == 200, f"HTTP {r.status_code}")
    r = api("get", "/user/me/profile/")
    log("FN9-ME-profile", "GET /user/me/profile/", r.status_code == 200, f"HTTP {r.status_code}")
    r = api("get", "/user/me/roles/")
    log("FN9-ME-roles", "GET /user/me/roles/", r.status_code == 200, f"HTTP {r.status_code}")

def fn9_tokens():
    r = api("post", "/user/tokens/", {"name": "coverage-token"})
    ok = r.status_code == 201
    log("FN9-TOKEN-create", "Crear API token", ok, f"HTTP {r.status_code}")
    pk = (r.json().get("id") or r.json().get("pk")) if ok else None
    token_key = r.json().get("token") if ok else None
    r2 = api("get", "/user/tokens/")
    log("FN9-TOKEN-list", "Listar tokens", r2.status_code == 200, f"HTTP {r2.status_code}")

    # Usar el token real (Authorization: Token <key>) en vez de Basic Auth ->
    # ejercita ApiTokenAuthentication.authenticate_credentials() (nunca se
    # cubre con auth=(USER, PASS) en el resto de la suite)
    if token_key:
        r3 = requests.get(f"{API_URL}/user/me/", headers={"Authorization": f"Token {token_key}"})
        log("FN9-TOKEN-auth", "Usar API token real para autenticar (Authorization: Token)", r3.status_code == 200, f"HTTP {r3.status_code} {short(r3)}")
        # Segunda llamada el mismo día -> last_seen ya == today, cubre la rama contraria
        r4 = requests.get(f"{API_URL}/user/me/", headers={"Authorization": f"Token {token_key}"})
        log("FN9-TOKEN-auth-again", "Reautenticar con el mismo token (last_seen ya actualizado hoy)", r4.status_code == 200, f"HTTP {r4.status_code}")

    # -- ApiTokenAuthentication: token revocado / expirado (debe rechazar) --
    if pk and token_key:
        r_revoke = api("patch", f"/user/tokens/{pk}/", {"revoked": True})
        if r_revoke.status_code == 200:
            r_revoked_auth = requests.get(f"{API_URL}/user/me/", headers={"Authorization": f"Token {token_key}"})
            log("COV-TOKEN-revoked", "Autenticar con token revocado (debe rechazar)", r_revoked_auth.status_code == 401, f"HTTP {r_revoked_auth.status_code}")

    r_exptoken = api("post", "/user/tokens/", {"name": "coverage-expired-token", "expiry": "2020-01-01"})
    if r_exptoken.status_code == 201:
        exp_key = r_exptoken.json().get("token")
        exp_pk = r_exptoken.json().get("id") or r_exptoken.json().get("pk")
        if exp_key:
            r_expired_auth = requests.get(f"{API_URL}/user/me/", headers={"Authorization": f"Token {exp_key}"})
            log("COV-TOKEN-expired", "Autenticar con token expirado (debe rechazar)", r_expired_auth.status_code == 401, f"HTTP {r_expired_auth.status_code}")
        if exp_pk:
            api("delete", f"/user/tokens/{exp_pk}/")

    if pk:
        api("delete", f"/user/tokens/{pk}/")

    # GetAuthToken (/user/me/token/): endpoint GET basado en sesión (no en
    # /user/tokens/, es un flujo distinto usado por la UI web) -> crea o
    # reutiliza un token por nombre para el usuario ya logueado
    sid, csrf = get_session_cookies()
    if sid:
        s = requests.Session()
        s.cookies.set("sessionid", sid)
        s.cookies.set("csrftoken", csrf)
        r_gat = s.get(f"{API_URL}/user/me/token/", params={"name": "coverage-session-token"}, headers={"X-CSRFToken": csrf})
        ok_gat = r_gat.status_code == 200
        log("FN9-TOKEN-getauth", "GetAuthToken vía sesión (/user/me/token/)", ok_gat, f"HTTP {r_gat.status_code} {str(r_gat.text)[:150]}")
        # Segunda llamada con el mismo nombre -> reutiliza el token existente (rama "if not token" no se repite)
        r_gat2 = s.get(f"{API_URL}/user/me/token/", params={"name": "coverage-session-token"}, headers={"X-CSRFToken": csrf})
        log("FN9-TOKEN-getauth-reuse", "GetAuthToken reutilizando token existente por nombre", r_gat2.status_code == 200, f"HTTP {r_gat2.status_code}")

def fn9_owner():
    r = api("get", "/user/owner/")
    log("FN9-OWNER-list", "Listar Owners", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = api("get", "/user/owner/", params={"is_active": "true"})
    log("FN9-OWNER-is_active", "Filtro Owner ?is_active=true", r2.status_code == 200, f"HTTP {r2.status_code}")
    r3 = api("get", "/user/owner/", params={"is_active": "false"})
    log("FN9-OWNER-is_active-false", "Filtro Owner ?is_active=false", r3.status_code == 200, f"HTTP {r3.status_code}")
    r4 = api("get", "/user/owner/", params={"search": "admin"})
    log("FN9-OWNER-search", "Búsqueda de texto en Owner ?search=admin", r4.status_code == 200, f"HTTP {r4.status_code}")

def fn9_group_ruleset():
    r = api("post", "/user/group/", {"name": "COV Test Group"})
    ok = r.status_code == 201
    log("FN9-GROUP-create", "Crear Group", ok, f"HTTP {r.status_code} {short(r)}")
    pk = r.json().get("pk") if ok else None
    if pk:
        r2 = api("get", "/user/ruleset/", params={"group": pk})
        log("FN9-RULESET-list", "Listar RuleSets ?group=", r2.status_code == 200, f"HTTP {r2.status_code}")
        api("delete", f"/user/group/{pk}/")

def fn9_user_setpassword():
    r = api("get", "/user/")
    log("FN9-USER-list", "Listar usuarios", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = api("get", "/user/2/")
    log("FN9-USER-detail", "Detalle de usuario testviewer (pk=2)", r2.status_code == 200, f"HTTP {r2.status_code}")
    r3 = api("put", "/user/2/set-password/", {"password": "viewer123-new", "password2": "viewer123-new"})
    ok3 = r3.status_code in (200, 201)
    log("FN9-USER-setpassword", "Set-password de testviewer", ok3, f"HTTP {r3.status_code}")
    if ok3:
        # override_warning=True es OBLIGATORIO acá: "viewer123" es rechazado por
        # UserAttributeSimilarityValidator (similar al email viewer@inventree.local),
        # así que sin este flag el revert falla en silencio y deja a testviewer con
        # la contraseña "viewer123-new" -> rompe la suite de permisos/trazabilidad
        # (que depende de credenciales fijas ("testviewer", "viewer123")) en la siguiente corrida.
        r_revert = api("put", "/user/2/set-password/", {"password": "viewer123", "password2": "viewer123", "override_warning": True})
        log("FN9-USER-setpassword-revert", "Revertir password de testviewer a su valor original", r_revert.status_code in (200, 201), f"HTTP {r_revert.status_code} {short(r_revert)}")

    # Password débil sin override_warning -> UserDetailSetPassword.perform_update()
    # dispara validate_password() y rechaza (rama no cubierta por el caso normal)
    r_weak = api("put", "/user/2/set-password/", {"password": "abc", "password2": "abc"})
    log("FN9-USER-setpassword-weak", "Set-password con contraseña débil (debe rechazar)", r_weak.status_code in (400, 422), f"HTTP {r_weak.status_code} {short(r_weak)}")

    # Crear usuario nuevo y borrarlo -> UserDetail.perform_destroy() (limpieza de sesiones)
    r_new = api("post", "/user/", {"username": "cov_temp_user", "email": "cov_temp_user@example.com", "first_name": "Cov", "last_name": "Temp"})
    ok_new = r_new.status_code == 201
    log("FN9-USER-create", "Crear usuario nuevo", ok_new, f"HTTP {r_new.status_code} {short(r_new)}")
    if ok_new:
        new_pk = r_new.json().get("pk")
        r_del = api("delete", f"/user/{new_pk}/")
        log("FN9-USER-delete", "Borrar usuario nuevo (perform_destroy)", r_del.status_code == 204, f"HTTP {r_del.status_code}")

def fn9_coverage_extra():
    """check_user_role()/check_user_permission() solo ejecutan sus ramas reales
    para usuarios NO superuser (admin siempre corta temprano con is_superuser=True).
    Se usa 'testviewer' (sin permisos) para forzar el camino completo de
    verificacion de permisos, y se le asigna un Group con RuleSet para cubrir
    tambien la rama de coincidencia de rol."""

    # -- Petición autenticada como testviewer (no-superuser) contra un recurso protegido --
    r_viewer_noperm = requests.get(f"{API_URL}/part/", auth=VIEWER_AUTH)
    log("COV-PERM-viewer-noperm", "GET /part/ como testviewer sin grupo/permiso (check_user_permission completo)",
        r_viewer_noperm.status_code in (200, 403), f"HTTP {r_viewer_noperm.status_code}")

    # Repetir la misma llamada -> ejercita la rama de session-cache (result is not None)
    r_viewer_noperm2 = requests.get(f"{API_URL}/part/", auth=VIEWER_AUTH)
    log("COV-PERM-viewer-cache", "Repetir GET /part/ como testviewer (cache de sesión)",
        r_viewer_noperm2.status_code in (200, 403), f"HTTP {r_viewer_noperm2.status_code}")

    # -- Crear Group con RuleSet 'part' view=True, asignar a testviewer, y reintentar --
    r_group = api("post", "/user/group/", {"name": "COV Viewer Perm Group"})
    group_pk = r_group.json().get("pk") if r_group.status_code == 201 else None
    if group_pk:
        r_rulesets = api("get", "/user/ruleset/", params={"group": group_pk})
        rulesets = extract_list(r_rulesets.json())
        part_ruleset = next((rs for rs in rulesets if rs.get("name") == "part"), None)
        if part_ruleset:
            r_rsupdate = api("patch", f"/user/ruleset/{part_ruleset['pk']}/", {"can_view": True, "can_add": True, "can_change": True, "can_delete": False})
            log("COV-RULESET-update", "PATCH RuleSet 'part' can_view/add/change=True (update_group_roles sincrono)", r_rsupdate.status_code == 200, f"HTTP {r_rsupdate.status_code}")

        r_adduser = api("patch", "/user/2/", {"groups": [group_pk]})
        ok_adduser = r_adduser.status_code == 200
        log("COV-USER-addgroup", "PATCH testviewer.groups = [COV Viewer Perm Group]", ok_adduser, f"HTTP {r_adduser.status_code} {short(r_adduser)}")

        if ok_adduser:
            # Limpiar la cache de sesión: las llamadas anteriores (sin grupo)
            # cachearon result=False para esta combinación user+permission, y
            # check_user_permission() corta temprano si encuentra cache.
            clear_rate_limits()
            r_viewer_withperm = requests.get(f"{API_URL}/part/", auth=VIEWER_AUTH)
            log("COV-PERM-viewer-withperm", "GET /part/ como testviewer CON permiso de grupo (check_user_role match)",
                r_viewer_withperm.status_code == 200, f"HTTP {r_viewer_withperm.status_code}")

            r_viewer_denied = requests.delete(f"{API_URL}/part/1/", auth=VIEWER_AUTH)
            log("COV-PERM-viewer-delete-denied", "DELETE /part/1/ como testviewer sin can_delete (debe rechazar)",
                r_viewer_denied.status_code in (403, 405), f"HTTP {r_viewer_denied.status_code}")

        # Revertir: quitar a testviewer del grupo antes de borrarlo
        api("patch", "/user/2/", {"groups": []})
        api("delete", f"/user/group/{group_pk}/")

    # -- Usuario inactivo: check_user_permission()/check_user_role() 'not user.is_active' --
    r_inactive = api("patch", "/user/2/", {"is_active": False})
    if r_inactive.status_code == 200:
        r_viewer_inactive = requests.get(f"{API_URL}/part/", auth=VIEWER_AUTH)
        log("COV-PERM-inactive-user", "GET /part/ como testviewer inactivo (debe rechazar)",
            r_viewer_inactive.status_code in (401, 403), f"HTTP {r_viewer_inactive.status_code}")
        api("patch", "/user/2/", {"is_active": True})


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 62)
    print("  InvenTree — Usuarios / Autenticación")
    print("=" * 62)

    print("\n── Login / Logout ──────────────────────────────────────")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        tc_l01(browser)
        tc_l02(browser)
        tc_l03(browser)
        tc_l04(browser)
        tc_l05(browser)
        tc_l06(browser)
        browser.close()

    print("\n── FN9 — Autenticación: casos extendidos ─────────────")
    try:
        fn9_me(); fn9_tokens(); fn9_owner(); fn9_group_ruleset(); fn9_user_setpassword(); fn9_coverage_extra()
    except Exception as e:
        log("FN9-AUTH-extended", "Casos extendidos de Autenticación", False, str(e))

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
