# web/ — the public demo site

A static, read-only demo of the reconciliation agent's results. Plain HTML, CSS
and JavaScript: no framework, no build step, no backend, and **no AI model call**,
so the published site costs nothing to run and needs no API key.

| File | What it is |
|---|---|
| `index.html` | Page structure: overview, the 16 exceptions, evaluation |
| `styles.css` | All styling; colours are CSS variables with a dark-mode set |
| `app.js` | Fetches the JSON in `data/` and renders it |
| `data/` | Pre-computed results — **committed on purpose** (Vercel serves the repo) |
| `vercel.json` | Cache headers for `data/`, plus two basic security headers |

## Regenerating the data

After a new agent run:

```bash
python -m recon.pipeline.refresh_analytics   # rebuild the warehouse + metrics
python -m recon.pipeline.build_web_demo      # rewrite web/data/
git add web/data && git commit -m "chore: refresh demo data" && git push
```

Vercel redeploys on push.

## Previewing locally

Browsers block `fetch()` on `file://` pages, so opening `index.html` directly
shows an empty page. Serve it instead:

```bash
cd web
python -m http.server 8000     # then open http://localhost:8000
```

## Notes on `vercel.json`

JSON has no comments, so the reasoning lives here:

- **`cleanUrls`** serves `/index.html` at `/`.
- **`Cache-Control` on `/data/*`** — the data only changes when the repo is
  pushed, so browsers cache it for 5 minutes and Vercel's CDN for an hour.
- **`X-Content-Type-Options: nosniff`** stops browsers guessing a file's type.
- **`Referrer-Policy`** limits what this site leaks to links it points at.

The site has no login and stores nothing about visitors; these headers are
cheap good practice rather than a response to a specific risk.
