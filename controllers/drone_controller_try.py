#!/usr/bin/env python3

import time
import platform
import asyncio
from waypoint_controller import *
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
        self.target_alt = 20.0

        self.waypoint = waypoints()

        self.drone_id = drone_id
        self.xbee = XBeeModule(port=port, baudrate=baudrate) 
        self.BROADCAST_ADDR = "000000000000FFFF" 
        
        self.telemetry_send_interval = 1.0 
        self.last_telemetry_send_time = 0
        self.is_xbee_connected = False
        print(f"DroneController {self.drone_id} başlatıldı.")

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

    async def send_telemetry_loop(self) -> None:
        """
        Dronun güncel telemetri verilerini periyodik olarak gönderir.
        """
        current_lat = 40.712800 # Simülasyon için başlangıç değeri
        current_lon = -74.006000 # Simülasyon için başlangıç değeri

        while self.is_xbee_connected:
            # Telemetri verilerini güncelle (gerçek dron sensörlerinden gelecek)
            current_lat += 0.000001 
            current_lon -= 0.000002

            if time.time() - self.last_telemetry_send_time >= self.telemetry_send_interval:
                gps_package = XBeePackage(
                    package_type="G",
                    sender=self.drone_id,
                    params={
                        "x": int(current_lat * 1000000),  
                        "y": int(current_lon * 1000000), 
                    }
                )
                # send_data senkron olmasına rağmen, XBeeModule zaten thread'leri yönetiyor.
                # await'e gerek yok, çünkü bloke edici bir G/Ç işlemi yok (kuyruğa ekleme).
                self.xbee.send_data(gps_package, remote_xbee_addr_hex=self.BROADCAST_ADDR)
                self.last_telemetry_send_time = time.time()
                print(f"Drone {self.drone_id}: Telemetri paketi gönderim kuyruğuna eklendi. (Lat: {current_lat:.6f}, Lon: {current_lon:.6f})")
            
            await asyncio.sleep(0.1) # Kısa bir bekleme, diğer görevlerin çalışmasına izin verir.

    async def process_messages_loop(self) -> None:
        """
        Gelen mesajları XBeeModule kuyruğundan sürekli okur ve işler.
        Asenkron bir görev olarak çalışacak.
        """
        while self.is_xbee_connected:
            incoming_package_json = self.xbee.read_received_data()
            if incoming_package_json: # Kuyrukta paket olduğu sürece oku
                print(f"\n--- DroneController {self.drone_id} - Gelen Paket İşleniyor ---")
                
                # Hata durumlarını kontrol et
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

                    # Gelen pakete göre işleme yap
                    package_type = incoming_package_json.get('t')
                    sender_id = incoming_package_json.get('s')
                    params = incoming_package_json.get('p', {})
                    match package_type:
                        case "G":
                            latitude = params.get('x') / 1000000.0 if params.get('x') is not None else "N/A"
                            longitude = params.get('y') / 1000000.0 if params.get('y') is not None else "N/A"
                            print(f"    GPS verisi alındı ve işlendi: Gönderen={sender_id}, Lat={latitude}, Lon={longitude}")
                            # Burada dronun konumunu güncelleyebilir veya haritaya işleyebilirsiniz.
                        case "H":
                            print(f"    El sıkışma alındı: Gönderen={sender_id}")
                        case "W":
                            latitude = params.get('x') / 1000000.0 if params.get('x') is not None else "N/A"
                            longitude = params.get('y') / 1000000.0 if params.get('y') is not None else "N/A"
                            heading = 0
                            self.waypoint.add(sender_id,latitude,longitude,self.target_alt,heading)
                            # add_waypoint(sender_id,latitude,longitude) # Eğer waypoint_controller asenkron ise await kullanın
                        case "w":
                            # remove_waypoint(sender_id) # Eğer waypoint_controller asenkron ise await kullanın
                            self.waypoint.remove(sender_id)
                        case "O":
                            print(f"    Görev için emir/order geldi: Görev id={sender_id}, Parametreler={params}")
                        case "MC":
                            # print(f"    Göreve başlama onayı geldi: Gönderen={sender_id}, Görev numarası={params[id]}") # 'id' yerine 'id' anahtarı mı olmalı?
                            print(f"    Göreve başlama onayı geldi: Gönderen={sender_id}, Görev numarası={params.get('id', 'N/A')}")
                        case _: # Bilinmeyen paket tipi
                            print(f"    Bilinmeyen paket tipi alındı: {package_type}")
                
            await asyncio.sleep(0.01) # Daha sık kontrol için çok kısa bekleme

    async def get_flying_altitude(self) -> float:
        """Yükseklik alınıyor (home + offset)"""
        print("Fetching amsl altitude at home location....")
        async for terrain_info in self.drone.telemetry.home():
            absolute_altitude = terrain_info.absolute_altitude_m
            break
        
        # Fly 20m above the ground plane
        self.flying_alt = absolute_altitude + self.target_alt
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

    async def go_to_waypoints(self,waypoint_ids=("1","2","3")) -> None:
        for i, in waypoint_ids:
            waypoint = self.waypoint.read(i)
            print(f"-- Going to waypoint {i}: ({waypoint.lat}, {waypoint.lon}) at {waypoint.alt}m")
            await self.drone.action.goto_location(waypoint.lat, waypoint.lon, waypoint.alt, waypoint.yaw)

            # Give drone time to start moving
            await asyncio.sleep(2)

            # Wait until we reach the waypoint
            print(f"-- Flying to waypoint {i}...")
            target_reached = False
            while not target_reached:
                async for position in self.drone.telemetry.position():
                    lat_diff = abs(position.latitude_deg - lat)
                    lon_diff = abs(position.longitude_deg - lon)
                    # If we're close enough (within ~10 meters)
                    if lat_diff < 0.0001 and lon_diff < 0.0001:
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
        
        # Wait for landing to complete
        async for armed in self.drone.telemetry.armed():
            if not armed:
                print("-- Drone indi ve disarm edildi")
                break

    async def run_mission(self) -> None:
        """Run complete mission: connect, takeoff, waypoints, land"""
        await self.connect()
        await self.get_flying_altitude()
        await self.arm_and_takeoff()
        await self.go_to_waypoints(waypoint_ids=("1","2","3"))
        await self.land()

# --- ANA PROGRAM AKIŞI ---
async def main(sys_address="udpin://0.0.0.0:14540"): # main fonksiyonu
    # Kullanıcıdan seri port bilgisini al
    print('XBee bağlantısı için port girin')
    if platform.system() == 'nt':
        input_port = "COM"+str(input('COM? :'))
    elif platform.system() == 'Linux':
        input_port = "/dev/"+str(input('/dev/? :'))
    else:
        input_port = str(input(' :'))


    # Drone oluştur
    my_drone = DroneController(sys_address=sys_address, port=input_port, drone_id="1")

    my_drone.waypoint.add("1",47.397606, 8.543060, 20.0, 0)
    my_drone.waypoint.add("2",47.398106, 8.543560, 20.0, 90)
    my_drone.waypoint.add("3",47.397106, 8.544060, 20.0, 180)

    if not await my_drone.xbee_connect(): # connect metodu await ediliyor
        print("XBee bağlantısı kurulamadı. Program sonlandırılıyor.")
        return # Programı burada sonlandır

    # Asenkron görevleri başlat
    #telemetry_task = asyncio.create_task(my_drone.send_telemetry_loop())
    message_processing_task = asyncio.create_task(my_drone.process_messages_loop())

    try:
        # Tüm görevlerin tamamlanmasını bekle (program kapanana kadar çalışacaklar)
        # Genellikle programın kapanmasını beklemek için bu kullanılır,
        # veya başka kullanıcı girişi/GUI döngüsü buraya konulabilir.
        await my_drone.run_mission()
        while True:
            await asyncio.sleep(1) # Ana döngüyü bloklamadan diğer görevlerin çalışmasına izin ver
            # Bu döngü, programın canlı kalmasını sağlar.

    except asyncio.CancelledError:
        print("\nAsenkron görevler iptal edildi.")
    except KeyboardInterrupt:
        print("\nProgram sonlandırılıyor...")
    finally:
        # Görevleri iptal et ve bağlantıyı kes
        telemetry_task.cancel()
        message_processing_task.cancel()
        await asyncio.gather(telemetry_task, message_processing_task, return_exceptions=True) # Görevlerin bitmesini bekle
        my_drone.xbee_disconnect()
        print("Program başarıyla sonlandırıldı.")

if __name__ == '__main__':
    asyncio.run(main()) # Ana asenkron fonksiyonu çalıştır