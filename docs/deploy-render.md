# Deploying the demo to Render

One Render **web service** runs everything: the built UI at `/` and the orchestrator API at `/api`. The service is defined by `Dockerfile` and `render.yaml` at the repo root, and served by `orchestration/web.py`.

## First deploy (about 10 minutes, once)

1. Sign in at <https://dashboard.render.com> with GitHub, and give Render access to this repository.
2. Go to **New → Blueprint** and pick this repository. Render reads `render.yaml`.
3. Pick the branch to deploy (`main`).
4. Render asks for `GEMINI_API_KEY` and `GROQ_API_KEY`. Both are optional; leave them blank to run every agent in replay/rules mode. **Paste keys only here, never in a file.**
5. Click **Apply**. The first build takes about 5 minutes. The site is then live at `https://cube-pod05.onrender.com` (or the name Render gives it).

After that, every push to the branch redeploys on its own.

## What to expect

- **The data is ready at start-up.** The image runs every sample case and the Pod's own cases while it builds (replay mode, no keys used), so the dashboard is full as soon as the service starts.
- **Changes on the site are temporary.** Overrides and new workflow runs are saved to the container's disk, and Render resets that disk on every deploy and restart. Each deploy starts again from the same clean state.
- **The free plan sleeps.** After 15 minutes without visitors, the first request takes about a minute while the service wakes up. Open the site a minute before you present it.
- **There is no login.** Anyone with the link can record an override or start a workflow, and the next deploy wipes it. Do not put real customer data in it.

## Check it

- `https://<your-service>.onrender.com/api/health` should show `"status": "ok"` and the five agents.
- `https://<your-service>.onrender.com/overview` should show "Live API Connected" and the workflows.

## Run the same image locally (optional)

```bash
docker build -t cube-pod05 .
docker run -p 8100:8100 cube-pod05        # open http://localhost:8100/overview
```

Without Docker: `cd ui && npm run build && cd ..`, then `python -m uvicorn orchestration.web:app --port 8100`.

## If the deploy fails

| Symptom in the Render log | Fix |
|---|---|
| `npm ci` fails | `ui/package-lock.json` does not match `package.json`: run `npm install` in `ui/` and commit the lock file. |
| `pip install` fails on one package | Pin the version in `requirements.txt` that CI (Python 3.12) installs. |
| Health check times out | Open the service **Logs**. The server must listen on `$PORT`, which the `CMD` in `Dockerfile` already does. |
| Page loads but says the API is offline | Open `/api/health` directly. If it gives a 500, the log names the agent that failed to load. |
