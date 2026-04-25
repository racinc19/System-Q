Recording Environment / System Q
================================

Started: 2026-03-27

This repo is the working package for System Q, a unified musician recording
environment. It combines public-facing pages, product strategy, software
prototypes, CAD concepts, BOM/spec pages, and partner/acquisition material.

Short version
-------------

System Q is a connected recording ecosystem for musicians:

- Personal Station: the musician endpoint for monitoring, playback, talkback,
  instrument/mic input, and session participation.
- Cube: the simpler modular I/O path into the system.
- Racks: the premium analog processing, routing, summing, monitoring, and
  conversion path.
- Software: the DSP, recall, UI, routing, and shared operating model.
- Controller: the tactile command surface for faders, focus, transport,
  automation, monitoring, and parameter control.
- Venue: the playback/live-output extension that carries the session into a
  performance environment.

The strategic value is continuity: musicians rehearse, record, refine, and play
back inside one operating model instead of stitching together disconnected
interfaces, mixers, plugins, monitor paths, and live tools.

Naming
------

- Platform / product line: System Q
- Public descriptor: Recording Environment
- Recording engine / workflow codename: GIG

Best first reads
----------------

Open these in order when returning to the project:

1. docs/ONE_PAGE_OVERVIEW.md
2. docs/PRODUCT_ARCHITECTURE.md
3. docs/SYSTEM_TECHNICAL_MODEL.md
4. docs/ACQUISITION_STRATEGY.md
5. docs/BUYER_FIT_MUSIC_TRIBE.md

Public and review pages
-----------------------

- index.html
  Main public landing page.

- studio/index.html
  Studio/System Q overview with links into specs and visuals.

- investors.html
  Strategic and acquisition-oriented framing.

- uli-review.html
  Owner/reviewer-facing page aimed at Uli Behringer / Music Tribe style review.

- html/
  Browser-open hardware specs, BOM pages, controller/cube/rack visual pages.

Software prototype
------------------

Primary prototype:

  py -3 software/system_q_console.py

Supporting prototype:

  py -3 software/pol_visualizer.py

Install software dependencies:

  py -3 -m pip install -r software/requirements.txt

Important software files:

- software/system_q_console.py
  Main System Q console prototype. Tkinter UI, 12-channel stem playback,
  channel strips, sends, pan, mute/solo/record arm, POL-style focus displays,
  mic-pre/harmonics/dynamics/EQ/tone processing concepts, and SpaceMouse-style
  control integration.

- software/pol_visualizer.py
  POL visualizer and audio/control experiment.

- software/jimmy_audio.py
  Smaller mic-pre prototype.

- software/generate_test_loops.py
  Generates simple loop audio under software/loops/.

- software/generate_band_stems.py
  Generates multi-channel band stems under software/band_stems/. The console
  creates these automatically on first launch if they are missing.

- software/check_system_q_nav.py
  Lightweight navigation behavior check for the console UI.

CAD and hardware concept
------------------------

Install CAD dependencies:

  py -3 -m pip install -r cad/requirements-cad.txt

Regenerate the left rack STEP model:

  py -3 cad/system_q_left_rack.py

Important CAD files:

- cad/system_q_left_rack.py
  CadQuery source for the left rack prototype shell.

- cad/system_q_left_rack.step
  Exported left rack enclosure.

- cad/system_q_left_rack_slideout.py
  Slide-out rear panel and side cable-routing concept.

- cad/generate_*.py
  Connector, tube, PSU, and supporting STEP part generators.

Partner / acquisition package
-----------------------------

- GRACE_PITCH/
  Draft materials and BOM scripts for a Grace Design-style partner discussion.

- docs/ACQUISITION_STRATEGY.md
  Buyer profile, proof threshold, and preferred package direction.

- docs/BUYER_FIT_MUSIC_TRIBE.md
  Why Music Tribe / Behringer is a plausible buyer profile.

- docs/OUTREACH_BRIEF.md
  First-contact framing for a buyer or strategic partner.

Deployment
----------

Cloudflare Pages:

  npx wrangler pages deploy . --project-name=<your-pages-project> --branch=main --commit-dirty=true

Source repo:

  https://github.com/racinc19/System-Q

GitHub Pages optional studio URL:

  https://racinc19.github.io/System-Q/studio/

See also:

- CLOUDFLARE_STUDIO.txt
- GITHUB_PAGES.txt
- RECALL.md

Repo hygiene notes
------------------

- takeoff_work/ contains construction/takeoff/change-order material. It may be
  valuable, but it is separate from the System Q product story and should be
  kept out of buyer-facing review unless intentionally included.

- If public pages reference images under Image/, confirm those files exist in
  the repo before deployment.

- Keep the front-door story simple for outside readers: System Q is a unified
  musician ecosystem, not just a mixer, interface, rack, app, or control
  surface.
