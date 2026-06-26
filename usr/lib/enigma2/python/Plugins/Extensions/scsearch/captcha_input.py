# -*- coding: utf-8 -*-

import base64
import os
from enigma import ePicLoad
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from .logger import get_logger
from . import _, load_skin

log = get_logger()


class CaptchaInputScreen(Screen):
    """
    Screen for entering a CAPTCHA code using numeric remote keys.
    Displays the captcha image and allows digit-by-digit entry.
    """
    # skin = '''
    # <screen name="CaptchaInputScreen" position="center,center" size="800,600" title="Enter Captcha">
    # <widget name="title" position="20,20" size="760,40" font="Regular;24" foregroundColor="#ffffff" halign="center" />
    # <widget name="captcha_image" position="200,80" size="400,200" zPosition="3" alphatest="on" />
    # <widget name="code_display" position="20,300" size="760,60" font="Regular;32" foregroundColor="#00ff00" halign="center" />
    # <widget name="instructions" position="20,380" size="760,80" font="Regular;18" foregroundColor="#cccccc" halign="center" />
    # <widget name="key_green" position="150,500" size="100,40" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#00ff00" />
    # <widget name="key_red" position="550,500" size="100,40" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#ff0000" />
    # </screen>'''

    def __init__(self, session, captcha_data, callback):

        skin_data = load_skin("CaptchaInputScreen")
        if skin_data:
            self.skin = skin_data

        Screen.__init__(self, session)
        self.captcha_data = captcha_data
        self.callback = callback
        self.captcha_code = ""
        self.temp_image_path = "/tmp/captcha.jpg"

        self["title"] = Label(_("Enter Captcha Code"))
        self["captcha_image"] = Pixmap()
        self["code_display"] = Label(_("Code: "))
        self["instructions"] = Label(
            _("Use the numeric keys on the remote\nto enter the captcha code\nGREEN = Confirm, RED = Cancel"))
        self["key_green"] = Label(_("CONFIRM"))
        self["key_red"] = Label(_("CANCEL"))

        self["actions"] = ActionMap(["NumberActions", "ColorActions", "OkCancelActions"], {
            "1": self.number_1,
            "2": self.number_2,
            "3": self.number_3,
            "4": self.number_4,
            "5": self.number_5,
            "6": self.number_6,
            "7": self.number_7,
            "8": self.number_8,
            "9": self.number_9,
            "0": self.number_0,
            "green": self.confirm,
            "red": self.cancel,
            "ok": self.confirm,
            "cancel": self.cancel
        }, -2)

        self.picload = ePicLoad()
        self.picload.PictureData.get().append(self.decode_finished)

        self.onLayoutFinish.append(self.load_captcha_image)

    def load_captcha_image(self):
        """Load and display the CAPTCHA image from base64 data."""
        try:
            log.info("CAPTCHA: Loading captcha image")

            # Extract base64 data and decode
            header, data = self.captcha_data.split(',', 1)
            image_data = base64.b64decode(data)

            with open(self.temp_image_path, 'wb') as f:
                f.write(image_data)

            # Load the image
            self.picload.setPara((400, 200, 1, 1, False, 1, "#00000000"))
            self.picload.startDecode(self.temp_image_path)

        except Exception as e:
            log.error(f"CAPTCHA: Error loading image: {e}")

    def decode_finished(self, picInfo=None):
        """Called when image decoding is finished; display the pixmap."""
        try:
            ptr = self.picload.getData()
            if ptr is not None:
                self["captcha_image"].instance.setPixmap(ptr)
        except Exception as e:
            log.error(f"CAPTCHA: Error displaying image: {e}")

    # Numeric key handlers
    def number_0(self):
        self.add_digit("0")

    def number_1(self):
        self.add_digit("1")

    def number_2(self):
        self.add_digit("2")

    def number_3(self):
        self.add_digit("3")

    def number_4(self):
        self.add_digit("4")

    def number_5(self):
        self.add_digit("5")

    def number_6(self):
        self.add_digit("6")

    def number_7(self):
        self.add_digit("7")

    def number_8(self):
        self.add_digit("8")

    def number_9(self):
        self.add_digit("9")

    def add_digit(self, digit):
        """Append a digit to the captcha code (max 6 digits)."""
        if len(self.captcha_code) < 6:
            self.captcha_code += digit
            self["code_display"].setText(_(f"Code: {self.captcha_code}"))

    def confirm(self):
        """Confirm the entered captcha code and call the callback."""
        if self.captcha_code:
            log.info(f"CAPTCHA: Code confirmed: {self.captcha_code}")
            self.cleanup()
            if self.callback:
                log.info(
                    "CAPTCHA: Calling callback with code: {}".format(
                        self.captcha_code))
                self.callback(self.captcha_code)
            self.close()
        else:
            log.warning("CAPTCHA: No code entered, cannot confirm")

    def cancel(self):
        """Cancel captcha entry and call callback with None."""
        log.info("CAPTCHA: Cancelled by user")
        callback_func = self.callback
        self.cleanup()
        self.close()
        if callback_func:
            log.info("CAPTCHA: Calling callback with None (cancelled)")
            callback_func(None)

    def cleanup(self):
        """Remove temporary image file."""
        try:
            if os.path.exists(self.temp_image_path):
                os.remove(self.temp_image_path)
        except Exception:
            pass
