import serial
import time

class Laser:
    """
    This device adapter allows control of Cobolt 01-06 MLD lasers in
    constant power and digital or analog modulation modes. For this
    adapter to work properly, the laser should be configured for OEM and
    have autostart disabled.
    
    The laser constructor takes a wavelength, which it checks against
    the wavelength of the laser at that COM port. This is a "belt and
    suspenders" check to make sure that you are connected to the cobolt
    laser you intend in case there are multiple cobolt lasers on a
    system. Changing this parameter will not change the wavelength of
    the actual laser.
    """
    def __init__(self,
                 which_port,
                 wavelength_nm, # of the laser you intend to connect to
                 verbose=True,
                 very_verbose=False):
        self.verbose = verbose
        self.very_verbose = very_verbose
        self.w = wavelength_nm
        if self.verbose: print('Cobolt %d: Initializing laser...'%self.w)
        try:
            self.port = serial.Serial(port=which_port, baudrate=115200)
        except serial.serialutil.SerialException:
            raise IOError('No connection to laser on port %s'%which_port)
        mn = self.get_model_number()
        # parse model number to get wavelength and max power
        fields = mn.split('-')
        assert wavelength_nm == int(fields[0]) # we connected to correct laser
        self.max_power_mW = int(fields[3])
        if self.very_verbose:
            print('Cobolt %d: Maximum power %d mW'%(self.w,self.max_power_mW))
        if self.verbose: print('Cobolt %d: Connected to laser.'%self.w)
        return None

    def configure(self,
                  mode,         # 'continuous' or 'modulation'
                  power_mW,     # 0 < float <= max for the laser (in init)
                  digital_mod_enabled=None, # for 'fast modulation' mode
                  analog_mod_enabled=None): # for 'fast modulation' mode
        # set up digital or analog modulation before we change the mode
        # so that if it's on it behaves as expected. Note that if both
        # digital and analog modulation are "off" in modulation mode,
        # the laser will not emit.
        if digital_mod_enabled is not None:
            self.set_digital_modulation_enable_state(digital_mod_enabled)
        if analog_mod_enabled is not None:
            self.set_analog_modulation_enable_state(analog_mod_enabled)
        if mode == 'continuous':
            self.set_power_setpoint(power_mW)
        elif mode == 'modulation':
            self.set_modulation_power_setpoint(power_mW)
        self.set_mode(mode) # do last; could change whether we are emitting
        return None

    def get_on_off_state(self):
        # Note that this will still return "ON" in certain fault states where
        # it isn't actually "ON"...not 100% trustworthy
        code = int(self._send('l?'))
        assert code in [0, 1]
        status = {0: 'OFF', 1: 'ON'}[code]
        if self.very_verbose:
            print('Cobolt %d: Laser is %s'%(self.w, status))
        return status

    def run_autostart(self):
        if self.verbose:
            print('Cobolt %d: Powering laser on'%self.w)
        ilk = self.is_interlock_open()
        if ilk:
            print('Cobolt %d: Interlock is open'%self.w)
            raise RuntimeError('Could not turn on laser diode')
        answer = self._send('@cob1')
        if answer != 'OK':
            print('Cobolt %d:'%self.w, answer)
            raise RuntimeError('Unable to autostart Cobolt %d laser'%self.w)
        time.sleep(0.5) # let autostart execute before we check
        assert self.get_on_off_state() == 'ON'
        return None

    def turn_on(self):
        if self.verbose:
            print('Cobolt %d: Turning on diode...'%self.w)
        ilk = self.is_interlock_open()
        if ilk:
            print('Cobolt %d: Interlock is open'%self.w)
            raise RuntimeError('Could not turn on laser diode')
        answer = self._send('l1')
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Could not turn on laser diode')
        assert self.get_on_off_state() == 'ON'
        return None

    def turn_off(self):
        if self.verbose:
            print('Cobolt %d: Turning off diode...'%self.w)
        answer = self._send('l0')
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Could not disable laser emission')
        assert self.get_on_off_state() == 'OFF'
        return None        

    def get_state(self):
        """
        Returns the state of the laser at this moment. Note that the
        laser will return off if it is off, regardless of what mode it
        will come into when it turns on. For example, if you set the
        mode to modulation while the laser is off, it will obey this
        when it comes on, but get_state will still return OFF.
        """
        code = int(self._send('gom?'))
        assert code in [0, 1, 2, 3, 4, 5, 6]
        state = {0: 'Off', 1: 'Waiting for key', 2: 'Continuous',
                 3: 'On/Off Modulation', 4: 'Modulation', 5: 'Fault',
                 6: 'Aborted'}[code]
        if self.very_verbose:
            print('Cobolt %d: Current mode is %s'%(self.w, mode))
        return state

    def set_mode(self, mode):
        mode2command = {'continuous': 'cp', # constant power
                        'modulation': 'em'} # analog/digital modulation
        assert mode in mode2command.keys()
        answer = self._send(mode2command[mode])
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Unable to set mode on Cobolt %d laser'%self.w)
        # There isn't a symmetrical getter; see get_state documentation.
        # If the mode is set while the laser is off, we can't confirm it.
        if self.get_on_off_state() == "ON":
            assert self.get_state()[1:] == mode[1:] # ignore capitalization
        if self.verbose:
            print('Cobolt %d: Set mode to %s'%(self.w, mode))
        return None

    def get_digital_modulation_enable_state(self):
        """
        Retrieves whether digital modulation is enabled. Note that the
        laser must also be in "fast modulation" mode for digital
        modulation to be accessible, which this function does not check.
        """
        enabled = int(self._send('gdmes?'))
        assert enabled in [0, 1]
        if self.very_verbose:
            print('Cobolt %d: Digital modulation enabled? %d'%(self.w,enabled))
        return enabled

    def set_digital_modulation_enable_state(self, enabled):
        assert enabled in [True, False]
        answer = self._send('sdmes %d'%enabled)
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Unable to change digital modulation')
        assert enabled == self.get_digital_modulation_enable_state()
        if self.verbose:
            print('Cobolt %d: set digital modulation enabled flag'%self.w)
        return None

    def get_analog_modulation_enable_state(self):
        """
        Retrieves whether analog modulation is enabled. Note that the
        laser must also be in "fast modulation" mode for analog
        modulation to be accessible, which this function does not check.
        """
        enabled = int(self._send('games?'))
        assert enabled in [0, 1]
        if self.very_verbose:
            print('Cobolt %d: Analog modulation enabled? %d'%(self.w,enabled))
        return enabled

    def set_analog_modulation_enable_state(self, enabled):
        assert enabled in [True, False]
        answer = self._send('sames %d'%enabled)
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Unable to change analog modulation')
        assert enabled == self.get_analog_modulation_enable_state()
        if self.verbose:
            print('Cobolt %d: set analog modulation enabled flag'%self.w)
        return None

    def get_power_setpoint(self):
        """
        Retrieves the set point for constant power mode. Note that this
        function does not check whether the laser is actually in
        constant power mode, and this power setting does not apply to
        the fast (digital/analog) modulation mode.
        """
        power_mW = float(self._send('p?')) * 1000 # convert from W
        if self.very_verbose:
            print('Cobolt %d: Power set point is %0.1f mW'%(self.w,power_mW))
        return power_mW

    def set_power_setpoint(self, power_mW):
        """
        Changes the set point for constant power mode. Note that this
        function does not check whether the laser is actually in
        constant power mode, and this power setting does not apply to
        the fast (digital/analog) modulation mode.
        """
        assert 0 < power_mW <= self.max_power_mW
        answer = self._send('p %0.4f'%(power_mW/1000)) # convert to W
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Unable to update power on %d laser'%self.w)
        assert round(power_mW, 4) == round(self.get_power_setpoint(), 4)
        if self.verbose:
            print('Cobolt %d: New constant power set point is %0.1f mW'%(
                self.w,power_mW))
        return None

    def get_modulation_power_setpoint(self):
        """
        Retrieves the power set point for  fast modulation (digital
        and/or analog) mode. Note that this function does not check
        whether the laser is actually in fast modulation mode, and this
        power setting does not apply to constant power mode.
        """
        power_mW = float(self._send('glmp?')) # will return mW directly
        if self.very_verbose:
            print('Cobolt %d: Modulation power set point is %0.1f mW'%(
                self.w,power_mW))
        return power_mW

    def set_modulation_power_setpoint(self, power_mW):
        """
        Changes the set point for constant power mode. Note that this
        function does not check whether the laser is actually in
        constant power mode, and this power setting does not apply to
        the fast (digital/analog) modulation mode.
        """
        assert 0 < power_mW <= self.max_power_mW
        answer = self._send('slmp %0.1f'%power_mW) # in mW
        if answer != 'OK':
            print('Cobolt %d: '%self.w, answer)
            raise RuntimeError('Unable to update power on %d laser'%self.w)
        assert round(power_mW,4)==round(self.get_modulation_power_setpoint(),4)
        if self.verbose:
            print('Cobolt %d: New modulation power set point is %0.1f mW'%(
                self.w,power_mW))
        return None

    def get_actual_power(self):
        """
        Reads the actual output power from the laser.
        """
        power_mW = float(self._send('pa?')) * 1000
        if self.very_verbose:
            print('Cobolt %d: Actual output power = %0.1f mW'%(self.w,power_mW))
        return power_mW

    def get_actual_current(self):
        """
        Reads the actual output current from the laser.
        """
        current_mA = float(self._send('i?'))
        if self.very_verbose:
            print('Cobolt %d: Actual output current is %0.1f W'%(self.w,
                                                                 current_mA))
        return current_mA

    def get_serial_number(self):
        sn = int(self._send('gsn?'))
        if self.very_verbose:
            print('Cobolt %d: Serial Number %d'%(self.w,sn))
        return sn

    def get_model_number(self):
        mn = self._send('glm?')
        if self.very_verbose:
            print('Cobolt %d: Model number %s'%(self.w,mn))
        return mn

    def get_operating_hours(self):
        hrs = float(self._send('hrs?'))
        if self.very_verbose:
            print('Cobolt %d: Laser head operating hours %0.2f'%(self.w,hrs))
        return hrs

    def get_fault(self):
        code = self._send('f?')
        assert code in ['0', '1', '3', '4']
        fault = {'0': 'no errors', '1': 'temperature error',
                 '3': 'interlock error', '4': 'constant power time out'}[code]
        if self.very_verbose:
            print('Cobolt %d: Fault status is %s'%(self.w, fault))
        return None

    def clear_fault(self):
        assert self._send('cf') == 'OK'
        if self.verbose: print('Cobolt %d: Cleared fault'%self.w)
        return None

    def is_interlock_open(self):
        is_open = int(self._send('ilk?'))
        assert is_open in [0, 1]
        if self.very_verbose:
            print('Cobolt %d: Interlock is open flag: '%(self.w, is_open))
        return is_open        

    def _send(self, cmd):
        assert isinstance(cmd, str)
        cmd = bytes(cmd + '\r\n', 'ascii')
        if self.very_verbose:
            print('Cobolt %d: Bytes written:'%self.w, cmd)
        self.port.write(cmd)
        response = self.port.read_until(expected=b'\r\n')
        if self.very_verbose:
            print('Cobolt %d: Bytes received:'%self.w, response)
        assert self.port.in_waiting == 0
        return response.decode('ascii').strip('\r\n')

    def close(self):
        self.turn_off()
        self.port.close()
        if self.verbose: print('Cobolt %d: Closing'%self.w)
        return None

if __name__ == '__main__':
    laser = Laser('COM8', wavelength_nm=785, verbose=True, very_verbose=False)
    laser.configure(mode='continuous', power_mW=1)
    laser.run_autostart() # or laser.turn_on()
    time.sleep(2)
    # To check modulation, you need the ability to send modulating
    # signals to the laser. I used a BNC525 box from Berkeley
    # Nucleonics, configured to a 50% duty cycle square wave at 0.5 Hz.
    # Connect to the digital modulation connector on the laser.
    laser.configure(mode='modulation', power_mW=10, analog_mod_enabled=False,
                    digital_mod_enabled=True)
    time.sleep(10)
    # TODO: set up a similar check for analog modulation (0-1 V)
    laser.configure(mode='modulation', power_mW=10, analog_mod_enabled=True,
                    digital_mod_enabled=False)
    time.sleep(5)
    laser.configure(mode='continuous', power_mW=1)
    time.sleep(2)
    laser.close() # will turn off the diode
        
