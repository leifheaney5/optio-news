# Phase 0 Safety Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Optio safe to invite users to by removing forgeable production sessions, making the web process WSGI-safe, isolating the digest job, decoupling import from database/feed work, and enforcing CSRF, rate limits, and stronger passwords.

**Architecture:** Keep the existing Flask application and database models intact for this slice. `main.py` will expose a side-effect-free `app`, with one-shot database initialization in `init_db.py`, a WSGI export in `wsgi.py`, and a separate one-shot digest entrypoint in `scheduled_job.py`. Flask-WTF will protect both browser forms and same-origin JSON mutations; Flask-Limiter will apply independent IP and normalized-email limits to authentication routes.

**Tech Stack:** Python 3.10-compatible Flask 3, Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Limiter, Gunicorn, zxcvbn, pytest, SQLite test database.

**Spec:** `C:/Users/lphea/.codex/attachments/5e9c312c-ff5c-40b2-bead-0367a597ee94/pasted-text-1.txt` (Optio Rebuild Plan, Phase 0).

## Global Constraints

- Production must refuse to boot when `SECRET_KEY` is absent; no deployed code path may use a known default secret.
- Session cookies must be secure, HTTP-only, and SameSite=Lax; local development may use a clearly development-only fallback.
- The web process must not run the digest scheduler or perform database creation/feed crawling during import.
- Authentication must be limited to 5 POST attempts per minute per IP and 20 POST attempts per hour per normalized email.
- All browser form posts and same-origin state-changing JSON requests must carry a valid CSRF token.
- New passwords must be at least 12 characters and reject zxcvbn dictionary matches ranked within the top 10,000.
- Do not deploy, access production data, set Railway variables, configure backups, or commit changes unless explicitly requested.
- Preserve the existing user-owned untracked `AGENTS.md` and `CLAUDE.md` files.

## Files and Responsibilities

- Modify `main.py`: security configuration, Flask-WTF/Flask-Limiter setup, password validation, auth decorators, and removal of import-time startup/scheduler behavior.
- Create `wsgi.py`: Gunicorn application export only.
- Create `scheduled_job.py`: one-shot digest runner that imports the app without starting web-process background work.
- Create `init_db.py`: explicit local/one-off database table creation command.
- Modify `requirements.txt`: add the runtime packages needed by the safety gate and Gunicorn entrypoint.
- Modify `Procfile`: make the web process invoke Gunicorn against `wsgi:application`.
- Modify `templates/login.html`, `templates/register.html`, `templates/index.html`, `templates/feeds.html`, and `templates/bookmarks.html`: render CSRF form/meta tokens and load the token transport script.
- Create `static/js/csrf.js`: inject the rendered token into same-origin POST/PUT/PATCH/DELETE requests made by existing frontend code.
- Modify `test_app.py`: make the suite exercise real CSRF protection, provide token-aware test helpers, and add regression coverage for production secret handling, import side effects, password policy, and rate limits.
- Modify `README.md`: document the explicit database initialization command, Gunicorn web command, separate digest command, and production secret requirement.

### Task 1: Security configuration and import-safe application lifecycle

**Files:**
- Modify: `main.py:1-65` and `main.py:1280-end`
- Create: `init_db.py`
- Test: `test_app.py` security/configuration section

**Interfaces:**
- Produces `resolve_secret_key(environ=None) -> str` for deterministic secret policy tests.
- Produces `initialize_database() -> None` for the explicit one-off initializer.
- `main.app` can be imported without `db.create_all()`, cache warming, feed crawling, or scheduler thread creation.

- [x] **Step 1: Add failing tests for secret policy and import safety.**

  Add tests that call `resolve_secret_key` with a production-like environment lacking `SECRET_KEY` and assert `RuntimeError`, call it with a local environment and assert the exact development-only fallback, and import `main` in a subprocess pointed at a nonexistent SQLite file and assert the database file is still absent after import.

- [x] **Step 2: Run the focused tests and verify the expected red failures.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'secret or import_side_effect' -q
  ```

  Expected: failures because the resolver does not exist and importing `main` currently creates/warms application state.

- [x] **Step 3: Implement the minimal lifecycle change.**

  Replace the literal fallback with `resolve_secret_key`, treating a non-empty `RAILWAY_ENVIRONMENT`, `FLASK_ENV=production`, or `APP_ENV=production` as production. Configure `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `REMEMBER_COOKIE_SECURE=True`, `REMEMBER_COOKIE_HTTPONLY=True`, and `REMEMBER_COOKIE_SAMESITE='Lax'`.

  Remove the module-level call to `_startup()`, remove the cache-warming thread from `_startup`, remove the in-process scheduler setup/thread, and leave `if __name__ == '__main__'` responsible only for starting Flask locally. Keep `fetch_articles`, its lock, and existing cache behavior in this slice so the Phase 1 persistence work remains isolated.

  Add `initialize_database()` in `main.py` and make `init_db.py` import `app` and that function, execute it under the script guard, and print a short success message. The initializer is the only place in this slice that calls `db.create_all()`.

- [x] **Step 4: Run the focused tests and the syntax check.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'secret or import_side_effect' -q
  python -m py_compile main.py init_db.py
  ```

  Expected: focused tests pass and both files compile.

### Task 2: WSGI web process and isolated digest command

**Files:**
- Create: `wsgi.py`
- Create: `scheduled_job.py`
- Modify: `requirements.txt`
- Modify: `Procfile`
- Test: `test_app.py` process-entrypoint section

**Interfaces:**
- `wsgi.application` is the same Flask app object as `main.app` and importing it starts no scheduler.
- Running `scheduled_job.py` executes one digest job inside an application context and exits with the job result; it does not call `app.run`.

- [x] **Step 1: Add failing entrypoint tests.**

  Add tests that import `wsgi` and assert `wsgi.application is app`, inspect the source/behavior to ensure no scheduler thread is started on import, and assert `scheduled_job.py` exposes a callable `run_job` that invokes `job` under `app.app_context`.

- [x] **Step 2: Run the focused entrypoint tests and verify red.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'wsgi or scheduled_job' -q
  ```

  Expected: failures because the entrypoint files and callable do not exist.

- [x] **Step 3: Implement the entrypoints and dependency declarations.**

  Add `wsgi.py` with `from main import app` and `application = app`. Add `scheduled_job.py` with `run_job()` that enters `app.app_context()` and calls `job()`, then invoke `run_job()` under the script guard. Add pinned-minimum declarations for `gunicorn`, `Flask-Limiter`, `Flask-WTF`, and `zxcvbn` to `requirements.txt`. Change `Procfile` to `web: gunicorn -w 2 -k gthread --threads 4 --timeout 60 -b 0.0.0.0:$PORT wsgi:application`.

- [x] **Step 4: Run entrypoint import and syntax checks.**

  Run:

  ```powershell
  python -m py_compile wsgi.py scheduled_job.py
  python -c "import wsgi; assert wsgi.application.name == 'main'"
  ```

  Expected: both commands exit successfully without fetching feeds.

### Task 3: CSRF protection for forms and frontend API mutations

**Files:**
- Modify: `main.py` Flask extension setup
- Modify: `templates/login.html`, `templates/register.html`, `templates/index.html`, `templates/feeds.html`, `templates/bookmarks.html`
- Create: `static/js/csrf.js`
- Test: `test_app.py` auth/security section

**Interfaces:**
- Forms render `{{ csrf_token() }}` as hidden `csrf_token` inputs.
- Authenticated HTML pages render a `meta[name="csrf-token"]` token.
- `csrf.js` transparently adds `X-CSRFToken` to same-origin mutating requests while preserving existing request bodies and headers.

- [x] **Step 1: Add failing CSRF tests.**

  Add tests that POST `/login` and `/register` without a token and assert HTTP 400, assert the rendered forms contain hidden CSRF fields, assert authenticated pages contain the meta token and script, and assert a token-bearing JSON bookmark create succeeds.

- [x] **Step 2: Run the focused CSRF tests and verify red.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'csrf' -q
  ```

  Expected: failures because CSRF is not registered and templates have no tokens.

- [x] **Step 3: Implement global CSRF and browser transport.**

  Register `CSRFProtect(app)` after app creation. Add hidden fields to login/register forms and a token meta tag to each authenticated page. Load `csrf.js` before the existing page scripts. In `csrf.js`, wrap `window.fetch` and use `Headers` to set `X-CSRFToken` only for same-origin mutating requests; leave GET and cross-origin requests unchanged.

- [x] **Step 4: Update tests and run the focused green cycle.**

  Add test helpers that fetch `/login`, extract the hidden token, and use it for form posts or `X-CSRFToken` for JSON requests. Update existing mutation tests to use those helpers. Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'csrf or Register or Login or Bookmarks or Feeds or Account' -q
  ```

  Expected: all selected tests pass, including legitimate form and JSON mutations.

### Task 4: Authentication rate limits and password policy

**Files:**
- Modify: `main.py` auth setup and `login`/`register` routes
- Modify: `templates/register.html`
- Test: `test_app.py` auth/security section

**Interfaces:**
- `rate_limit_email_key() -> str` returns `email:<normalized-email>` for supplied auth email input and an IP fallback when no email is available.
- `is_common_password(password: str) -> bool` returns true when a full-password zxcvbn dictionary match has rank `<= 10000`.
- Registration rejects passwords shorter than 12 characters or matching the top-10,000 dictionary, with a user-facing flash message and no account creation.

- [x] **Step 1: Add failing tests for the password boundary and limits.**

  Add tests for an 11-character password rejection, a 12-character top-ranked password rejection, a strong 12-character password acceptance, six invalid login POSTs from one IP returning 429 on the sixth when limits are enabled, and 21 attempts for one normalized email across distinct IPs returning 429 on the 21st.

- [x] **Step 2: Run the focused tests and verify red.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'password_policy or rate_limit' -q
  ```

  Expected: failures because the current minimum is eight characters and authentication has no limiter.

- [x] **Step 3: Implement the smallest shared enforcement boundary.**

  Register `Limiter(key_func=get_remote_address, storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'), default_limits=[])`. Apply `5 per minute` with the default IP key and `20 per hour` with `rate_limit_email_key` to POST requests for both auth routes. Use `zxcvbn` dictionary match ranks, requiring the match to span the entire password, for the top-10,000 check. Update browser `minlength` and placeholder text to 12 characters.

- [x] **Step 4: Run focused tests and the full project suite.**

  Run:

  ```powershell
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -k 'password_policy or rate_limit' -q
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -q
  ```

  Expected: focused tests and the full suite pass.

### Task 5: Documentation and final verification

**Files:**
- Modify: `README.md`
- Test: repository working tree and all applicable checks

- [x] **Step 1: Update documented commands.**

  Replace the production-facing `python main.py` guidance with `python init_db.py` for first-time local schema creation, `python main.py` for local development, and the Gunicorn command used by `Procfile` for deployment. Document that production requires an explicitly generated `SECRET_KEY`, that the digest is run separately with `python scheduled_job.py`, and that no `.env` file should be committed.

- [x] **Step 2: Run the canonical checks.**

  Run:

  ```powershell
  python -m py_compile main.py init_db.py wsgi.py scheduled_job.py
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest test_app.py -q
  git diff --check
  git status --short --branch
  ```

  Expected: compilation succeeds, all project tests pass, `git diff --check` emits no errors, and only the planned files plus the pre-existing untracked instruction files appear in status.

- [x] **Step 3: Review the final diff.**

  Confirm there is no known production secret fallback, no import-time `db.create_all`, no scheduler thread in `main.py`, no missing CSRF token on an existing mutation page, no weakened existing authorization, and no unrelated reformatting or user-file deletion.

## Plan Self-Review

- Phase 0 secret handling is covered by Task 1 and tested at the resolver and import boundary.
- Gunicorn and scheduler isolation are covered by Task 2; Railway secret assignment/backups remain an explicit manual deployment prerequisite outside this patch.
- CSRF coverage includes HTML forms and the existing same-origin JSON mutation surface in Task 3.
- The authentication limits and password floor/blocklist are covered by Task 4.
- Phase 1 persistence, migrations, per-user feed subscriptions, article storage, ingestion, clustering, unread state, onboarding, personalization, search, alerts, PWA work, Sentry, and Railway operations are intentionally separate sub-projects and are not silently folded into this slice.
- No placeholders or unresolved implementation choices remain in the tasks above.
