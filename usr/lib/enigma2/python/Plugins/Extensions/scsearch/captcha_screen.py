# -*- coding: utf-8 -*-

import urllib.request
import tempfile
import os
from enigma import ePicLoad
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from .logger import get_logger
from . import _  # translation function

log = get_logger()


class CaptchaScreen(Screen):
    """
    Screen for displaying a CAPTCHA image and opening a virtual keyboard
    to enter the code.
    """
    skin = '''
        <screen name="CaptchaScreen" position="center,center" size="800,600" title="Enter Captcha">
            <widget name="title" position="20,20" size="760,40" font="Regular;24" foregroundColor="#ffffff" halign="center" />
            <widget name="captcha_image" position="200,80" size="400,200" zPosition="3" alphatest="on" />
            <widget name="code_label" position="20,300" size="760,30" font="Regular;20" foregroundColor="#ffffff" halign="center" />
            <widget name="instructions" position="20,340" size="760,60" font="Regular;16" foregroundColor="#cccccc" halign="center" />
            <widget name="key_green" position="150,500" size="100,40" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#00ff00" />
            <widget name="key_red" position="550,500" size="100,40" font="Regular;18" halign="center" valign="center" foregroundColor="#ffffff" backgroundColor="#ff0000" />
        </screen>'''

    def __init__(self, session, captcha_url, callback):
        Screen.__init__(self, session)
        self.session = session
        self.captcha_url = captcha_url
        self.callback = callback
        self.captcha_code = ""
        self.temp_image_path = "/tmp/captcha.jpg"

        log.info(
            f"CAPTCHA: Initializing screen with URL: {captcha_url[:100]}...")

        self["title"] = Label(_("Enter Captcha Code"))
        self["captcha_image"] = Pixmap()
        self["code_label"] = Label(_("Code: "))
        self["instructions"] = Label(
            _("Press GREEN to enter the code\nPress RED to cancel"))
        self["key_green"] = Label(_("ENTER"))
        self["key_red"] = Label(_("CANCEL"))

        self["actions"] = ActionMap(["ColorActions", "OkCancelActions"], {
            "green": self.open_keyboard,
            "red": self.cancel,
            "cancel": self.cancel,
            "ok": self.open_keyboard
        }, -2)

        self.picload = ePicLoad()
        self.picload.PictureData.get().append(self.decode_finished)

        self.onLayoutFinish.append(self.load_captcha_image)

    def load_captcha_image(self):
        """Download or decode the CAPTCHA image and display it."""
        try:
            log.info(
                f"CAPTCHA: Loading image from {self.captcha_url[:100]}...")

            if self.captcha_url.startswith('data:image/'):
                # Handle base64 encoded image
                log.info("CAPTCHA: Processing base64 image")
                import base64

                # Extract base64 data and decode
                header, data = self.captcha_url.split(',', 1)
                image_data = base64.b64decode(data)

                with open(self.temp_image_path, 'wb') as f:
                    f.write(image_data)
            else:
                # Handle normal URL
                log.info("CAPTCHA: Downloading image from URL")
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

                req = urllib.request.Request(self.captcha_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    with open(self.temp_image_path, 'wb') as f:
                        f.write(response.read())

            # Load the image
            self.picload.setPara((400, 200, 1, 1, False, 1, "#00000000"))
            self.picload.startDecode(self.temp_image_path)

        except Exception as e:
            log.error(f"CAPTCHA: Error loading image: {e}")
            self["code_label"].setText(_("Error loading captcha"))

    def decode_finished(self, picInfo=None):
        """Called when image decoding is finished; display the pixmap."""
        try:
            ptr = self.picload.getData()
            if ptr is not None:
                self["captcha_image"].instance.setPixmap(ptr)
        except Exception as e:
            log.error(f"CAPTCHA: Error displaying image: {e}")

    def open_keyboard(self):
        """Open the virtual keyboard to enter the captcha code."""
        self.session.openWithCallback(
            self.keyboard_callback,
            VirtualKeyBoard,
            title=_("Enter captcha code:"),
            text=self.captcha_code
        )

    def keyboard_callback(self, result):
        """Handle result from virtual keyboard."""
        if result:
            self.captcha_code = result
            self["code_label"].setText(_(f"Code: {self.captcha_code}"))
            self.submit_captcha()

    def submit_captcha(self):
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
