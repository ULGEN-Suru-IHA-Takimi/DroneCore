import asyncio
import pathlib
import tkinter as tk
import tkinter.ttk as ttk
import pygubu
import time
import os
import sys
PROJECT_PATH = pathlib.Path(__file__).parent
PROJECT_UI = PROJECT_PATH / "ground_control.ui"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controllers.waypoint_controller import *
from controllers.xbee_controller import *


class Drone:
    def __init__(self):
        pass

class GroundControlApp:
    def __init__(self, master=None):


        
        self.waypoint = waypoints()
        self.drone_id = "0"

        self.builder = builder = pygubu.Builder()
        builder.add_resource_path(PROJECT_PATH)
        builder.add_from_file(PROJECT_UI)

        self.mainwindow = builder.get_object('main_window', master)
        builder.connect_callbacks(self)
        self.port_dialog = builder.get_object('port_dialog', self.mainwindow)
        self.port_dialog.run()


        self.xbee = XBeeModule(port=self.port, baudrate=DEFAULT_BAUD_RATE) 
        self.BROADCAST_ADDR = "000000000000FFFF"
        self.is_xbee_connected = False

    async def xbee_connect(self):
        """XBee bağlantısını kurar."""
        # xbee.connect() senkron bir metot olduğundan, bunu doğrudan çağırıyoruz.
        # Eğer bu işlem uzun sürerse, `loop.run_in_executor` ile ayrı bir thread'de çalıştırılabilir.
        # Şimdilik, genellikle bağlantı hızlı olduğu için doğrudan çağrı yeterli.
        self.is_xbee_connected = self.xbee.connect()
        if self.is_xbee_connected:
            print(f"DroneController {self.drone_id}: XBee bağlantısı başarılı.")
        else:
            print(f"DroneController {self.drone_id}: XBee bağlantısı kurulamadı.")
        return self.is_xbee_connected

    def xbee_disconnect(self):
        """XBee bağlantısını keser."""
        self.xbee.disconnect()
        self.is_xbee_connected = False
        print(f"DroneController {self.drone_id}: XBee bağlantısı kesildi.")


if __name__ == "__main__":
    app = GroundControlApp()