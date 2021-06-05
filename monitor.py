"""
Monitoring program for hikvision api.
"""

import time
import logging
import pyhik.hikvision as hikvision
import requests
from datetime import datetime
from datetime import timedelta
import smtplib
from os.path import basename
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
import yaml
import json

logging.basicConfig(filename='out.log', filemode='w', level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')


class HikCamObject(object):
    """Representation of HIk camera."""

    def __init__(self, url, port, user, passw, callback_url='localhost'):
        """initalize camera"""

        # Establish camera
        self.cam = hikvision.HikCamera(url, port, user, passw)

        self.callback_url = callback_url

        self._name = self.cam.get_name
        self.motion = self.cam.current_motion_detection_state

        # Start event stream
        self.cam.start_stream()

        self._event_states = self.cam.current_event_states
        self._id = self.cam.get_id

        print('NAME: {}'.format(self._name))
        print('ID: {}'.format(self._id))
        print('{}'.format(self._event_states))
        print('Motion Dectect State: {}'.format(self.motion))

    @property
    def sensors(self):
        """Return list of available sensors and their states."""
        return self.cam.current_event_states

    @property
    def name(self):
        """Return the name of the camera."""
        return self._name

    def get_attributes(self, sensor, channel):
        """Return attribute list for sensor/channel."""
        return self.cam.fetch_attributes(sensor, channel)

    def stop_hik(self):
        """Shutdown Hikvision subscriptions and subscription thread on exit."""
        self.cam.disconnect()

    def flip_motion(self, value):
        """Toggle motion detection"""
        if value:
            self.cam.enable_motion_detection()
        else:
            self.cam.disable_motion_detection()

    def get_picture(self):
        return self.cam.get_picture()


class HikSensor(object):
    """ Hik camera sensor."""

    def __init__(self, sensor, channel, cam, email_info):
        """Init"""
        self._cam = cam
        self._name = "{} {} {}".format(self._cam.cam.name, sensor, channel)
        self._id = "{}.{}.{}".format(self._cam.cam.cam_id, sensor, channel)
        self._sensor = sensor
        self._channel = channel
        self._email_info = email_info

        self._sensor_last_trigger = datetime.now() - timedelta(seconds=60)

        # print('NAME: {}'.format(self._name))
        # print('ID: {}'.format(self._id))
        # print('Sensor: {}'.format(self._sensor))
        # print('Channel: {}'.format(self._channel))

        self._cam.cam.add_update_callback(self.update_callback, self._id)

    def _sensor_state(self):
        """Extract sensor state."""
        return self._cam.get_attributes(self._sensor, self._channel)[0]

    def _sensor_last_update(self):
        """Extract sensor last update time."""
        return self._cam.get_attributes(self._sensor, self._channel)[3]

    def _sensor_last_trigger(self):
        """The last time the sensor was triggered."""
        return self._sensor_last_trigger

    @property
    def name(self):
        """Return the name of the Hikvision sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return an unique ID."""
        return '{}.{}'.format(self.__class__, self._id)

    @property
    def is_on(self):
        """Return true if sensor is on."""
        return self._sensor_state()

    def update_callback(self, msg):
        """ get updates. """
        print('Callback: {}'.format(msg))
        print('{}:{} @ {}'.format(self._cam.name, self._sensor_state(), self._sensor_last_update()))
        if self._sensor_state() and self._cam.callback_url:
            currTime = self._sensor_last_update()
            if self._sensor_last_trigger:
                difference = currTime - self._sensor_last_trigger
                if difference.total_seconds() > 60:
                    print("Updating last trigger time")
                    self._sensor_last_trigger = currTime
                    print("Sending email.")
                    self.send_mail()
                    # print("Would send an email now.")
                else:
                    print("Would not send an email now.")
            else:
                print("Last trigger time was blank! Updating now...")
                self._sensor_last_trigger = currTime

            print('Sending get request to {}'.format(self._cam.callback_url))
            r = requests.get(self._cam.callback_url)
            print(r.status_code)

    def send_mail(self):
        send_from = self._email_info["send_from"]
        send_to = self._email_info["send_to"]
        server = self._email_info["server"]
        user = self._email_info["user"]
        password = self._email_info["password"]
        triggerTime = self._sensor_last_trigger.strftime("%H:%M:%S")
        fFtiggerTime = self._sensor_last_trigger.strftime("%H-%M-%S")

        msg = MIMEMultipart()
        msg['From'] = send_from
        msg['To'] = COMMASPACE.join(send_to)
        msg['Date'] = formatdate(localtime=True)
        msg['Subject'] = "Motion detected at %s" % self._name

        msg.attach(MIMEText("Motion detected at %s at %s." % (self._name, triggerTime)))

        image = self._cam.get_picture()

        part = MIMEApplication(
            image.content,
            Name="%s.jpg" % fFtiggerTime
        )

        part['Content-Disposition'] = 'attachment; filename="%s.jpg"' % fFtiggerTime
        msg.attach(part)

        smtp = smtplib.SMTP(server, 587)
        smtp.starttls()
        smtp.login(user, password)
        r = smtp.sendmail(send_from, send_to, msg.as_string())
        print(r)
        smtp.close()

def main():
    """Main function"""

    with open('config.yaml', 'rb') as configfile:
        config = yaml.safe_load(configfile)

    print(json.dumps(config, indent=2))

    PORT = config["ipCameras"]["port"]
    USER = config["ipCameras"]["user"]
    PASSWORD = config["ipCameras"]["password"]
    cameras = []
    email_info = {
    "server" : config["smtp"]["server"],
    "user" : config["smtp"]["user"],
    "password" : config["smtp"]["password"],
    "send_to" : config["smtp"]["recipients"],
    "send_from" : config["smtp"]["user"],
    }

    NAS_IP = '%s:%s' % (config["nas"]["ip"], config["nas"]["port"])
    SURVEILLANCE_STATION_URL = 'http://%s%s' % (NAS_IP, config["nas"]["surveillanceStationPath"])



    back_door = HikCamObject('http://%s' % config["ipCameras"]["cameras"]["back_door"]["ip"], PORT, USER, PASSWORD, SURVEILLANCE_STATION_URL + "back_door")
    cameras.append(back_door)
    driveway = HikCamObject('http://%s' % config["ipCameras"]["cameras"]["driveway"]["ip"], PORT, USER, PASSWORD, SURVEILLANCE_STATION_URL + "driveway")
    cameras.append(driveway)
    patio = HikCamObject('http://%s' % config["ipCameras"]["cameras"]["patio"]["ip"], PORT, USER, PASSWORD, SURVEILLANCE_STATION_URL + "patio")
    cameras.append(patio)

    entities = []

    for camera in cameras:
        for sensor, channel_list in camera.sensors.items():
            for channel in channel_list:
                entities.append(HikSensor(sensor, channel[1], camera, email_info))

main()
