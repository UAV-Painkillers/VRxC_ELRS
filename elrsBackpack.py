import logging
import hashlib
import serial
import time
import copy

from threading import Thread, Lock
import queue
import serial.tools.list_ports
import gevent

import RHUtils
from RHRace import RaceStatus
from VRxControl import VRxController
from RHGPIO import RealRPiGPIOFlag
if RealRPiGPIOFlag:
    import RPi.GPIO as GPIO

from plugins.VRxC_ELRS.hardware import HARDWARE_SETTINGS
from plugins.VRxC_ELRS.msp import msptypes, msp_message

logger = logging.getLogger(__name__)

class elrsBackpack(VRxController):
    
    _queue_lock = Lock()
    _delay_lock = Lock()
    _connector_status_lock = Lock()
    _repeat_count = 0
    _send_delay = 0.05

    _backpack_connected = False
    
    _heat_name = None
    _heat_data = {}
    _finished_pilots = []
    _queue_full = False

    # last persisten message per pilot(id)
    _last_persistent_betaflight_craftname_message = {}
    _activePilotIdentifier = None

    def __init__(self, name, label, rhapi):
        super().__init__(name, label)
        self._rhapi = rhapi

        self._backpack_queue = queue.Queue(maxsize=200)
        Thread(target=self.backpack_connector, daemon=True).start()

    def registerHandlers(self, args):
        args['register_fn'](self)

    def setOptions(self, _args = None):

        self._queue_lock.acquire()

        if self._rhapi.db.option('_heat_name') == "1":
            self._heat_name = True
        else:
            self._heat_name = False
        if self._rhapi.db.option('_position_mode') == "1":
            self._position_mode = True
        else:
            self._position_mode = False
        if self._rhapi.db.option('_gap_mode') == "1":
            self._gap_mode = True
        else:
            self._gap_mode = False
        if self._rhapi.db.option('_results_mode') == "1":
            self._results_mode = True
        else:
            self._results_mode = False

        self._racestage_message = self._rhapi.db.option('_racestage_message')
        self._racestart_message = self._rhapi.db.option('_racestart_message')
        self._pilotdone_message = self._rhapi.db.option('_pilotdone_message')
        self._racefinish_message = self._rhapi.db.option('_racefinish_message')
        self._racestop_message = self._rhapi.db.option('_racestop_message')
        self._leader_message = self._rhapi.db.option('_leader_message')

        self._racestart_uptime = self._rhapi.db.option('_racestart_uptime') * 1e-1
        self._finish_uptime = self._rhapi.db.option('_finish_uptime') * 1e-1
        self._results_uptime = self._rhapi.db.option('_results_uptime') * 1e-1
        self._announcement_uptime = self._rhapi.db.option('_announcement_uptime') * 1e-1

        self._status_row = self._rhapi.db.option('_status_row')
        self._currentlap_row = self._rhapi.db.option('_currentlap_row')
        self._lapresults_row = self._rhapi.db.option('_lapresults_row')
        self._announcement_row = self._rhapi.db.option('_announcement_row')

        self._repeat_count = self._rhapi.db.option('_bp_repeat')
        with self._delay_lock:
            self._send_delay = self._rhapi.db.option('_bp_delay') * 1e-5

        self._queue_lock.release()

    def start_race(self):
        if self._rhapi.db.option('_race_control') == '1':
            start_race_args = {'start_time_s' : 10}
            if self._rhapi.race.status == RaceStatus.READY:
                self._rhapi.race.stage(start_race_args)

    def stop_race(self):
        if self._rhapi.db.option('_race_control') == '1':
            status = self._rhapi.race.status
            if status == RaceStatus.STAGING or status == RaceStatus.RACING:
                self._rhapi.race.stop()

    def reboot_esp(self, _args):
        if RealRPiGPIOFlag:
            GPIO.output(11, GPIO.LOW)
            time.sleep(1)
            GPIO.output(11, GPIO.HIGH)
            message = "Cycle Complete"
            self._rhapi.ui.message_notify(self._rhapi.language.__(message))

    #
    # Backpack communications
    #

    def combine_bytes(self, a, b):
        return (b << 8) | a

    def backpack_connector(self):
        version = msp_message()
        version.set_function(msptypes.MSP_ELRS_GET_BACKPACK_VERSION)
        version_message = version.get_msp()
        
        logger.info("Attempting to find backpack")
        
        ports = list(serial.tools.list_ports.comports())
        s = serial.Serial(baudrate=460800,
                        bytesize=8, parity='N', stopbits=1,
                        timeout=0.01, xonxoff=0, rtscts=0)
        
        #
        # Search for connected backpack
        #

        for port in ports:
            s.port = port.device
            
            try:
                s.open()
            except:
                logger.warning('Failed to open serial device. Attempting to connect to new device...')
                continue
            
            time.sleep(1.5) # Needed for connecting to DevKitC

            try:
                s.write(version_message)
            except:
                logger.error('Failed to write to open serial device. Attempting to connect to new device...')
                s.close()
                continue

            response = list(s.read(8))
            if len(response) == 8:
                logger.info(f'Device response: {response}')
                if response[:3] == [ord('$'),ord('X'),ord('>')]:
                    mode = self.combine_bytes(response[4], response[5])
                    response_payload_length = self.combine_bytes(response[6], response[7])
                    response_payload = list(s.read(response_payload_length))
                    response_check_sum = list(s.read(1))

                    if mode == msptypes.MSP_ELRS_BACKPACK_SET_MODE or mode == msptypes.MSP_ELRS_GET_BACKPACK_VERSION:
                        logger.info(f"Connected to backpack on {port.device}")

                        version_list = [chr(val) for val in response_payload]
                        logger.info(f"Backpack version: {''.join(version_list)}")

                        with self._connector_status_lock:
                            self._backpack_connected = True
                        break
                    
                    else:
                        logger.warning(f"Unexpected response from {port.device}, trying next port...")
                        s.close()
                        continue
                else:
                    logger.warning(f"Unrecongnized response from {port.device}, trying next port...")
                    s.close()
                    continue
            else:
                logger.warning(f"Bad response from {port.device}, trying next port...")
                s.close()
                continue
        else:
            logger.warning("Could not find connected backpack. Ending connector thread.")
            with self._connector_status_lock:
                self._backpack_connected = False

        #
        # Backpack connection loop
        #

        with self._connector_status_lock:
            backpack_connected = copy.copy(self._backpack_connected)
        
        error_count = 0
        while backpack_connected:

            self._delay_lock.acquire()
            delay = copy.copy(self._send_delay)
            self._delay_lock.release()

            # Handle backpack comms 
            while not self._backpack_queue.empty():
                message = self._backpack_queue.get()
                time.sleep(delay)
                
                try:
                    s.write(message)
                except:
                    error_count += 1
                    if error_count > 5:
                        logger.error('Failed to write to backpack. Ending connector thread')
                        s.close()
                        with self._connector_status_lock:
                            self._backpack_connected = False
                        return
                else:
                    error_count = 0

            packet = list(s.read(8))
            if len(packet) == 8:
                if packet[:3] == [ord('$'),ord('X'),ord('<')]:
                    mode = self.combine_bytes(packet[4], packet[5])
                    payload_length = self.combine_bytes(packet[6], packet[7])
                    payload = list(s.read(payload_length))
                    check_sum = list(s.read(1))

                    # Monitor SET_RECORDING_STATE for controlling race
                    if mode == msptypes.MSP_ELRS_BACKPACK_SET_RECORDING_STATE:
                        if payload[0] == 0x00:
                            gevent.spawn(self.stop_race)
                        elif payload[0] == 0x01:
                            gevent.spawn(self.start_race)
            
            with self._connector_status_lock:
                backpack_connected = copy.copy(self._backpack_connected)

            time.sleep(0.01)

    #
    # Backpack message generation
    #

    def hash_phrase(self, bindphrase:str) -> list:
        bindingPhraseHash = [x for x in hashlib.md5(("-DMY_BINDING_PHRASE=\"" + bindphrase + "\"").encode()).digest()[0:6]]
        if (bindingPhraseHash[0] % 2) == 1:
            bindingPhraseHash[0] -= 0x01
        return bindingPhraseHash
    
    def centerOSD(self, stringlength, hardwaretype):
        # return 0 if row size is not defined or hardwaretype is not defined in HARDWARE_SETTINGS
        if hardwaretype not in HARDWARE_SETTINGS:
            return 0
        
        if 'row_size' not in HARDWARE_SETTINGS[hardwaretype]:
            return 0

        offset = int(stringlength/2)
        if hardwaretype:
            col = int(HARDWARE_SETTINGS[hardwaretype]['row_size'] / 2) - offset
            if col < 0:
                col = 0
        else:
            col = 0
        return col

    def queue_add(self, msp):
        with self._connector_status_lock:
            if self._backpack_connected is False:
                return
        try:
            self._backpack_queue.put(msp, block=False)
        except queue.Full:
            if self._queue_full is False:
                self._queue_full = True
                message = 'ERROR: ELRS Backpack not responding. Please reboot the server to attempt to reconnect.'
                self._rhapi.ui.message_alert(self._rhapi.language.__(message))
        else:
            if self._queue_full is True:
                self._queue_full = False
                message = 'ELRS Backpack has start responding again.'
                self._rhapi.ui.message_notify(self._rhapi.language.__(message))
    
    def send_msp(self, msp):
        self.queue_add(msp)
        if self.combine_bytes(msp[4], msp[5]) == msptypes.MSP_ELRS_SET_OSD:
            for _ in range(self._repeat_count):
                self.queue_add(msp)
            
    def set_sendUID(self, bindingHash:list):
        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_SET_SEND_UID)
        message.set_payload([1] + bindingHash)
        self.send_msp(message.get_msp())
        self._activePilotIdentifier = '.'.join(map(str, bindingHash))

    def clear_sendUID(self):
        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_SET_SEND_UID)
        message.set_payload([0])
        self.send_msp(message.get_msp())

        self._activePilotIdentifier = None

    def send_clear(self, hardwaretype, displayLastPersistentMessage = True):
        if hardwaretype == 'betaflight_craftname':
            persistentMessageToRecover = self._last_persistent_betaflight_craftname_message.get(self._activePilotIdentifier)
            if displayLastPersistentMessage and persistentMessageToRecover:
                self.send_msg(0, 0, persistentMessageToRecover, hardwaretype, False)
                return

            self.send_msg(0, 0, '    ', hardwaretype, False)
            return

        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_SET_OSD)
        message.set_payload([0x02])
        self.send_msp(message.get_msp())

    def send_announcement(self, str, hardwareType, persistent = False):
        if hardwareType != 'betaflight_craftname':
            self.send_clear_announcement(hardwareType)

        col = self.centerOSD(len(str), hardwareType)
        self.send_msg(self._announcement_row, col, str, hardwareType, persistent)

    def send_status(self, str, hardwareType, clearFullScreen = False, persistent = False):
        if hardwareType != 'betaflight_craftname':
            if clearFullScreen:
                self.send_clear(hardwareType)
            else:
                self.send_clear_status(hardwareType)

        col = self.centerOSD(len(str), hardwareType)
        self.send_msg(self._status_row, col, str, hardwareType, persistent)

    def send_currentlap(self, str, hardwareType, persistent = False):
        if hardwareType != 'betaflight_craftname':
            self.send_clear_currentlap(hardwareType)

        col = self.centerOSD(len(str), hardwareType)
        self.send_msg(self._currentlap_row, col, str, hardwareType, persistent)

    def send_lapresults(self, str, hardwareType, persistent = False):
        if hardwareType != 'betaflight_craftname':
            self.send_clear_lapresults(hardwareType)

        col = self.centerOSD(len(str), hardwareType)
        self.send_msg(self._lapresults_row, col, str, hardwareType, persistent)

    def send_msg(self, row, col, str, hardwaretype, persistent):
        payload = [1]
        if hardwaretype != 'betaflight_craftname':
            payload = [0x03,row,col,0]
            str = str.replace('>>', 'x')
            str = str.replace('<<', 'w')
        elif len(str) > 16:
            str = str.replace('>>', '')
            str = str.replace('<<', '')

        str = str.strip()

        if hardwaretype == 'betaflight_craftname' and len(str) < 16:
            # if the string is shorter than 16 characters, center it by prepending spaces
            spacesToAdd = int((16 - len(str)) / 2)
            str = (' ' * spacesToAdd) + str

        # add every character using the ord() function to payload
        # if hardwareType == betaflight_craftname, then only upto 16 characters can be sent
        for index, char in enumerate(str):
            if hardwaretype == 'betaflight_craftname' and index > 15:
                logger.info("too many characters for betaflight_craftname, breaking into next line")
                break
            payload.append(ord(char))

        message = msp_message()

        if hardwaretype == 'betaflight_craftname':
            message.set_function(msptypes.MSP_ELRS_SET_NAME)
        else:
            message.set_function(msptypes.MSP_ELRS_SET_OSD)

        message.set_payload(payload)
        mspString = message.get_msp()
        self.send_msp(mspString)

        if hardwaretype == 'betaflight_craftname' and len(str) > 16:
            # if the string is longer than 16 characters, make it scroll
            time.sleep(0.4)
            self.send_msg(row, col, str[1:], hardwaretype, False)

        if persistent:
            self._last_persistent_betaflight_craftname_message[self._activePilotIdentifier] = str

    def send_display(self):
        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_SET_OSD)
        message.set_payload([0x04])
        self.send_msp(message.get_msp())
    
    def send_clear_status(self, hardwareType, displayLastPersistentMessage = True):
        self.send_clear_row(self._status_row, hardwareType, displayLastPersistentMessage)

    def send_clear_announcement(self, hardwareType, displayLastPersistentMessage = True):
        self.send_clear_row(self._announcement_row, hardwareType, displayLastPersistentMessage)

    def send_clear_currentlap(self, hardwareType, displayLastPersistentMessage = True):
        self.send_clear_row(self._currentlap_row, hardwareType, displayLastPersistentMessage)

    def send_clear_lapresults(self, hardwareType, displayLastPersistentMessage = True):
        self.send_clear_row(self._lapresults_row, hardwareType, displayLastPersistentMessage)

    def send_clear_row(self, row, hardwaretype, displayLastPersistentMessage = True):
        if hardwaretype == 'betaflight_craftname':
            self.send_clear(hardwaretype, displayLastPersistentMessage)
            return
        
        payload = [0x03,row,0,0]
        for x in range(HARDWARE_SETTINGS[hardwaretype]['row_size']):
            payload.append(0)

        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_SET_OSD)
        message.set_payload(payload)

        self.send_msp(message.get_msp())

    def activate_bind(self, _args):
        message = "Activating backpack's bind mode..."
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))
        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_BACKPACK_SET_MODE)
        message.set_payload([ord('B')])
        with self._queue_lock:
            self.send_msp(message.get_msp())
    
    def activate_wifi(self, _args):
        message = "Turning on backpack's wifi..."
        self._rhapi.ui.message_notify(self._rhapi.language.__(message))
        message = msp_message()
        message.set_function(msptypes.MSP_ELRS_BACKPACK_SET_MODE)
        message.set_payload([ord('W')])
        with self._queue_lock:
            self.send_msp(message.get_msp())

    #
    # Connection Test
    #

    def test_osd(self, _args):

        def test():
            message = 'ROTORHAZARD'
            self._queue_lock.acquire()
            #self.send_clear('betaflight_craftname')
            self.send_msg(0, 0, message, 'betaflight_craftname', False)
            #self.send_display()
            self._queue_lock.release()

            time.sleep(1)

            self._queue_lock.acquire()
            self.send_clear('betaflight_craftname')
            #self.send_display()
            self._queue_lock.release()
        #    for row in range(HARDWARE_SETTINGS['hdzero']['column_size']):

#                self._queue_lock.acquire()
#                self.send_clear('hdzero')
#                start_col = self.centerOSD(len(message), 'hdzero')
#                self.send_msg(row, start_col, message, 'hdzero')    
#                self.send_display()
#                self._queue_lock.release()

#                time.sleep(0.5)

#                self._queue_lock.acquire()
#                self.send_clear_row(row, 'hdzero')
#                self.send_display()
#                self._queue_lock.release()

#            time.sleep(1)
#            self._queue_lock.acquire()
#            self.send_clear('hdzero')
#            self.send_display()
#            self._queue_lock.release()

        Thread(target=test, daemon=True).start()

    #
    # VRxC Event Triggers
    #

    def onPilotAlter(self, args):
        pilot_id = args['pilot_id']
        self._queue_lock.acquire()

        if pilot_id in self._heat_data:
            pilot_settings = {}

            hardware_type = self._rhapi.db.pilot_attribute_value(pilot_id, 'hardware_type')
            logger.info(f"Pilot {pilot_id}'s hardware set to {hardware_type}")
            if hardware_type in HARDWARE_SETTINGS:
                pilot_settings['hardware_type'] = hardware_type
            else:
                self._heat_data[pilot_id] = None
                self._queue_lock.release()
                return

            bindphrase = self._rhapi.db.pilot_attribute_value(pilot_id, 'comm_elrs')
            if bindphrase:
                UID = self.hash_phrase(bindphrase)
                pilot_settings['UID'] = UID
            else:
                UID = self.hash_phrase(self._rhapi.db.pilot_by_id(pilot_id).callsign)
                pilot_settings['UID'] = UID

            self._heat_data[pilot_id] = pilot_settings
            logger.info(f"Pilot {pilot_id}'s UID set to {UID}")

        self._queue_lock.release()

    def onHeatSet(self, args):

        heat_data = {}
        for slot in self._rhapi.db.slots_by_heat(args['heat_id']):
            if slot.pilot_id:
                hardware_type = self._rhapi.db.pilot_attribute_value(slot.pilot_id, 'hardware_type')
                if hardware_type not in HARDWARE_SETTINGS:
                    heat_data[slot.pilot_id] = None
                    continue

                pilot_settings = {}
                pilot_settings['hardware_type'] = hardware_type
                logger.info(f"Pilot {slot.pilot_id}'s hardware set to {self._rhapi.db.pilot_attribute_value(slot.pilot_id, 'hardware_type')}")

                bindphrase = self._rhapi.db.pilot_attribute_value(slot.pilot_id, 'comm_elrs')
                if bindphrase:
                    UID = self.hash_phrase(bindphrase)
                    pilot_settings['UID'] = UID
                else:
                    UID = self.hash_phrase(self._rhapi.db.pilot_by_id(slot.pilot_id).callsign)
                    pilot_settings['UID'] = UID
                
                heat_data[slot.pilot_id] = pilot_settings
                logger.info(f"Pilot {slot.pilot_id}'s UID set to {UID}")
        
        self._heat_data = heat_data

    def onRaceStage(self, args):
        # Set OSD options
        self.setOptions()

        # Setup heat if not done already
        with self._queue_lock:
            self.clear_sendUID()
            self._finished_pilots = []
            if not self._heat_data:
                self.onHeatSet(args)

        heat_data = self._rhapi.db.heat_by_id(args['heat_id'])
        raceclass = None
        if heat_data:
            raceclass = self._rhapi.db.raceclass_by_id(heat_data.class_id)

        if raceclass:
            class_name = raceclass.name
        else:
            class_name = None
        
        heat_name = None
        if heat_data:
            heat_name = heat_data.name


        if heat_data and self._heat_name and class_name and heat_name:
            round_trans = self._rhapi.__('Round')
            round_num = self._rhapi.db.heat_max_round(args['heat_id']) + 1
            if round_num > 1:
                race_name = f'x {class_name.upper()} | {heat_name.upper()} | {round_trans.upper()} {round_num} w'
            else:
                race_name = f'x {class_name.upper()} | {heat_name.upper()} w'

        # Send stage message to all pilots
        def arm(pilot_id):
            hardwareType = self._heat_data[pilot_id]['hardware_type']
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_status(self._racestage_message, hardwareType, True)
            if self._heat_name and class_name and heat_name:
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_announcement(race_name, hardwareType)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id]:
                    Thread(target=arm, args=(pilot_id,), daemon=True).start()

    def onRaceStart(self, _args):
        
        def start(pilot_id):
            hardwareType = self._heat_data[pilot_id]['hardware_type']
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_status(self._racestage_message, hardwareType, True)
            self.send_display()
            self.clear_sendUID()
            delay = copy.copy(self._racestart_uptime)
            self._queue_lock.release()

            time.sleep(delay)

            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_clear_status(hardwareType, False)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id]:
                    thread1 = Thread(target=start, args=(pilot_id,), daemon=True)
                    thread1.start()

    def onRaceFinish(self, _args):
        
        def start(pilot_id):

            hardwareType = self._heat_data[pilot_id]['hardware_type']
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_status(self._racefinish_message, hardwareType)
            self.send_display()
            self.clear_sendUID()
            delay = copy.copy(self._finish_uptime)
            self._queue_lock.release()

            time.sleep(delay)

            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_clear_status(hardwareType)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id] and (pilot_id not in self._finished_pilots):
                    Thread(target=start, args=(pilot_id,), daemon=True).start()

    def onRaceStop(self, _args):
        def land(pilot_id):
            hardwareType = self._heat_data[pilot_id]['hardware_type']
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_status(self._racestop_message, hardwareType)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id] and (pilot_id not in self._finished_pilots):
                    Thread(target=land, args=(pilot_id,), daemon=True).start()

    def onRaceLapRecorded(self, args):

        def update_pos(result):
            pilot_id = result['pilot_id']
            hardwareType = self._heat_data[pilot_id]['hardware_type']

            self._queue_lock.acquire()
            if not self._position_mode or len(self._heat_data) == 1:
                message = f"LAP: {result['laps'] + 1}"
            else:
                message = f"POSN: {str(result['position']).upper()} | LAP: {result['laps'] + 1}"

            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_currentlap(message, hardwareType, True)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        def lap_results(result, gap_info):
            pilot_id = result['pilot_id']

            hardwareType = self._heat_data[pilot_id]['hardware_type']

            self._queue_lock.acquire()
            if not self._gap_mode or len(self._heat_data) == 1:
                formatted_time = RHUtils.time_format(gap_info.current.last_lap_time, '{m}:{s}.{d}')
                message = f">> LAP {gap_info.current.lap_number} | {formatted_time} <<"
            elif gap_info.next_rank.position:
                formatted_time = RHUtils.time_format(gap_info.next_rank.diff_time, '{m}:{s}.{d}')
                formatted_callsign = str.upper(gap_info.next_rank.callsign)
                message = f">> {formatted_callsign} | +{formatted_time} <<"
            else:
                message = self._leader_message
        
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_lapresults(message, hardwareType)
            self.send_display()
            self.clear_sendUID()
            delay = copy.copy(self._results_uptime)
            self._queue_lock.release()

            time.sleep(delay)

            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_clear_lapresults(hardwareType)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()


        self._queue_lock.acquire()
        if self._heat_data == {}:
            return

        if args['pilot_done_flag']:
            self._finished_pilots.append(args['pilot_id'])

        results = args['results']['by_race_time']
        for result in results:
            if self._heat_data[result['pilot_id']]:
                
                if result['pilot_id'] not in self._finished_pilots:
                    Thread(target=update_pos, args=(result,), daemon=True).start()

                if (result['pilot_id'] == args['pilot_id']) and (result['laps'] > 0):
                    Thread(target=lap_results, args=(result, args['gap_info']), daemon=True).start()
        
        self._queue_lock.release()
    
    def onLapDelete(self, _args):
        
        def delete(pilot_id):
            self._queue_lock.acquire()
            if self._heat_data[pilot_id]:
                self.set_sendUID(self._heat_data[pilot_id]['UID'])
                self.send_clear(self._heat_data[pilot_id]['hardware_type'], False)
                self.send_display()
                self.clear_sendUID()
            self._queue_lock.release()
        
        with self._queue_lock:
            if self._results_mode:
                for pilot_id in self._heat_data:
                    Thread(target=delete, args=(pilot_id,), daemon=True).start()
            

    def onRacePilotDone(self, args):

        def done(result):

            self._queue_lock.acquire()
            pilot_id = result['pilot_id']
            hardwareType = self._heat_data[pilot_id]['hardware_type']
        
            self.set_sendUID(self._heat_data[result['pilot_id']]['UID'])
            if hardwareType != 'betaflight_craftname':
                self.send_clear_currentlap(hardwareType)
            
            self.send_status(self._pilotdone_message, hardwareType)

            if self._results_mode:
                self.send_msg(10, 11, "PLACEMENT:", hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(10, 30, str(result['position']), hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(11, 11, "LAPS COMPLETED:", hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(11, 30, str(result['laps']), hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(12, 11, "FASTEST LAP:", hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(12, 30, result['fastest_lap'], hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(13, 11, "FASTEST " + str(result['consecutives_base']) +  " CONSEC:", hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(13, 30, result['consecutives'], hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(14, 11, "TOTAL TIME:", hardwareType, False)
                if hardwareType == 'betaflight_craftname':
                    time.sleep(1)
                self.send_msg(14, 30, result['total_time'], hardwareType, False)
            
            self.send_display()
            self.clear_sendUID()
            delay = copy.copy(self._finish_uptime)
            self._queue_lock.release()

            time.sleep(delay)

            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_clear_status(hardwareType, False)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        results = args['results']['by_race_time']
        with self._queue_lock:
            for result in results:
                if (self._heat_data[args['pilot_id']]) and (result['pilot_id'] == args['pilot_id']):
                    Thread(target=done, args=(result,), daemon=True).start()
                    break

    def onLapsClear(self, _args):
        
        def clear(pilot_id):
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot_id]['UID'])
            self.send_clear(self._heat_data[pilot_id]['hardware_type'], False)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            self._finished_pilots = []
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id]:
                    Thread(target=clear, args=(pilot_id,), daemon=True).start()

    def onSendMessage(self, args):
        
        def notify(pilot):

            hardwareType = self._heat_data[pilot]['hardware_type']
            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot]['UID'])
            self.send_announcement(args['message'], hardwareType)
            self.send_display()
            self.clear_sendUID()
            delay = copy.copy(self._announcement_uptime)
            self._queue_lock.release()

            time.sleep(delay)

            self._queue_lock.acquire()
            self.set_sendUID(self._heat_data[pilot]['UID'])
            self.send_clear_announcement(hardwareType)
            self.send_display()
            self.clear_sendUID()
            self._queue_lock.release()

        with self._queue_lock:
            for pilot_id in self._heat_data:
                if self._heat_data[pilot_id]:
                    Thread(target=notify, args=(pilot_id,), daemon=True).start()