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
    self.listen_state(self.motion, self.sensor)
    
    #self.listen_state(self.stored_state_update, "irisone.state_{}".format(self.state_id))

    self.log(" >> GenericMotion {}:{}->{} ==> {}".format(self.sensor,
                                                         self.state_from,
                                                         self.state_to,
                                                         self.light))

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
