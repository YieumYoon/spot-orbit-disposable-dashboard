# Spot Orbit Disposable Dashboard

Single-page Flask dashboard for showing current Spot activity through Orbit on an internal network.

## Local Development With `uv`

```bash
UV_CACHE_DIR=.uv-cache uv python install 3.10
UV_CACHE_DIR=.uv-cache uv venv --python 3.10
UV_CACHE_DIR=.uv-cache uv sync
ORBIT_USE_FIXTURES=true UV_CACHE_DIR=.uv-cache uv run python run.py
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

## Key Environment Variables

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

3. Set the Orbit environment variables and disable fixtures:

```powershell
$env:ORBIT_USE_FIXTURES="false"
$env:ORBIT_HOST="your-orbit-host"
$env:ORBIT_API_TOKEN="your-token"
```

4. Start the app with `waitress-serve --host=0.0.0.0 --port=8080 run:app`.

The shareable internal site URL is the internal hostname or IP of that Windows host plus the configured port.
