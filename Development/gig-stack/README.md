# GIG

Browser prototype for the musician-facing GIG control surface.

## Naming

- GIG: the whole musician environment.
- Venue: the brain/host rig that runs the work, owns hardware input recognition, and connects to Cube, Racks, Akai EIE, outputs, and future live playback.
- Console: the deeper control model and software engine running on the Venue computer for editing, troubleshooting, and full control.
- GIG browser: the dead-simple musician phone, iPad, or browser remote.
- Session: the active project.
- Channel: a touchable mix fader controlled by Venue/Console.
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
- Let Venue own all recognized inputs and routing.
- Mix touch faders for Drums, Bass, Guitar, Vocal, Acoustic, Main, and Phones.
- Open Drums into Kick, Snare, Hat, Tom 1, Tom 2, OH L, OH R, and Room.
- Record all armed channels into takes.
- Apply simple musician-language Console controls such as mute, solo, EQ, compression, and level changes.
- Save the mix and move the mixed session to a set.

## Command examples

- `new session`
- `open previous session`
- `record all`
- `open drums`
- `make vocal louder`
- `mute guitar`
- `turn drums down`
- `compress bass`
- `brighten acoustic`
- `save this mix`
- `move this session to set`

## Next integration target

Connect this GIG browser API to the existing System Q Console Python model on Venue so browser commands update real `ConsoleEngine` and `ChannelState` fields instead of prototype state.
