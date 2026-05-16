# System Q: Tape Cylinder Technical Specification

This document defines the physical and magnetic parameters for the first prototype thesis of the System Q Tape Cylinder.

The Tape Cylinder is intended to be evaluated as a premium analog coloration, capture, repro, and print path inside the System Q rack architecture.

It can serve three roles:

- Input magnetic buffer: historic input card -> Tape Cylinder -> A/D -> DAW
- Output magnetic buffer: DAW / stems -> historic output card -> Tape Cylinder -> print / monitor / Venue
- Double-tape path: input card -> Tape Cylinder -> DAW -> output card -> Tape Cylinder

The product goal is not only "tape sound." The product goal is a clip-resistant magnetic buffer that lets hot analog-card output become compression, harmonic density, and saturation before it reaches a hard digital ceiling.

## 1. Drum Dimensions and Physics

To target the sonic behavior associated with a 2-inch Studer-style machine, the first prototype uses a large-roll cylinder form factor.

| Parameter | Specification | Rationale |
| --- | --- | --- |
| Material | Aircraft-grade 6061 aluminum | High stability and non-magnetic structure. |
| Width | 2.0 inches | Matches the 2-inch tape-machine reference width. |
| Diameter | 5.0 inches | Provides a 15.7-inch circumference. |
| Speed | 114.6 RPM | Required rotational speed for 30 inches per second at 5-inch diameter. |
| Motor | High-torque brushless DC | Slaved to DAW sample clock through System Q logic. |

### Speed calculation

```text
circumference = pi * diameter
circumference = 3.14159 * 5.0 in = 15.708 in

target tape speed = 30 in/sec = 1800 in/min
required RPM = 1800 / 15.708 = 114.6 RPM
```

## 2. The Thick-Wad Magnetic Coating

Unlike thin ribbon tape, the cylinder concept uses a permanent, multi-layer magnetic coating.

| Parameter | Prototype Thesis |
| --- | --- |
| Composition | Gamma ferric oxide (`Fe2O3`) with high-density cobalt doping |
| Thickness | 1.5 mm |
| Intended benefit | Extreme magnetic headroom and low-end stability under high-level input |

The intended product behavior is that the user can drive the System Q input or output cards hard without the tape stage thinning out or losing low-end detail.

## 3. The 12-Track Head Array

The first architecture assumes custom-wound heads designed around high-voltage analog signals.

| Head | Material | Role |
| --- | --- | --- |
| Erase head | Ferrite | Clears the cylinder every rotation. |
| Record head | Permalloy | Driven by the System Q input cards. |
| Repro head | Sendust | Positioned after the record head and wired directly to the integrated A/D converter. |

The current concept places the repro head 3 inches after the record head.

At 30ips, a 3-inch record-to-repro spacing produces roughly 100 ms of delay:

```text
delay = spacing / speed
delay = 3 in / 30 in/sec = 0.1 sec
```

That delay should be treated as part of the integration design. It may be useful for monitoring character or effect behavior, but it must be compensated when the Tape Cylinder is used as a recording path into the DAW.

## 4. DAW Integration

The Tape Cylinder should be controlled through the System Q transport layer.

The implementation target is currently `Development/software/system_q_transport.py`.

| Feature | Behavior |
| --- | --- |
| Auto-cue | The cylinder spins up when a track is armed for recording. |
| Sync-lock | Motor speed adjusts in micro-increments to stay phase-aligned with the DAW clock. |
| Recall | Bias and EQ settings are saved as part of the DAW session metadata. |

## 5. Bias Card Behavior

The Tape Cylinder should support swappable bias behavior through the System Q frame.

For example:

- A Zappa-style bias card could emphasize aggressive midrange saturation and fast transient response.
- A Zeppelin-style bias card could emphasize weight, transient bloom, and low-mid thickness.

The purpose of the bias card is to change how the cylinder reacts to incoming audio without requiring a full mechanical or magnetic assembly swap.

## 6. Historic Card Integration

The Tape Cylinder is not isolated from the rack card idea. It is the magnetic stage that historic input and output cards can hit.

Example input-card families:

- Abbey Road-inspired capture
- Sausalito Record Plant / API-inspired capture
- Zeppelin Mobile / Neve-inspired capture
- Zappa UMRK / Harrison-Trident-inspired capture
- Tom Scholz Basement-inspired capture

Example output-card families:

- SSL bus-inspired print
- RCA New York Church-inspired output
- Les Paul Studio-inspired overdub/print path
- Bill Putnam / United-inspired print path
- Abbey Road-inspired print
- Power Station-inspired print

The card references should be treated as voicing references and product-language anchors, not as licensed clones or literal reproductions.

## 7. Engineering Validation Notes

The following points are not settled engineering claims yet. They are prototype risks that need specialist validation before buyer-facing technical claims are made.

- A 1.5 mm magnetic coating is far thicker than conventional tape oxide layers and may require custom head-gap geometry, field strength, surface finishing, and wear testing.
- The phrase "2-inch track spacing" should be avoided externally. The accurate reference is 2-inch tape width.
- Thick coating headroom, low-frequency retention, erase behavior, and noise floor must be measured rather than assumed.
- "Cannot clip" should not be used as an engineering claim. The safer claim is magnetic overload buffering: saturation and compression before hard digital clipping.
- The erase/record/repro array needs mechanical tolerance analysis at 114.6 RPM.
- DAW sync-lock needs a defined control loop, encoder feedback path, jitter target, and failure behavior.
- The 100 ms repro delay must be compensated or intentionally exposed as a creative monitoring/effect mode.

## Current Positioning

Externally, this should be described as a premium analog cylinder concept inside System Q, not as proven replacement technology for a Studer machine.

The useful claim is:

> System Q is exploring a clock-locked analog tape-cylinder stage that lets historic input and output cards hit a physical magnetic buffer before conversion, print, monitoring, or Venue playback.
