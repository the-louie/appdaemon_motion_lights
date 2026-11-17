"""Deadline arithmetic for lights owned by more than one AppDaemon app.

T-40 / S4-09. `light.v0_verkstad_vagg` is driven by two apps — `i1_zha` (a wall
switch) and `i1_motion_lights` (a PIR) — which coordinated through a shared
Home Assistant entity holding `{timer, off_time}`, where `timer` was an
AppDaemon timer handle.

**That cannot work, and not by a small margin.** `cancel_timer` is scoped to
the calling app: it looks the handle up in `self.schedule[<calling app>]`, so
one app cancelling a handle written by another falls through to
`WARNING Invalid callback handle ... in cancel_timer()` and returns `False`.
The cancel is a guaranteed no-op, and every failure below follows from it:

- Switch at T arms an off for T+1800. Motion at T+700 arms T+1900 and
  "cancels" the switch's handle. At **T+1800 the light goes dark while someone
  is standing in the workshop.**
- Motion at T arms T+1200. The switch turning off at T+30 zeroes the shared
  entity without cancelling anything, losing the handle to both apps. Switch on
  at T+40 arms T+1840 — and the orphaned T+1200 timer **kills the light ten
  minutes into the user's half hour.**
- Orphans accumulate one per cycle, so the light always dies at the earliest.

The fix is to stop sharing a handle at all. The shared state becomes a single
number: the epoch second at which the light may go off. Each app arms only its
**own** timers, and when one fires it asks the deadline rather than assuming.
A timer that fires early re-arms; a timer that fires late finds the work done.
Nothing needs to cancel anything, so nothing can fail to.

These functions are pure so the arithmetic can be tested without AppDaemon, and
copied byte-identical into both repos — the same arrangement as
`notification_policy.py`, for the same reason: these are independent git
repositories and neither may depend on the other being deployed.
"""

# A deadline of zero means "no reason for this light to be on".
OFF = 0


def extend(stored, now, timeout):
    """The new deadline after an on-event. Never shortens an existing one.

    Whoever wants the light on for longest wins, which is the only rule that
    behaves sensibly when a person is both triggering the PIR and pressing the
    switch. Note this replaces the old "stored is greater, so do nothing"
    branch: that let a shorter timeout **veto the turn-on itself**, so with
    motion at 1200s and the switch lowered below it, the wall switch silently
    did nothing.
    """
    candidate = int(now) + int(timeout)
    return max(int(stored or OFF), candidate)


def expired(deadline, now):
    """True when the light may go off."""
    return int(now) >= int(deadline or OFF)


def remaining(deadline, now):
    """Seconds left, never negative — a re-arm delay must not be in the past."""
    return max(0, int(deadline or OFF) - int(now))


def parse(value):
    """Read a deadline out of an HA attribute, tolerating junk.

    The attribute round-trips through Home Assistant's state machine, so it can
    come back as a string, as None from a missing entity, or as whatever a
    previous version of these apps wrote there — including a timer handle,
    which is a UUID string. Anything unreadable means "no deadline", which
    fails toward turning the light off rather than leaving it on forever.
    """
    if value is None:
        return OFF
    try:
        return max(OFF, int(float(value)))
    except (TypeError, ValueError):
        return OFF


def as_attributes(off_time):
    """The shared entity's attributes for a deadline, lossless through AppDaemon (T-78).

    AppDaemon 4.5.13's set_state silently drops a 0 (0 == False), and an empty
    attribute dict never clears the old value, so "off" was only ever right by
    luck. The deadline is written as a string, which survives, and parse() reads
    it back exactly: "0" is OFF. Always pass replace=True with it, or AppDaemon
    merges its own bookkeeping fields into the attributes.
    """
    return {"off_time": str(max(OFF, int(off_time or OFF)))}
