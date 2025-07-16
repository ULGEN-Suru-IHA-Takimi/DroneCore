#!/usr/bin/env python3

import serial
import time
import threading
import json

class XBeePackage:
    '''
    XBee üzerinden gelecek paket tanımlaması
    '''
    def __init__(self, package_type: str = "HANDSHAKE",
                 sender: str = None,
                 send_time: str = None,
                 param1: str = None,
                 param2: str = None,
                 param3: str = None):
        self.package_type = package_type
        self.sender = sender
        self.send_time = send_time
        match self.package_type:
            case "HANDSHAKE":
                pass
            case _:
                if param1 or param2 or param3:
                    self.param = [param1, param2, param3]
    
    def __str__(self):
        match self.package_type:
            case "HANDSHAKE":
                return [1, self.sender, self.send_time]
            case _:
                return [0, self.sender, self.send_time, self.param]

class XBeeModule:
    def __init__(self,):
        pass



if __name__ == '__main__':
    input_user = str(input('port gir'))
    print(f'port: {input_user}')