import time
import json
import appdaemon.plugins.hass.hassapi as hass

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

  def _setState(self, timer_handle, off_time):
    if self.state_id is None:
        return

    if timer_handle is not None:
      state = "on"
    else:
      state = "off"
    self.set_state("irisone.state_{}".format(self.state_id), state=state, attributes={"timer": timer_handle, "off_time": off_time})

  def _getState(self):
    if self.state_id is None:
      return { "timer_handle": None, "off_time": 0 }

    timer_handle = self.get_state("irisone.state_{}".format(self.state_id), attribute="timer")
    off_time = self.get_state("irisone.state_{}".format(self.state_id), attribute="off_time")
    if off_time is None:
      off_time = 0
    return { "timer_handle": timer_handle, "off_time": off_time }

  def motion(self, entity, attribute, old, new, kwargs):
    if (old != self.state_from and "*" != self.state_from) or new != self.state_to:
      return

    if not self.whensunup and self.sun_up():
      return

    now = int(time.time())
    off_time = now + self.timeout
    
    stored_state = self._getState()
    if stored_state.get("off_time", 0) > off_time:
      self.log("\tStored off_time is greater then new, exiting ({} > {})".format(stored_state.get("off_time", 0), off_time))
      return

    for light in self.light:
      if stored_state.get("timer_handle") is not None:
        # if we already have a timer that ends before the new remove it
        self.log("\tExsisting timer_handle is canceled new:{} old:{}".format(off_time, stored_state.get("off_time")))
        self.cancel_timer(stored_state.get("timer_handle"))
      else:
        # otherwise keep it and do nothing
        self.log("\tExsisting timer_handle does not exist new:{} old:{}".format(off_time, stored_state.get("off_time")))

      self.log("\tTurning ON '{}'".format(light))
      self.turn_on(light)
      handle = self.run_in(self.light_off, self.timeout, light=light)
      self._setState(handle, off_time)

  def light_off(self, kwargs):
    if self.override_id is not None:
        screensaver = self.get_state(self.override_id)
        self.log("\tscreensaver {} state: {}".format(self.override_id, screensaver))
        if screensaver == "off":
            now = int(time.time())
            off_time = now + 60
            self.log("\tOverride screen saver is off")
            handle = self.run_in(self.light_off, self.timeout, light=kwargs["light"])
            self._setState(handle, off_time)
            return

    light = kwargs["light"]
    self.log("\tTurning OFF {}".format(light))
    self.turn_off(light)
    self._setState(None, 0)
