#!/usr/bin/env python3

import time
import platform
import asyncio
from waypoint_controller import waypoints, Waypoint
from xbee_controller import *
from mavsdk import System
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from connect.drone_connection import DroneConnection

class DroneController(DroneConnection):
    def __init__(self, sys_address="udpin://0.0.0.0:14540", port: str = "/dev/ttyUSB0", drone_id: str = "1", baudrate: int = DEFAULT_BAUD_RATE):
        super().__init__(sys_address=sys_address)
        self.flying_alt = 0
        self.target_alt = 10.0

        self.waypoint = waypoints() # waypoints sınıfından bir örnek oluşturuyoruz

        self.drone_id = drone_id
        self.xbee = XBeeModule(port=port, baudrate=baudrate) 
        self.BROADCAST_ADDR = "000000000000FFFF" 
        
        self.telemetry_send_interval = 1.0 
        self.last_telemetry_send_time = 0
        self.is_xbee_connected = False
        print(f"DroneController {self.drone_id} başlatıldı.")

    async def xbee_connect(self):
        """XBee bağlantısını kurar."""
        self.is_xbee_connected = self.xbee.connect() # Senkron çağrı, ayrı bir thread'de çalıştırmaya gerek yok, hızlı
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

    async def send_telemetry_loop(self) -> None:
        """
        Dronun güncel telemetri verilerini periyodik olarak gönderir.
        Gerçek drone konumunu MAVSDK'den alır.
        """
        last_known_lat = None
        last_known_lon = None
        
        # MAVSDK telemetri akışını başlat
        position_stream = self.drone.telemetry.position()
        
        # Pozisyonu arka planda güncelleyen yardımcı görev
        async def update_position_from_telemetry():
            nonlocal last_known_lat, last_known_lon
            try:
                async for position in position_stream:
                    last_known_lat = position.latitude_deg
                    last_known_lon = position.longitude_deg
            except asyncio.CancelledError:
                print("Position stream updater görevi iptal edildi.")
            except Exception as e:
                print(f"Pozisyon akışı güncellemede hata: {e}")

        # Yardımcı görevi başlat
        position_updater_task = asyncio.create_task(update_position_from_telemetry())

        try:
            while self.is_xbee_connected:
                if last_known_lat is not None and last_known_lon is not None:
                    if time.time() - self.last_telemetry_send_time >= self.telemetry_send_interval:
                        gps_package = XBeePackage(
                            package_type="G",
                            sender=self.drone_id,
                            params={
                                "x": int(last_known_lat * 1000000),  
                                "y": int(last_known_lon * 1000000), 
                            }
                        )
                        self.xbee.send_data(gps_package, remote_xbee_addr_hex=self.BROADCAST_ADDR)
                        self.last_telemetry_send_time = time.time()
                        print(f"Drone {self.drone_id}: Telemetri paketi gönderim kuyruğuna eklendi. (Lat: {last_known_lat:.6f}, Lon: {last_known_lon:.6f})")
                
                await asyncio.sleep(0.1) # Diğer görevlerin çalışmasına izin ver
        finally:
            # Döngü sonlandığında veya hata oluştuğunda yardımcı görevi iptal et
            position_updater_task.cancel()
            try:
                await position_updater_task # Görevin bitmesini bekle
            except asyncio.CancelledError:
                pass # Normal iptal

    async def process_messages_loop(self) -> None:
        """
        Gelen mesajları XBeeModule kuyruğundan sürekli okur ve işler.
        Asenkron bir görev olarak çalışacak.
        """
        while self.is_xbee_connected:
            incoming_package_json = self.xbee.read_received_data()
            if incoming_package_json: 
                print(f"\n--- DroneController {self.drone_id} - Gelen Paket İşleniyor ---")
                
                if "error" in incoming_package_json:
                    print(f"  Paket işleme hatası: {incoming_package_json['error']}")
                    if "raw_data_hex" in incoming_package_json:
                        print(f"  Ham Veri (Hex): {incoming_package_json['raw_data_hex']}")
                    if "source_addr" in incoming_package_json:
                        print(f"  Kaynak Adres: {incoming_package_json['source_addr']}")
                else:
                    print(f"  Tip: {incoming_package_json.get('t')}")
                    print(f"  Gönderen: {incoming_package_json.get('s')}")
                    print(f"  Parametreler: {incoming_package_json.get('p')}")

                    package_type = incoming_package_json.get('t')
                    sender_id = incoming_package_json.get('s')
                    params = incoming_package_json.get('p', {})
                    match package_type:
                        case "G":
                            latitude = params.get('x') / 1000000.0 if params.get('x') is not None else "N/A"
                            longitude = params.get('y') / 1000000.0 if params.get('y') is not None else "N/A"
                            print(f"    GPS verisi alındı ve işlendi: Gönderen={sender_id}, Lat={latitude}, Lon={longitude}")
                        case "H":
                            print(f"    El sıkışma alındı: Gönderen={sender_id}")
                        case "W":
                            latitude = params.get('x') / 1000000.0 if params.get('x') is not None else "N/A"
                            longitude = params.get('y') / 1000000.0 if params.get('y') is not None else "N/A"
                            heading = params.get('h', 0) # Eğer heading pakette geliyorsa
                            self.waypoint.add(sender_id,latitude,longitude,self.target_alt,heading)
                        case "w":
                            self.waypoint.remove(sender_id)
                        case "O":
                            print(f"    Görev için emir/order geldi: Görev id={sender_id}, Parametreler={params}")
                        case "MC":
                            print(f"    Göreve başlama onayı geldi: Gönderen={sender_id}, Görev numarası={params.get('id', 'N/A')}")
                        case _: 
                            print(f"    Bilinmeyen paket tipi alındı: {package_type}")
                
            await asyncio.sleep(0.01)

    async def get_flying_altitude(self) -> float:
        """Yükseklik alınıyor (home + offset)"""
        print("Fetching amsl altitude at home location....")
        async for terrain_info in self.drone.telemetry.home():
            absolute_altitude = terrain_info.absolute_altitude_m
            break
        
        self.flying_alt = absolute_altitude + self.target_alt
        print(f"-- Flying altitude set to: {self.flying_alt}m")
        return self.flying_alt

    async def arm_and_takeoff(self) -> None:
        """Arm drone and takeoff"""
        print("-- Arm ediliyor...")
        await self.drone.action.arm()

        print("-- Taking off...")
        await self.drone.action.takeoff()

        # Dronun kalkış irtifasına ulaşmasını bekle
        print(f"-- Waiting for drone to reach flying altitude (target: {self.target_alt}m relative)...")
        
        # Sadece hedef irtifaya ulaşana kadar pozisyon akışını dinle
        async for position in self.drone.telemetry.position():
            # Göreceli irtifayı kontrol et
            current_relative_altitude = position.relative_altitude_m
            print(f"  Current relative altitude: {current_relative_altitude:.2f}m") # İrtifa takibi için
            
            # Hedef irtifanın %90'ına ulaştığında (biraz esneklik için) veya tamamen hedef irtifaya ulaştığında
            # Koşulu `self.target_alt` ile kullanmak daha mantıklı olacaktır.
            if current_relative_altitude >= (self.target_alt * 0.95): # Hedef irtifanın %95'i
                print(f"-- Drone reached flying altitude ({current_relative_altitude:.2f}m relative), ready for waypoint mission")
                break # Telemetri akışından ve bu asenkron fonksiyondan çık
        
        await asyncio.sleep(2)  # Stabilize olması için ekstra bekleme

    async def go_to_waypoints(self, waypoint_ids=None) -> None:
        if waypoint_ids is None:
            print("Uyarı: Gidilecek waypoint ID'si belirtilmedi.")
            return

        for i in waypoint_ids:
            waypoint_obj = self.waypoint.read(i)
            if waypoint_obj is None:
                print(f"Hata: Waypoint {i} bulunamadı. Sonraki waypointe geçiliyor.")
                continue

            print(f"-- Going to waypoint {i}: ({waypoint_obj.lat}, {waypoint_obj.lon}) at {waypoint_obj.alt}m, heading {waypoint_obj.hed}deg")
            await self.drone.action.goto_location(waypoint_obj.lat, waypoint_obj.lon, waypoint_obj.alt, waypoint_obj.hed)

            await asyncio.sleep(2)

            print(f"-- Waypointe uçuluyor {i}...")
            target_reached = False
            while not target_reached:
                async for position in self.drone.telemetry.position():
                    lat_diff = abs(position.latitude_deg - waypoint_obj.lat)
                    lon_diff = abs(position.longitude_deg - waypoint_obj.lon)
                    # Çok daha küçük bir eşik kullanarak daha hassas kontrol
                    if lat_diff < 0.00001 and lon_diff < 0.00001: 
                        print(f"-- Reached waypoint {i}")
                        target_reached = True
                        break 
                
                if not target_reached:
                    await asyncio.sleep(1)
            print(f"-- Entering hold mode at waypoint {i} for 10 seconds...")
            await self.drone.action.hold()
            await asyncio.sleep(10)
            print(f"-- Finished loitering at waypoint {i}")
        
        print("-- All waypoints completed!")

    async def land(self) -> None:
        """Dronu indir"""
        print("-- iniyor...")
        await self.drone.action.land()
        
        async for armed in self.drone.telemetry.armed():
            if not armed:
                print("-- Drone indi ve disarm edildi")
                break

    async def run_mission(self) -> None:
        """Run complete mission: connect, takeoff, waypoints, land"""
        await super().connect() # DroneConnection'ın connect metodunu çağırıyoruz
        await self.get_flying_altitude()
        await self.arm_and_takeoff()
        await self.go_to_waypoints(waypoint_ids=("1","2","3"))
        await self.land()

# --- ANA PROGRAM AKIŞI ---
async def main(sys_address="serial:///dev/ttyACM0:115200"): 
    print('XBee bağlantısı için port girin')
    if platform.system() == 'nt':
        input_port = "COM"+str(input('COM? :'))
    elif platform.system() == 'Linux':
        input_port = "/dev/"+str(input('/dev/? :'))
    else:
        input_port = str(input(' :'))
    
    my_drone = DroneController(sys_address=sys_address, port=input_port, drone_id="1")

    # Waypoint'leri tanımla
    my_drone.waypoint.add("1",40.325757, 36.473615, 10.0, 0)
    my_drone.waypoint.add("2",40.325733, 36.473877, 10.0, 0)
    my_drone.waypoint.add("3",40.325499, 36.473636, 10.0, 0)

    # XBee bağlantısını kur
    if not await my_drone.xbee_connect(): 
        print("XBee bağlantısı kurulamadı. Program sonlandırılıyor.")
        return 

    # Asenkron görevleri başlat
    telemetry_task = asyncio.create_task(my_drone.send_telemetry_loop())
    message_processing_task = asyncio.create_task(my_drone.process_messages_loop())

    try:
        # Ana drone görevini başlat
        await my_drone.run_mission()
        
        # Görev tamamlandıktan sonra programı canlı tutmak için
        print("Görev tamamlandı. Program aktif kalmaya devam ediyor...")
        while True:
            await asyncio.sleep(1) 

    except asyncio.CancelledError:
        print("\nAsenkron görevler iptal edildi.")
    except KeyboardInterrupt:
        print("\nProgram sonlandırılıyor...")
    except Exception as e:
        print(f"Ana döngüde beklenmedik bir hata oluştu: {e}")
        # import traceback
        # traceback.print_exc() # Hata izini görmek için
    finally:
        telemetry_task.cancel()
        message_processing_task.cancel()
        # Her iki görevin de iptal edilmesini bekleyin ve olası istisnaları yoksayın
        await asyncio.gather(telemetry_task, message_processing_task, return_exceptions=True) 
        my_drone.xbee_disconnect()
        print("Program başarıyla sonlandırıldı.")

if __name__ == '__main__':
    asyncio.run(main())