# GIG Stack

Browser prototype for the musician-facing Stack interface inside GIG.

## Naming

- GIG: the whole musician environment.
- Stack: the musician phone, iPad, or browser interface.
- Venue: the brain/host rig that runs the work and connects to Cube, Racks, Akai EIE, outputs, and future live playback.
- Console: the deeper control model and software engine.
- Session: the active project.
- Track: an audio lane inside a session.
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

- Open a new session.
- Add tracks and assign Akai EIE inputs.
- Record, play, stop, mute, solo, arm, and adjust a selected track.
- Apply simple musician-language Console controls such as EQ, low cut, compression, and reverb.
- Save the Akai EIE setup.
- Move the mixed session to a set.

## Command examples

- `new session`
- `name this session Friday Demo`
- `create vocal track on input 1`
- `create guitar track on input 2`
- `record this track`
- `make this louder`
- `mute input 2`
- `compress this track`
- `make it brighter`
- `cut the low end`
- `add reverb`
- `save this setup`
- `move this session to set`

## Next integration target

Connect this Stack API to the existing System Q Console Python model so browser commands update real `ConsoleEngine` and `ChannelState` fields instead of prototype state.
