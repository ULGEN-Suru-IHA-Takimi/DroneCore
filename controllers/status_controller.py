#!/usr/bin/env python3
import asyncio
from mavsdk import System
import os
import sys
from typing import List, Dict, Any, TypedDict, Tuple
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class StatusController:
    def __init__(self, sys_address: str = "udpin://0.0.0.0:14540", drone: System = None):
        self.sys_address = sys_address
        self.drone = drone if drone else print("No drone instance provided, creating a new one.")

    async def print_gps_info(self) -> None:
        async for gps_info in self.drone.telemetry.gps_info():
            print(f"GPS Info: {gps_info}")

    async def print_battery_info(self) -> None:
        async for battery_info in self.drone.telemetry.battery():
            print(f"Battery Info: {battery_info}")
    
    async def print_position(self) -> None:
        async for position in self.drone.telemetry.position():
            print(f"Position: {position.latitude_deg}, {position.longitude_deg}, {position.absolute_altitude_m}")
    
    async def print_health(self) -> None:
        async for health in self.drone.telemetry.health():
            print(f"Health: {health}")
    
    async def print_status_text(self) -> None:
        try:
            async for status_text in self.drone.telemetry.status_text():
                print(f"Status: {status_text.type}: {status_text.text}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Status text error (this is normal): {e}")
            pass

    async def monitor_status(self, ):
        await self.connect()
        async for status in self.drone.telemetry.status_text():
            print(f"Status: {status.type}: {status.text}")

if __name__ == "__main__":
    status_controller = StatusController()
    asyncio.run(status_controller.monitor_status())