#!/usr/bin/env python3

import asyncio
from mavsdk import System

class DroneConnection:
    def __init__(self, sys_address="udpin://0.0.0.0:14540"):
        self.sys_address = sys_address
        self.drone = System()
    
    async def connect(self):
        await self.drone.connect(system_address=self.sys_address)

        status_text_task = asyncio.ensure_future(self.print_status_text(self.drone))
        print("Waiting for drone to connect...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print(f"-- Connected to drone!")
                break
        
        print("Waiting for drone to have a global position estimate...")
        async for health in self.drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Global position estimate OK")
                break

    async def print_status_text(self, drone):
        try:
            async for status_text in drone.telemetry.status_text():
                print(f"Status: {status_text.type}: {status_text.text}")
        except asyncio.CancelledError:
            return

            

async def run(sys_address = "udpin://0.0.0.0:14540"):
    drone_connection = DroneConnection(sys_address)
    await drone_connection.connect()

if __name__ == "__main__":
    asyncio.run(run())