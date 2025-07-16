#!/usr/bin/env python3

import serial
import time
import threading
import json
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass


@dataclass
class XBeeMessage:
    """Data class for XBee messages."""
    sender: str
    receiver: str
    message_type: str
    payload: Dict[str, Any]
    timestamp: float


class XBeeModule:
    """
    A class to handle XBee communication for drone systems.
    Provides methods for sending/receiving data and managing connections.
    """
    
    def __init__(self, port: str = "/dev/tty19", baudrate: int = 57600, timeout: float = 1.0):
        """
        Initialize the XBee module.
        
        Args:
            port: Serial port for XBee module
            baudrate: Communication speed (default 57600)
            timeout: Serial timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection: Optional[serial.Serial] = None
        self.is_connected = False
        self.is_listening = False
        
        # Message handling
        self.message_callbacks: Dict[str, Callable] = {}
        self.received_messages = []
        self.listen_thread: Optional[threading.Thread] = None
        
        # Node identification
        self.node_id = "DRONE_01"  # Default node ID
        
    def connect(self) -> bool:
        """
        Connect to the XBee module.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS
            )
            
            # Wait for connection to stabilize
            time.sleep(2)
            
            if self.serial_connection.is_open:
                self.is_connected = True
                print(f"-- XBee connected on {self.port} at {self.baudrate} baud")
                return True
            else:
                print(f"-- Failed to open XBee port {self.port}")
                return False
                
        except serial.SerialException as e:
            print(f"-- XBee connection error: {e}")
            return False
            
    def disconnect(self) -> None:
        """Disconnect from the XBee module."""
        self.stop_listening()
        
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.is_connected = False
            print("-- XBee disconnected")
            
    def set_node_id(self, node_id: str) -> None:
        """Set the node ID for this XBee module."""
        self.node_id = node_id
        print(f"-- Node ID set to: {node_id}")
        
    def send_message(self, receiver: str, message_type: str, payload: Dict[str, Any]) -> bool:
        """
        Send a message via XBee.
        """
        if not self.is_connected or not self.serial_connection:
            print("-- XBee not connected")
            return False
            
        try:
            message = XBeeMessage(
                sender=self.node_id,
                receiver=receiver,
                message_type=message_type,
                payload=payload,
                timestamp=time.time()
            )
            
            # Convert to JSON
            json_message = json.dumps({
                'sender': message.sender,
                'receiver': message.receiver,
                'type': message.message_type,
                'payload': message.payload,
                'timestamp': message.timestamp
            })
            
            # Encode as hex to avoid binary data issues
            hex_message = json_message.encode('utf-8').hex()
            formatted_message = f"<HEX>{hex_message}<END>\n"
            
            self.serial_connection.write(formatted_message.encode('ascii'))
            print(f"-- Sent to {receiver}: {message_type}")
            return True
            
        except Exception as e:
            print(f"-- Error sending message: {e}")
            return False
            
    def send_telemetry(self, receiver: str, telemetry_data: Dict[str, Any]) -> bool:
        """
        Send telemetry data.
        
        Args:
            receiver: Target node ID
            telemetry_data: Telemetry information
            
        Returns:
            bool: True if sent successfully
        """
        return self.send_message(receiver, "telemetry", telemetry_data)
        
    def send_command(self, receiver: str, command: str, parameters: Dict[str, Any] = None) -> bool:
        """
        Send a command message.
        
        Args:
            receiver: Target node ID
            command: Command name
            parameters: Command parameters
            
        Returns:
            bool: True if sent successfully
        """
        payload = {"command": command}
        if parameters:
            payload["parameters"] = parameters
            
        return self.send_message(receiver, "command", payload)
        
    def send_status(self, receiver: str, status: str, details: Dict[str, Any] = None) -> bool:
        """
        Send a status message.
        
        Args:
            receiver: Target node ID
            status: Status description
            details: Additional status details
            
        Returns:
            bool: True if sent successfully
        """
        payload = {"status": status}
        if details:
            payload["details"] = details
            
        return self.send_message(receiver, "status", payload)
        
    def start_listening(self) -> None:
        """Start listening for incoming messages in a separate thread."""
        if self.is_listening:
            print("-- Already listening for messages")
            return
            
        if not self.is_connected:
            print("-- Cannot start listening: XBee not connected")
            return
            
        self.is_listening = True
        self.listen_thread = threading.Thread(target=self._listen_for_messages, daemon=True)
        self.listen_thread.start()
        print("-- Started listening for XBee messages")
        
    def stop_listening(self) -> None:
        """Stop listening for incoming messages."""
        self.is_listening = False
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
        print("-- Stopped listening for XBee messages")
        
    def _listen_for_messages(self) -> None:
        """Internal method to listen for incoming messages."""
        buffer = ""
        
        while self.is_listening and self.serial_connection:
            try:
                if self.serial_connection.in_waiting > 0:
                    # Read as ASCII only
                    raw_data = self.serial_connection.read(self.serial_connection.in_waiting)
                    data = raw_data.decode('ascii', errors='ignore')
                    buffer += data
                    
                    # Process HEX encoded messages
                    while "<HEX>" in buffer and "<END>" in buffer:
                        start_idx = buffer.find("<HEX>") + 5
                        end_idx = buffer.find("<END>")
                        
                        if end_idx > start_idx:
                            hex_str = buffer[start_idx:end_idx]
                            buffer = buffer[end_idx + 5:]
                            
                            try:
                                # Decode hex back to JSON
                                message_str = bytes.fromhex(hex_str).decode('utf-8')
                                self._process_received_message(message_str)
                            except (ValueError, UnicodeDecodeError):
                                print("-- Invalid hex message received")
                        else:
                            break
                            
                time.sleep(0.01)
                
            except Exception as e:
                print(f"-- Error in message listening: {e}")
                buffer = ""
                time.sleep(0.1)
                
    def _process_received_message(self, message_str: str) -> None:
        """Process a received message."""
        try:
            message_data = json.loads(message_str)
            
            message = XBeeMessage(
                sender=message_data['sender'],
                receiver=message_data['receiver'],
                message_type=message_data['type'],
                payload=message_data['payload'],
                timestamp=message_data['timestamp']
            )
            
            # Store message
            self.received_messages.append(message)
            
            # Call registered callback if available
            if message.message_type in self.message_callbacks:
                self.message_callbacks[message.message_type](message)
            
            print(f"-- Received from {message.sender}: {message.message_type}")
            
        except json.JSONDecodeError as e:
            print(f"-- Error parsing received message: {e}")
        except KeyError as e:
            print(f"-- Missing field in received message: {e}")
            
    def register_callback(self, message_type: str, callback: Callable[[XBeeMessage], None]) -> None:
        """
        Register a callback function for a specific message type.
        
        Args:
            message_type: Type of message to handle
            callback: Function to call when message is received
        """
        self.message_callbacks[message_type] = callback
        print(f"-- Registered callback for message type: {message_type}")
        
    def get_received_messages(self, message_type: Optional[str] = None) -> list:
        """
        Get received messages, optionally filtered by type.
        
        Args:
            message_type: Filter by message type (optional)
            
        Returns:
            list: List of received messages
        """
        if message_type:
            return [msg for msg in self.received_messages if msg.message_type == message_type]
        return self.received_messages.copy()
        
    def clear_messages(self) -> None:
        """Clear the received messages buffer."""
        self.received_messages.clear()
        print("-- Cleared message buffer")
        
    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get current connection status.
        
        Returns:
            dict: Connection status information
        """
        return {
            "is_connected": self.is_connected,
            "is_listening": self.is_listening,
            "port": self.port,
            "baudrate": self.baudrate,
            "node_id": self.node_id,
            "messages_received": len(self.received_messages)
        }


# Example usage and test functions
def example_telemetry_callback(message: XBeeMessage) -> None:
    """Example callback for telemetry messages."""
    print(f"Telemetry from {message.sender}: {message.payload}")


def example_command_callback(message: XBeeMessage) -> None:
    """Example callback for command messages."""
    print(f"Command from {message.sender}: {message.payload}")


def main():
    """Example usage of XBeeModule."""
    # Initialize XBee module
    xbee = XBeeModule(port="/dev/ttyUSB0", baudrate=57600)
    xbee.set_node_id("DRONE_01")
    
    # Connect to XBee
    if not xbee.connect():
        print("Failed to connect to XBee")
        return
        
    # Register message callbacks
    xbee.register_callback("telemetry", example_telemetry_callback)
    xbee.register_callback("command", example_command_callback)
    
    # Start listening for messages
    xbee.start_listening()
    
    try:
        # Send some example messages
        xbee.send_telemetry("BASE_STATION", {
            "lat": 47.397606,
            "lon": 8.543060,
            "alt": 450.0,
            "battery": 85.5
        })
        
        xbee.send_status("BASE_STATION", "mission_started", {
            "mission_type": "waypoint",
            "waypoints": 3
        })
        
        # Keep running and listening
        while True:
            time.sleep(1)
            status = xbee.get_connection_status()
            if status["messages_received"] > 0:
                print(f"Total messages received: {status['messages_received']}")
                
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        xbee.disconnect()


if __name__ == "__main__":
    main()