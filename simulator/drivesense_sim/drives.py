"""Scripted drives.

`DEMO_DRIVE` exercises every behaviour the model claims to have: launch,
upshifts through the box, a corner, braking, a downshift, a stop, and revving
in neutral. It backs the golden regression test and gives the headless mode
something realistic to record.

Milestone 7 will add calm / normal / aggressive profile drives here. No other
part of the simulator changes when it does.
"""

from __future__ import annotations

from drivesense_sim.input.providers import ScriptStep

DEMO_DRIVE: list[ScriptStep] = [
    ScriptStep(1.0),  # idle
    ScriptStep(0.5, clutch=1.0, shift_up=True),  # neutral -> 1st
    ScriptStep(0.6, clutch=1.0, throttle=0.3),  # blip while disengaged
    ScriptStep(3.0, throttle=1.0),  # launch in 1st
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 2nd
    ScriptStep(3.5, throttle=1.0),
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 3rd
    ScriptStep(4.0, throttle=0.9),
    ScriptStep(0.4, clutch=1.0, shift_up=True),  # -> 4th
    ScriptStep(4.0, throttle=0.7),
    ScriptStep(3.0, throttle=0.4, steer=0.35),  # steady corner
    ScriptStep(3.0, brake=0.6),  # braking
    ScriptStep(0.4, clutch=1.0, shift_down=True),  # -> 3rd
    ScriptStep(2.0, throttle=0.5),
    ScriptStep(2.5, brake=0.9),  # to a stop
    ScriptStep(0.5, clutch=1.0, engage_neutral=True),
    ScriptStep(2.5, throttle=0.8),  # rev in neutral
    ScriptStep(1.0),
]
