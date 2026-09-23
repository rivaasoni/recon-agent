# web/ : the public demo site

A read-only demo of the agent's results. Plain HTML, CSS and JavaScript. No framework,
no build step, no backend, and it never calls an AI model, so the live site costs
nothing to run and needs no API key.

| File | What it is |
|---|---|
| `index.html` | The page: overview, the 16 exceptions, how well it did |
| `styles.css` | All the styling. Colours are variables, with a dark mode set |
| `app.js` | Loads the JSON in `data/` and puts it on the page |
| `data/` | The results. These files are committed on purpose, because Vercel serves the repo |
| `vercel.json` | Cache and security headers |

## Updating the data after a new run

```bash
python -m recon.pipeline.refresh_analytics   # rebuild the database and metrics
python -m recon.pipeline.build_web_demo      # rewrite web/data/
git add web/data && git commit -m "chore: refresh demo data" && git push
```

Vercel redeploys on every push.

## Looking at it locally

Browsers block JavaScript from loading files when you open a page directly, so
double-clicking `index.html` shows an empty page. Serve it instead:

```bash
cd web
python -m http.server 8000     # then open http://localhost:8000
```

## Notes on vercel.json

JSON can't have comments, so the reasoning is here:

- `cleanUrls` serves `index.html` at the root URL.
- The cache header on `/data/*` lets browsers keep the files for 5 minutes and Vercel's
  servers for an hour. The data only changes when I push.
- `X-Content-Type-Options: nosniff` stops browsers guessing what a file is.
- `Referrer-Policy` limits what gets passed on when someone clicks a link off the site.

There's no login and nothing is stored about visitors. Those last two headers are just
good practice.
