# Recall (Recording Environment)

## What this repo is
A Cloudflare Pages static site deployed from the GitHub repo `racinc19/System-Q`.

- Canonical live site: https://recording-environment.pages.dev/
- Repo root contains the published site (`index.html`, `uli-review.html`, assets folders).

## Primary files to edit
- `index.html`
  - Main landing page.
  - Software section uses a 2-column “split” media layout (image left, text right).
- `uli-review.html`
  - Owner review page.

## Images / assets
Images must exist as files inside this repo to appear on the deployed site.

- Landing page renders live in: `Image/`
  - `Image/Recording Environment.png` (hero / ecosystem)
  - `Image/Left.png`, `Image/Right.png`
  - `Image/cube.png`
  - `Image/Console.png` (Console render)
  - `Image/Pedal.png`
  - `Image/Venue.png`
  - `Image/download.png` (vertical CH02 strip screenshot used in Software section)

Other visuals exist under: `visuals/` (misc UI renders / experiments).

## Software section: intended content
The Software section describes the channel strip as console components:

- Mic pre
- Harmonics: unique 5-band harmonic processor (H1–H5)
- Compressor
- EQ
- Effects processor: transient designer + saturation/exciter (treated as one stage)

POL (polar) editing concept:
- The mic pre and dynamics visually “close in” on a polar graph.
- Ring radius maps frequency:
  - bigger ring = lower frequency
  - smaller ring = higher frequency

## Deployment workflow (Cloudflare Pages)
Cloudflare redeploys automatically when you push to GitHub.

Typical flow:

```bash
git status
# edit files
git add -A
git commit -m "Describe change"
git push
```

To confirm what changed:

```bash
git log --oneline -n 20
git show <hash>
```

To verify deployments:
- Cloudflare Dashboard → Workers & Pages → Pages → `recording-environment` → Deployments

## Gotchas
- Chat-uploaded screenshots are NOT automatically part of the repo.
  - To use an image on the live site, it must be copied into the repo (e.g. `Image/`) and committed.
- Do NOT edit/save `.git/index.lock`.
  - It’s a transient lock file used by Git.

## Optional cleanup
- Consider renaming `Image/download.png` to something stable like `Image/strip-ch02.png` and updating references.
