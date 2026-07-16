# Deploy Geekonomy HRMS on Container Station (Nginx → Gunicorn → Django)

This guide walks you through deploying **Geekonomy HRMS** on QNAP Container Station with **Nginx** (reverse proxy + static files), **Gunicorn** (WSGI), and **Django** for better speed than runserver.


---

## What you get

| Layer    | Role |
|----------|------|
| **Nginx**   | Reverse proxy, serves `/static` and `/media`, forwards requests to Gunicorn |
| **Gunicorn**| WSGI server running Django (inside `geekonomy-hrms` container) |
| **Django**  | Your app (same codebase) |
| **PostgreSQL** | Database (`geekonomy-database`) |

- **Port:** You access the app on **port 8080** (Nginx).  
- **URL:** `http://<NAS-IP>:8080` (e.g. `http://10.0.0.178:8080`).

---

## Prerequisites

1. **Container Station** installed on your QNAP NAS (you already have it).
2. **Project files** on the NAS (e.g. under `/share/...` or where you keep Geekonomy HRMS).
3. **Docker** available (Container Station provides it).

---

## Step 1: Copy project to the NAS (if not already there)

Copy the whole Geekonomy HRMS project (this repo) to a folder on the NAS, for example:

- `/share/CE_CACHEDEV1_DATA/Container/geekonomy-hrms/`

Ensure these files/folders exist there:

- `Dockerfile`
- `entrypoint.sh`
- `docker-compose.geekonomy.yaml`
- `nginx/nginx.conf`
- `manage.py`, `horilla/`, app code, etc.

---

## Step 2: Create the app in Container Station

1. Open **Container Station** (e.g. `http://10.0.0.178:8080`).
2. Go to **Applications**.
3. Click **Create** (or **+ Create**).
4. Choose **Create Application** (or **Compose** if you use Compose).

### Option A: Using Docker Compose (recommended)

1. In Container Station, go to **Containers** or the Compose area.
2. Use **Create** → **Create from docker-compose** (or similar).
3. Set **Path** (or “Compose file directory”) to the project folder, e.g.  
   `/share/CE_CACHEDEV1_DATA/Container/geekonomy-hrms/`
4. Set **Compose file** to: `docker-compose.geekonomy.yaml`
5. Application name: e.g. **geekonomy** or **Geekonomy HRMS**.
6. Click **Create** / **Deploy**.

### Option B: Creating containers manually

If Container Station doesn’t support Compose in the UI:

1. **SSH** into the NAS and `cd` to the project folder:
   ```bash
   cd /share/CE_CACHEDEV1_DATA/Container/geekonomy-hrms/
   ```
2. Run:
   ```bash
   docker compose -f docker-compose.geekonomy.yaml up -d
   ```
3. Check:
   ```bash
   docker compose -f docker-compose.geekonomy.yaml ps
   ```

---

## Step 3: Wait for first run

1. **geekonomy-database** starts first and becomes healthy.
2. **geekonomy-hrms** (Django + Gunicorn) starts, runs migrations and `collectstatic`, then listens on port 8000 (internal).
3. **geekonomy-nginx** starts and listens on **port 8080** on the host.

First startup can take 1–2 minutes (migrations, static collection).

---

## Step 4: Open the app

- In the browser: **`http://<NAS-IP>:8080`**  
  Example: **`http://10.0.0.178:8080`**

If you see the login page, Nginx → Gunicorn → Django is working.

---

## Step 5: Configure Django (optional)

- **ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS:** Already set in `docker-compose.geekonomy.yaml` for `10.0.0.178` and `localhost`. If you use another IP or domain, add it there (and restart the stack).
- **SECRET_KEY / DB password:** For production, change them in the compose file (or use env files) and recreate the app.

---

## Step 6: Restart / update later

- **Restart:** In Container Station, restart the **geekonomy** application (or the three containers).
- **Update code:** Replace the project folder on the NAS, then rebuild and restart:
  ```bash
  cd /path/to/geekonomy-hrms
  docker compose -f docker-compose.geekonomy.yaml build --no-cache geekonomy-app
  docker compose -f docker-compose.geekonomy.yaml up -d
  ```

---

## Ports summary

| Service           | Internal port | Host port | Use |
|-------------------|---------------|-----------|-----|
| geekonomy-nginx   | 80            | **8080**  | Browser → `http://<NAS>:8080` |
| geekonomy-hrms    | 8000          | (none)    | Only Nginx talks to it |
| geekonomy-database| 5432          | 5433      | Optional direct DB access |

If **8080** is already in use (e.g. Container Station UI), change the Nginx port in `docker-compose.geekonomy.yaml`:

```yaml
geekonomy-nginx:
  ports:
    - "8880:80"   # use http://<NAS>:8880
```

---

## Troubleshooting

| Issue | What to do |
|-------|-------------|
| 502 Bad Gateway | Gunicorn not ready yet. Wait 1–2 min and refresh. Check logs: `docker logs geekonomy-hrms`. |
| Blank / 404 page | Check Nginx and app logs: `docker logs geekonomy-nginx`, `docker logs geekonomy-hrms`. |
| Static files missing (no CSS) | App runs `collectstatic` on start. Ensure **geekonomy-static** volume is mounted on Nginx (as in the compose). Restart **geekonomy-hrms** once so it repopulates the volume. |
| Database connection error | Ensure **geekonomy-db** is healthy. Check `docker logs geekonomy-database`. |

---

## Flow recap

1. User opens **http://10.0.0.178:8080**.
2. **Nginx** receives the request.
3. **/static/** and **/media/** → Nginx serves from volumes (fast).
4. All other paths → Nginx proxies to **Gunicorn** (geekonomy-hrms:8000).
5. **Gunicorn** runs **Django**; Django uses **PostgreSQL** (geekonomy-db).

This gives you a **Nginx → Gunicorn → Django** deployment on Container Station with a single entry point on port 8080.

