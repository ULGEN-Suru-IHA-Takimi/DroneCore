#!/usr/bin/env python3

import time
import platform
from waypoint_controller import *
# xbee_controller.py dosyasındaki tüm sınıfları ve değişkenleri içe aktarın.
# Bu dosyanın xbee_controller.py ile aynı dizinde olduğundan emin olun.
from xbee_controller import * # --- DRONE CONTROLLER SINIFI ---
class DroneController:
    def __init__(self, port: str, drone_id: str, baudrate: int = DEFAULT_BAUD_RATE):
        """
        DroneController başlatıcısı. XBee iletişimi ve dron mantığını ayırır.
        :param port: XBee modülünün bağlı olduğu seri port.
        :param drone_id: Bu dronun benzersiz ID'si.
        :param baudrate: XBee iletişim baud hızı.
        """
        self.drone_id = drone_id
        # XBeeModule'ü doğrudan DroneController içinde başlatıyoruz ve tüm iletişim mantığını ona bırakıyoruz.
        self.xbee = XBeeModule(port=port, baudrate=baudrate) 
        self.BROADCAST_ADDR = "000000000000FFFF" # Zigbee Broadcast adresi
        
        self.telemetry_send_interval = 1.0 # Telemetri gönderme sıklığı (saniye)
        self.last_telemetry_send_time = 0

        # Dronun bağlı olup olmadığını takip edelim
        self.is_connected = False
        print(f"DroneController {self.drone_id} başlatıldı.")

    def connect(self):
        """XBee bağlantısını kurar."""
        self.is_connected = self.xbee.connect()
        if self.is_connected:
            print(f"DroneController {self.drone_id}: XBee bağlantısı başarılı.")
        else:
            print(f"DroneController {self.drone_id}: XBee bağlantısı kurulamadı.")
        return self.is_connected

    def disconnect(self):
        """XBee bağlantısını keser."""
        self.xbee.disconnect()
        self.is_connected = False
        print(f"DroneController {self.drone_id}: XBee bağlantısı kesildi.")

    def send_telemetry(self, latitude: float, longitude: float):
        """
        Dronun güncel telemetri verilerini gönderir.
        Periyodik gönderme kontrolü burada yapılır.
        """
        if not self.is_connected:
            # print("Hata: XBee bağlı değil, telemetri gönderilemiyor.")
            return

        if time.time() - self.last_telemetry_send_time >= self.telemetry_send_interval:
            gps_package = XBeePackage(
                package_type="G",
                sender=self.drone_id,
                params={
                    "x": int(latitude * 1000000),  # Latitude'i int'e çeviriyoruz (6 ondalık hane hassasiyet)
                    "y": int(longitude * 1000000), # Longitude'i int'e çeviriyoruz (6 ondalık hane hassasiyet)
                }
            )
            # XBeeModule'ün send_data metodunu çağırıyoruz.
            self.xbee.send_data(gps_package, remote_xbee_addr_hex=self.BROADCAST_ADDR)
            self.last_telemetry_send_time = time.time()
            print(f"Drone {self.drone_id}: Telemetri paketi gönderim kuyruğuna eklendi.")

    def process_incoming_messages(self):
        """
        Gelen mesajları XBeeModule kuyruğundan okur ve işler.
        Bu metodun ana döngüde düzenli olarak çağrılması gerekir.
        """
        if not self.is_connected:
            return

        incoming_package_json = self.xbee.read_received_data()
        while incoming_package_json: # Kuyrukta paket olduğu sürece oku
            print(f"\n--- DroneController {self.drone_id} - Gelen Paket İşleniyor ---")
            
            # Hata durumlarını kontrol et
            if "error" in incoming_package_json:
                print(f"  Paket işleme hatası: {incoming_package_json['error']}")
                if "raw_data_hex" in incoming_package_json:
                    print(f"  Ham Veri (Hex): {incoming_package_json['raw_data_hex']}")
                if "source_addr" in incoming_package_json:
                    print(f"  Kaynak Adres: {incoming_package_json['source_addr']}")
            else:

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
                        add_waypoint(sender_id,latitude,longitude)
                    case "w":
                        remove_waypoint(sender_id)
                    case "O":
                        print(f"    Görev için emir/order geldi: Görev id={sender_id}, Parametreler={params}")
                    case "MC":
                        print(f"    Göreve başlama onayı geldi: Gönderen={sender_id}, Görev numarası={params[id]}")
            
            # Bir sonraki paketi dene (varsa)
            incoming_package_json = self.xbee.read_received_data()


# --- ANA PROGRAM AKIŞI ---
if __name__ == '__main__':
    # Kullanıcıdan seri port bilgisini al
    print('XBee bağlantısı için port girin')
    if platform.system() == 'nt':
        input_port = "COM"+str(input('COM? :'))
    elif platform.system() == 'Linux':
        input_port = "/dev/"+str(input('/dev/? :'))
    else:
        input_port = str(input(' :'))
    
    # DroneController nesnesini basitçe başlatın
    # XBeeModule'ün başlatılması ve thread'leri DroneController içinde yönetilir.
    my_drone = DroneController(port=input_port, drone_id="DRONE_1")

    # XBee bağlantısını kur
    if not my_drone.connect():
        print("XBee bağlantısı kurulamadı. Program sonlandırılıyor.")
        exit()
    
    # Örnek telemetri gönderme ve gelen mesajları işleme döngüsü
    current_lat = 40.712800
    current_lon = -74.006000

    try:
        while True:
            # Telemetri verilerini güncelle (gerçek dron sensörlerinden gelecek)
            current_lat += 0.000001 
            current_lon -= 0.000002

            # Telemetri gönder (XBeeModule tarafından yönetilen dahili kuyruğa ekler)
            my_drone.send_telemetry(current_lat, current_lon)
            
            # Gelen mesajları işle (XBeeModule'den okur)
            my_drone.process_incoming_messages()

            # CPU'yu boş yere harcamamak için kısa bir bekleme
            time.sleep(0.1) # Daha sık kontrol için bu süreyi kısaltabilirsiniz.

    except KeyboardInterrupt:
        print("\nProgram sonlandırılıyor...")
    finally:
        my_drone.disconnect()
        print("Program başarıyla sonlandırıldı.")