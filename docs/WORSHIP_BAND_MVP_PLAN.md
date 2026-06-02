# Worship Band MVP Plan

## Product thesis

Build the first version as a rehearsal and live-rig assistant for worship bands.

The promise is simple:

> Plug the band into stage boxes, open synced charts on iPads, put in in-ears, and let one central brain handle monitoring, recording, playback, cues, and simple mix changes.

This is the first practical expression of the larger Recording Environment architecture:

- Personal Station becomes the musician stage box.
- Software becomes the Mac/iPad session brain.
- Controller becomes voice plus minimal fallback controls.
- Venue becomes the live output path.

## First customer

The first target customer should be a worship team with:

- Volunteer musicians
- In-ear monitor needs
- Shared charts or lyrics
- Repeat weekly setlists
- Limited technical staff
- A need to record and review rehearsals quickly

This customer is better than a generic band because the workflow is repeatable and the pain is obvious.

## MVP scope

The MVP should prove one complete rehearsal flow before custom hardware.

### Included

- Mac brain running the session
- iPad chart and setlist view
- Shared song position and section sync
- Per-musician monitor controls
- Voice commands for common actions
- Multitrack record and playback
- Basic talkback state
- Saved mixes per song
- Simple musician roles: leader, drummer, vocal, guitar, keys, bass

### Excluded for version one

- Custom network stage boxes
- Fully automatic AI mixing
- Wireless live audio
- Deep DAW editing
- Full licensing integrations
- FOH replacement in uncontrolled venues

## Prototype hardware

Use off-the-shelf gear first:

- One Mac as the brain
- Logic Pro or MainStage for audio/session behavior
- Multichannel audio interface
- Headphone distribution or existing personal monitor system
- iPads on local Wi-Fi for charts and controls
- Wired network where possible for reliability

The goal is to prove the workflow before committing to a custom Personal Station.

## Software architecture

```text
iPad clients
  charts, setlist, personal mix, fallback controls
        |
        | local network
        v
Mac brain app
  session state, voice commands, routing commands, record/playback control
        |
        | MIDI / control surface / automation bridge
        v
Logic Pro / MainStage
  audio engine, instruments, effects, transport, recording
        |
        v
Audio interface
  inputs, outputs, in-ear feeds, mains
```

## Core demo flow

1. Create a Sunday setlist.
2. Assign each musician a role and input.
3. Upload a chart or PDF for each song.
4. Everyone opens the iPad view.
5. The leader loads the first song.
6. MainStage or Logic loads the matching state.
7. The drummer receives click and cues.
8. The band rehearses.
9. The leader says, "record this."
10. The system records a multitrack pass.
11. The leader says, "play back from chorus."
12. Audio playback and chart position jump to the chorus.
13. A musician says, "more vocal in my ears."
14. The system raises that send safely and confirms the change.
15. The mix is saved with the song.

## Voice command model

Voice should be treated as an intent layer, not as magic.

Every command should map to a safe, reversible action.

### Transport

- Record this
- Stop
- Play it back
- Play from chorus
- Go to the bridge
- Next song
- Load the set

### Monitor mix

- More me
- Less click
- More lead vocal in my ears
- Turn guitar down in everyone else's ears
- Give the drummer more bass

### Live/session

- Save this mix
- Recall rehearsal mix
- Mute talkback
- Talk to band
- Mark this section

## Safety rules

- Never make large level jumps at once.
- Keep per-command gain moves small, such as 1 to 2 dB.
- Require confirmation for changes to mains or speaker outputs.
- Always support undo.
- Preserve local emergency volume control for in-ears.
- Audio must continue if an iPad disconnects.
- Voice must never be the only control path.

## First build milestone

Build a local web prototype:

- Mac-hosted session server
- iPad-sized performer UI
- Setlist and chart display
- Section markers
- Synced leader-follow mode
- Per-musician mix controls
- Simulated voice command input
- Simulated Logic/MainStage command log

This can be built and tested before touching real audio control.

## Second build milestone

Connect the Mac app to a real audio/session environment:

- MIDI transport control
- MainStage patch/song selection
- Logic record/play/stop where reliable
- Virtual mixer state
- Basic audio interface output assignment

The success condition is a real rehearsal where the system controls charts, records, plays back, and adjusts monitor sends.

## Hardware milestone

Only after the workflow proves useful, design the Personal Station.

Baseline box:

- Ethernet
- Power over Ethernet target if feasible
- One mic/instrument input
- Stereo in-ear output
- Local volume knob
- Mute/talkback button
- Status lights
- Rugged enclosure

The box should be intentionally minimal. The central brain owns the session logic.

## Validation test

The first real test should be one worship rehearsal, not a polished launch.

Success means:

- Setup is faster than their normal rig.
- Musicians can follow the set without chart confusion.
- In-ear changes happen without a technical person stopping rehearsal.
- Recording and playback are useful immediately.
- The leader wants to use it again the next week.

## Immediate next step

Create the first clickable prototype:

- `Brain` view for the leader/operator
- `Performer` iPad view
- Demo setlist with song sections
- Synced page/section navigation
- Mix controls per musician
- Voice command text input that executes the same actions voice will later trigger

