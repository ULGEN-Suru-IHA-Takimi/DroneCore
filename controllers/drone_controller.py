#!/usr/bin/env python3
import asyncio
from mavsdk import System
import os
import sys
from typing import List, Dict, Any, TypedDict, Tuple
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from connect.drone_connection import DroneConnection

# Waypoint tuple formatı: (lat, lon, alt, heading)
WaypointTuple = Tuple[float, float, float, float]

class Waypoint(TypedDict):
    lat: float
    lon: float
    alt: float
    speed: float

class DroneController(DroneConnection):
    def __init__(self, sys_address="udpin://0.0.0.0:14540"):
        super().__init__(sys_address=sys_address)
        self.waypoints: List[WaypointTuple] = []

    def set_waypoints(self, waypoints: List[WaypointTuple] = [
        (47.397606, 8.543060, 10, 0),    # Waypoint 1
        (47.398106, 8.543560, 10, 90),   # Waypoint 2 (500m north-east)
        (47.397106, 8.544060, 10, 180),  # Waypoint 3 (500m south-east)
    ]) -> None:
        """
        Set waypoints for the drone mission
        Format: [(lat, lon, alt, heading), ...]
        Example: [(47.397606, 8.543060, 20.0, 0), (47.398106, 8.543560, 20.0, 90)]
        """
        self.waypoints = waypoints

    async def takeoff(self):
        print("-- Arming")
        await self.drone.action.arm()
        print("-- Taking off")
        await self.drone.action.takeoff()
        await asyncio.sleep(2)  # Extra time to stabilize

    async def waypoint_mission(self):
        for i, (lat, lon, alt, yaw) in enumerate(self.waypoints, 1):
            print(f"-- Going to waypoint {i}: ({lat}, {lon})")
            await self.drone.action.goto_location(lat, lon, alt, yaw)
            await asyncio.sleep(2)
        
            # Wait until we reach the waypoint (check position)
            print(f"-- Flying to waypoint {i}...")
            target_reached = False
            while not target_reached:
                async for position in self.drone.telemetry.position():
                    # Calculate distance to target (simple approximation)
                    lat_diff = abs(position.latitude_deg - lat)
                    lon_diff = abs(position.longitude_deg - lon)
                    
                    # If we're close enough (within ~10 meters)
                    if lat_diff < 0.0001 and lon_diff < 0.0001:
                        print(f"-- Reached waypoint {i}")
                        target_reached = True
                        break
                
                if not target_reached:
                    await asyncio.sleep(1)  # Check position every second
    
    async def run_mission(self):
        await self.connect()  # Önce bağlan
        await self.takeoff()  # Sonra kalk
        await self.waypoint_mission()
        
        # Mission bitince land
        print("-- Landing")
        await self.drone.action.land()


async def run(sys_address="udpin://0.0.0.0:14540"):
    drone_controller = DroneController(sys_address=sys_address)
    await drone_controller.connect()
    await drone_controller.run_mission()

if __name__ == "__main__":
    asyncio.run(run())