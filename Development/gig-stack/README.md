# GIG

Browser prototype for the musician-facing GIG control surface.

## Naming

- GIG: the whole musician environment.
- Venue: the brain/host rig that runs the work, owns hardware input recognition, and connects to Cube, Racks, Akai EIE, outputs, and future live playback.
- Console: the deeper control model and software engine running on the Venue computer for editing, troubleshooting, and full control.
- GIG browser: the dead-simple musician phone, iPad, or browser remote.
- Personal Console: each musician's deeper Console view for their own monitor mix only.
- Venue Console: an assigned engineering/house control entry point, separate from musician faders.
- Console Assist: the listening intelligence that identifies source tone and applies source-aware EQ, compression, gate, and level moves.
- Session: the active project.
- Channel: a touchable personal mix fader controlled by the musician.
- Take: a recorded pass inside a session.
- Set: a mixed/ready session moved into playlist/live-use form.

## Run locally

From this folder:

```powershell
npm start
```

Then open:

```text
http://localhost:4180
```

## Current prototype flow

- Open a new or previous session.
- Let Venue own all recognized inputs, house routing, and recording.
- Show only the musician's personal mix faders for sources such as Drums, Bass, Guitar, Vocal, and Acoustic.
- Keep house/main controls out of the musician fader surface.
- Open Drums into Kick, Snare, Hat, Tom 1, Tom 2, OH L, OH R, and Room.
- Record all armed channels into takes.
- Adjust personal mix volume directly on faders or by voice.
- Open Personal Console for deeper manual edits on that musician's mix.
- Open assigned Venue Console for house/engineering work.
- Let Console Assist listen, identify source targets, and shape tone without exposing those controls on the simple fader screen.
- Save the personal mix and move the mixed session to a set.

## Command examples

- `new session`
- `open previous session`
- `record all`
- `open drums`
- `make vocal louder`
- `turn drums down`
- `open my console`
- `open venue console`
- `shape snare target`
- `console assist listen`
- `save this mix`
- `move this session to set`

## Next integration target

Connect this GIG browser API to the existing System Q Console Python model on Venue so browser commands update real `ConsoleEngine` and `ChannelState` fields instead of prototype state.
