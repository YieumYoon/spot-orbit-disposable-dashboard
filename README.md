# Spot Orbit Disposable Dashboard

Single-page Flask dashboard for showing current Spot activity through Orbit on an internal network.

## Local Development With `uv`

```bash
UV_CACHE_DIR=.uv-cache uv python install 3.10
UV_CACHE_DIR=.uv-cache uv venv --python 3.10
UV_CACHE_DIR=.uv-cache uv sync
cp .env.example .env
UV_CACHE_DIR=.uv-cache uv run python run.py
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

The app loads `.env` from the repo root automatically. Real environment variables still win if both are set.

## `.env` Support

Use [`.env.example`](/Users/junsu/Documents/github/spot-orbit-disposable-dashboard/.env.example) as the template for a local `.env` file.

Example fixture preview:

```env
ORBIT_USE_FIXTURES=true
TIMEZONE=America/Indiana/Indianapolis
DASHBOARD_BIND_HOST=127.0.0.1
DASHBOARD_PORT=8080
```

Example live server config:

```env
ORBIT_USE_FIXTURES=false
ORBIT_HOST=your-orbit-host-or-ip
ORBIT_API_TOKEN=your-orbit-api-token
ORBIT_VERIFY_TLS=true
TIMEZONE=America/Indiana/Indianapolis
DASHBOARD_BIND_HOST=0.0.0.0
DASHBOARD_PORT=8080
```

## Key Variables

- `ORBIT_HOST`
- `ORBIT_API_TOKEN`
- `ORBIT_VERIFY_TLS`
- `ORBIT_CERT_PATH`
- `TIMEZONE`
- `DASHBOARD_REFRESH_SECONDS`
- `DASHBOARD_CACHE_TTL_SECONDS`
- `DASHBOARD_BIND_HOST`
- `DASHBOARD_PORT`
- `ORBIT_USE_FIXTURES`
- `ORBIT_FIXTURE_DIR`

## Offline Windows Deployment

1. Copy the app source tree, `requirements-offline.txt`, and `wheelhouse/` to the Orbit-connected Windows machine.
2. Create a venv and install from local files only:

```powershell
py -3.10 -m venv .venv
.venv\Scripts\activate
py -m pip install --no-index --find-links=wheelhouse -r requirements-offline.txt
```

`wheelhouse/` is already pruned for the exact Windows CPython 3.10 dependency set this app needs. Replace the server copy rather than merging with an older wheelhouse.

`tzdata` is included in the offline dependency set so Python `zoneinfo` works on Windows hosts that do not ship the IANA timezone database.

3. Create `.env` on the Windows machine from `.env.example` and fill in the live Orbit values:

```powershell
Copy-Item .env.example .env
```

4. Start the app with `waitress-serve --host=0.0.0.0 --port=8080 run:app`.

The shareable internal site URL is the internal hostname or IP of that Windows host plus the configured port.
