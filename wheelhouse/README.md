# Wheelhouse

This folder is curated for the current app's offline install target:

- Windows
- CPython 3.10
- `requirements-offline.txt`

Keep only this dependency closure:

- `bosdyn-orbit==5.1.1`
- `Deprecated==1.2.18`
- `wrapt==1.17.3` Windows wheel
- `Flask==3.1.3`
- `blinker==1.9.0`
- `click==8.3.1`
- `colorama==0.4.6`
- `itsdangerous==2.2.0`
- `jinja2==3.1.6`
- `markupsafe==3.0.3` Windows wheel
- `werkzeug==3.1.6`
- `requests==2.32.5`
- `charset-normalizer==3.4.5` Windows wheel
- `idna==3.11`
- `urllib3==2.6.3`
- `certifi==2026.2.25`
- `waitress==3.0.2`

Do not keep stale wheels for:

- macOS-only builds
- `Deprecated==1.3.1`
- `wrapt==2.1.2`
- unused Spot SDK packages such as `bosdyn-client` or `bosdyn-core`
