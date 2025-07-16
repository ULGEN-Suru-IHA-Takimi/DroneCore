#!/usr/bin/env python3
import asyncio
from email.mime import message
from mavsdk import System
import os
import sys
from typing import List, Dict, Any, TypedDict, Tuple
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from connect.drone_connection import DroneConnection
from xbee_controller import *
# Waypoint tuple formatı: (lat, lon, alt, heading)
WaypointTuple = Tuple[float, float, float, float]

class Waypoint(TypedDict):
    lat: float
    lon: float
    alt: float
    speed: float

class DroneController(DroneConnection):
    def __init__(self, sys_address="udpin://0.0.0.0:14540", xbee_port="/dev/ttyUSB0", xbee_baud_rate=57600):
        super().__init__(sys_address=sys_address)
        self.waypoints: List[WaypointTuple] = []
        self.flying_alt: float = 0.0
        self.xbee_module = XBeeModule(port=xbee_port, baudrate=xbee_baud_rate)
        
        self.BROADCAST_64BIT_ADDR = "000000000000FFFF"  # XBee broadcast address

    def set_waypoints(self, waypoints: List[WaypointTuple] = [
        (47.397606, 8.543060, 20.0, 0),    # Waypoint 1  
        (47.398106, 8.543560, 20.0, 90),   # Waypoint 2 (500m north-east)
        (47.397106, 8.544060, 20.0, 180),  # Waypoint 3 (500m south-east)
    ]) -> None:
        """
        Set waypoints for the drone mission
        Format: [(lat, lon, alt, heading), ...]
        Example: [(47.397606, 8.543060, 20.0, 0), (47.398106, 8.543560, 20.0, 90)]
        """
        self.waypoints = waypoints

    async def get_flying_altitude(self) -> float:
        """Get absolute altitude for flying (home + offset)"""
        print("Fetching amsl altitude at home location....")
        async for terrain_info in self.drone.telemetry.home():
            absolute_altitude = terrain_info.absolute_altitude_m
            break
        
        # Fly 20m above the ground plane
        self.flying_alt = absolute_altitude + 20.0
        print(f"-- Flying altitude set to: {self.flying_alt}m")
        return self.flying_alt

    async def arm_and_takeoff(self) -> None:
        """Arm drone and takeoff"""
        print("-- Arming")
        await self.drone.action.arm()

        print("-- Taking off")
        await self.drone.action.takeoff()

        # Wait until drone reaches takeoff altitude
        print("-- Waiting for drone to reach flying altitude...")
        while True:
            async for position in self.drone.telemetry.position():
                if position.relative_altitude_m >= 10.0:  # Wait until at least 10m high
                    print("-- Drone reached flying altitude, ready for waypoint mission")
                    break
            break
        
        await asyncio.sleep(2)  # Extra time to stabilize

    async def waypoint_mission(self) -> None:
        self.xbee_module.connect()
        """Execute waypoint mission"""
        # Update waypoint altitudes to use calculated flying altitude
        updated_waypoints = []
        for lat, lon, _, yaw in self.waypoints:
            updated_waypoints.append((lat, lon, self.flying_alt, yaw))
        self.waypoints = updated_waypoints
        
        # Visit each waypoint
        for i, (lat, lon, alt, yaw) in enumerate(self.waypoints, 1):
            print(f"-- Going to waypoint {i}: ({lat}, {lon}) at {alt}m")
            await self.drone.action.goto_location(lat, lon, alt, yaw)
            
            # Give drone time to start moving
            await asyncio.sleep(2)
            
            # Wait until we reach the waypoint
            print(f"-- Flying to waypoint {i}...")
            target_reached = False
            while not target_reached:
                async for position in self.drone.telemetry.position():
                    # Calculate distance to target (simple approximation)
                    
                    gps_package = XBeePackage(
                        package_type="G",
                        sender="1",
                        params={
                            "x": int(lat * 10000),
                            "y": int(lon * 10000),
                            "z": int(alt * 10)
                        }
                    )
                    self.xbee_module.send_package(gps_package, remote_xbee_addr_hex= self.BROADCAST_64BIT_ADDR)
                    lat_diff = abs(position.latitude_deg - lat)
                    lon_diff = abs(position.longitude_deg - lon)
                    
                    
                    # If we're close enough (within ~10 meters)
                    if lat_diff < 0.0001 and lon_diff < 0.0001:
                        print(f"-- Reached waypoint {i}")
                        target_reached = True
                        break
                
                if not target_reached:
                    await asyncio.sleep(1)  # Check position every second
            
            # Hold/loiter for 10 seconds at this waypoint
            print(f"-- Entering hold mode at waypoint {i} for 10 seconds...")
            await self.drone.action.hold()
            await asyncio.sleep(10)
            print(f"-- Finished loitering at waypoint {i}")
        
        print("-- All waypoints completed!")

    async def land(self) -> None:
        """Land the drone"""
        print("-- Landing")
        await self.drone.action.land()
        
        # Wait for landing to complete
        async for armed in self.drone.telemetry.armed():
            if not armed:
                print("-- Drone landed and disarmed")
                break
    
    async def run_mission(self) -> None:
        """Run complete mission: connect, takeoff, waypoints, land"""
        await self.connect()
        await self.get_flying_altitude()
        await self.arm_and_takeoff()
        await self.waypoint_mission()
        await self.land()


async def run(sys_address="udpin://0.0.0.0:14540"):
    drone_controller = DroneController(sys_address=sys_address)
    
    # Waypoint'leri set et - istersen burada custom waypoint'ler kullanabilirsin
    custom_waypoints = [
        (47.397606, 8.543060, 20.0, 0),    # Waypoint 1
        (47.398106, 8.543560, 20.0, 90),   # Waypoint 2 (500m north-east)
        (47.397106, 8.544060, 20.0, 180),  # Waypoint 3 (500m south-east)
    ]
    
    # Default waypoint'leri kullan veya custom waypoint'leri set et
    drone_controller.set_waypoints(custom_waypoints)  # Custom waypoints
    # drone_controller.set_waypoints()  # Default waypoints için bu satırı kullan
    
    print(f"Mission will visit {len(drone_controller.waypoints)} waypoints")
    
    try:
        await drone_controller.run_mission()
        
        # Keep connection alive
        print("Mission completed! Staying connected, press Ctrl-C to exit")
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("-- Mission interrupted by user")
    except Exception as e:
        print(f"-- Mission failed: {e}")

if __name__ == "__main__":
    asyncio.run(run())