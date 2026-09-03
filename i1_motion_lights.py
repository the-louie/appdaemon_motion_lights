import time
import json
import appdaemon.plugins.hass.hassapi as hass

import light_deadline as deadline

DEFAULT_LAMP_TIMEOUT = 300


class GenericMotion(hass.Hass):
  def initialize(self):
    self.log("Loading GenericMotion()")


    self.state_id = self.args.get("state_id")
    self.sensor = self.args.get("sensor", None)
    self.override_id = self.args.get("override_id")
    self.light = self.args.get("light", None)
    self.state_from = str(self.args.get("from", None))
    self.state_to = str(self.args.get("to", None))
    self.whensunup = bool(self.args.get("sunup", False))
    if self.sensor is None or self.light is None:
      self.log(" >> GenericMotion.initialize(): Warning - Not configured")
      return
    if not isinstance(self.light, list):
      self.light = [self.light]

    self.timeout = self.args.get("timeout", DEFAULT_LAMP_TIMEOUT)

    # Verify the configured entities EXIST before listening to them.
    #
    # verkstad_motion has been bound to
    # binary_sensor.v0_verkstad_eye_security_motion_detection since its first
    # commit. That entity does not exist -- not under that name, not under any
    # other. The Verkstad area holds one bulb and a Z-Wave stick, and none of
    # Home Assistant's 148 motion or occupancy entities is in the workshop.
    #
    # listen_state() on a non-existent entity registers happily and never
    # fires, so the app has been loading cleanly and doing nothing at all for
    # as long as it has existed. Nothing reported it. That is the failure this
    # check removes: an app that cannot work should say so at startup.
    self._handle = None
    self._report_missing_entities()

    self.listen_state(self.motion, self.sensor)
    
    #self.listen_state(self.stored_state_update, "irisone.state_{}".format(self.state_id))

    self.log(" >> GenericMotion {}:{}->{} ==> {}".format(self.sensor,
                                                         self.state_from,
                                                         self.state_to,
                                                         self.light))

  def _report_missing_entities(self):
    """Distinguish 'never existed' from 'currently down'. Returns the missing.

    A MISSING entity is a configuration error: the id is wrong or the hardware
    was removed, and no amount of waiting will fix it. An UNAVAILABLE one is a
    device that is off the network and may well come back, so it is worth a
    warning and nothing more.

    Collapsing the two would either cry wolf at every flat battery or stay
    silent about a permanently dead binding. They are different problems.
    """
    missing = []
    unavailable = []
    for entity in [self.sensor] + list(self.light):
      state = self.get_state(entity)
      if state is None:
        missing.append(entity)
      elif str(state).lower() in ("unavailable", "unknown", ""):
        unavailable.append(entity)

    if missing:
      self.log(
        " >> GenericMotion.initialize(): ENTITY DOES NOT EXIST: {}. "
        "listen_state() will register and never fire, so this app will load "
        "cleanly and do nothing. Fix the entity id or remove the app.".format(
          ", ".join(missing)
        ),
        level="ERROR",
      )
    if unavailable:
      self.log(
        " >> GenericMotion.initialize(): entity currently unavailable: {}. "
        "It may return; the app will work when it does.".format(
          ", ".join(unavailable)
        ),
        level="WARNING",
      )
    return missing

  def _set_deadline(self, off_time):
    """Publish the shared deadline. No timer handle is ever shared: see
    light_deadline.py for why sharing one cannot work."""
    if self.state_id is None:
      return
    state = "on" if off_time else "off"
    self.set_state(
      "irisone.state_{}".format(self.state_id),
      state=state,
      attributes={"off_time": off_time},
    )

  def _get_deadline(self):
    if self.state_id is None:
      return deadline.OFF
    return deadline.parse(
      self.get_state("irisone.state_{}".format(self.state_id), attribute="off_time")
    )

  def _arm(self, seconds):
    """Arm our OWN off-check. Cancelling our own previous handle is legal;
    cancelling the other app's never was -- cancel_timer is app-scoped."""
    if self._handle is not None:
      try:
        self.cancel_timer(self._handle)
      except Exception:
        pass  # a handle that has already fired is not an error
    self._handle = self.run_in(self.check_deadline, max(1, int(seconds)))

  def motion(self, entity, attribute, old, new, kwargs):
    if (old != self.state_from and "*" != self.state_from) or new != self.state_to:
      return

    if not self.whensunup and self.sun_up():
      return

    now = int(time.time())
    stored = self._get_deadline()
    off_time = deadline.extend(stored, now, self.timeout)
    self.log("\tMotion: deadline {} -> {} ({}s)".format(stored, off_time, off_time - now))

    self._set_deadline(off_time)
    for light in self.light:
      self.log("\tTurning ON '{}'".format(light))
      self.turn_on(light)
    self._arm(off_time - now)

  def check_deadline(self, kwargs):
    """Turn off only if the shared deadline has actually passed.

    This is the whole fix. A timer that fires while the other app has since
    extended the deadline re-arms instead of killing the light, so the person
    standing in the workshop keeps their light.
    """
    self._handle = None
    now = int(time.time())
    off_time = self._get_deadline()

    if self.override_id is not None and self.get_state(self.override_id) == "off":
      # Something says keep it on a little longer; extend rather than turn off.
      off_time = deadline.extend(off_time, now, 60)
      self.log("\tOverride {} is off; extending 60s".format(self.override_id))
      self._set_deadline(off_time)
      self._arm(deadline.remaining(off_time, now))
      return

    if not deadline.expired(off_time, now):
      left = deadline.remaining(off_time, now)
      self.log("\tDeadline extended elsewhere; re-arming for {}s".format(left))
      self._arm(left)
      return

    for light in self.light:
      self.log("\tTurning OFF {}".format(light))
      self.turn_off(light)
    self._set_deadline(deadline.OFF)
