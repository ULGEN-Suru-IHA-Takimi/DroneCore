#!/usr/bin/env python3

import serial
from digi.xbee.devices import XBeeDevice, RemoteXBeeDevice, XBee64BitAddress
from digi.xbee.exception import XBeeException, TimeoutException
import time
import threading
import json
from collections import deque

# --- Global Yapılandırma Sabitleri ---
DEFAULT_BAUD_RATE = 57600
# Not: SEND_INTERVAL ve QUEUE_RETENTION artık XBeeModule'ün kendi parametreleri veya dahili sabitleri olacak.

# --- XBeePackage Sınıfı ---
class XBeePackage:
    '''
    XBee üzerinden gönderilecek/alınacak paket tanımlaması.
    Paketin 't' (type), 's' (sender) ve 'p' (parameters) alanları vardır.
    '''
    def __init__(self, package_type: str, sender: str, params: dict = None):    
        self.package_type = package_type
        self.sender = sender
        self.params = params if params is not None else {}

    def to_json(self):
        """Paketi JSON formatında bir Python sözlüğüne dönüştürür."""
        data = {
            "t": self.package_type,
            "s": self.sender,
        }
        if self.params:
            data["p"] = self.params
        return data

    def __bytes__(self):
        """Paketi JSON string'ine ve ardından UTF-8 bayt dizisine dönüştürür."""
        json_data = json.dumps(self.to_json())
        encoded_data = json_data.encode('utf-8')
        # Paket boyutu uyarısı send_package metodunda daha detaylı ele alınacak.
        return encoded_data
    
    def __str__(self):
        return f"Type:{self.package_type}, Sender:{self.sender}, Params:{self.params}"
            
    @classmethod
    def from_bytes(cls, byte_data):
        """Bayt dizisinden XBeePackage nesnesi oluşturur."""
        decoded_data = byte_data.decode('utf-8')
        json_data = json.loads(decoded_data)
        
        package_type = json_data.get("t")
        sender = json_data.get("s")
        params = json_data.get("p", {})
        
        return cls(package_type, sender, params)

# --- XBeeModule Sınıfı ---
class XBeeModule:
    def __init__(self, port: str, baudrate: int = DEFAULT_BAUD_RATE, 
                 send_interval: float = 1.0, queue_retention_seconds: int = 10): 
        """
        XBee modülünü başlatır ve seri port ayarlarını yapar.
        :param port: XBee modülünün bağlı olduğu seri port.
        :param baudrate: Seri portun baud hızı.
        :param send_interval: Periyodik gönderimlerin aralığı (saniye).
        :param queue_retention_seconds: Gelen/giden paket kuyruğunda paketin saklanma süresi (saniye).
        """
        self.port = port
        self.baudrate = baudrate
        self.send_interval = send_interval
        self.queue_retention = queue_retention_seconds

        self.xbee_device: XBeeDevice = None
        self.local_xbee_address: XBee64BitAddress = None
        self.is_api_mode: bool = False 

        # Gelen ve giden sinyalleri depolamak için thread-safe kuyruklar
        self.received_queue = deque() # Sadece gelen paketler
        self.send_queue = deque()     # Gönderilecek paketler
        self.queue_lock = threading.Lock() # Kuyruklara erişim için tek kilit
        
        # İç thread'ler
        self.cleaner_thread = None
        self.sender_thread = None
        self.receiver_callback_set = False # Callback'in ayarlanıp ayarlanmadığını kontrol et

        print(f"XBeeModule başlatılıyor: Port={self.port}, Baudrate={self.baudrate}")
    
    def connect(self):
        """Seri porta bağlanır ve XBee cihazını başlatır."""
        if self.xbee_device and self.xbee_device.is_open():
            print("XBee zaten bağlı.")
            return True
        try:
            self.xbee_device = XBeeDevice(self.port, self.baudrate)
            self.xbee_device.open()
            
            print(f"XBee modülü '{self.port}' portuna başarıyla bağlandı.")
            
            try:
                ap_mode_param = self.xbee_device.get_parameter("AP")
                if ap_mode_param == b'\x01' or ap_mode_param == b'\x02':
                    self.is_api_mode = True
                    print("XBee modülü API modunda çalışıyor.")
                    self.local_xbee_address = self.xbee_device.get_64bit_addr()
                    print(f"Kendi adresim (API Modu): {self.local_xbee_address.address.hex()}")
                else:
                    self.is_api_mode = False
                    print("XBee modülü AT modunda (Transparent) çalışıyor.")
                    self.local_xbee_address = None
            except XBeeException as e:
                self.is_api_mode = False
                print(f"Uyarı: XBee modülü AT modunda olabilir (AP komutu hatası: {e}). Bağlantı AT modunda devam ediyor.")
                self.local_xbee_address = None

            # Sadece bir kere callback ata
            if not self.receiver_callback_set:
                self.xbee_device.add_data_received_callback(self._receive_data_callback)
                self.receiver_callback_set = True
            
            # Bağlantı kurulunca iç thread'leri başlat
            self._start_internal_threads()

            return True
        except serial.SerialException as e:
            print(f"Hata: Seri porta bağlanılamadı: {e}")
            self.disconnect()
            return False
        except XBeeException as e:
            print(f"Hata: XBee cihaza bağlanılamadı veya yapılandırılamadı: {e}")
            self.disconnect()
            return False
        except Exception as e:
            print(f"Beklenmedik bir hata oluştu: {e}")
            self.disconnect()
            return False

    def disconnect(self):
        """XBee cihazını kapatır ve seri port bağlantısını keser."""
        self._stop_internal_threads() # Thread'leri durdur
        if self.xbee_device and self.xbee_device.is_open():
            self.xbee_device.close()
            print(f"XBee bağlantısı '{self.port}' portunda kesildi.")
        else:
            print("XBee zaten bağlı değil.")
        
        self.xbee_device = None
        self.local_xbee_address = None
        self.is_api_mode = False
        self.receiver_callback_set = False

    def _start_internal_threads(self):
        """Modülün iç thread'lerini (gönderici ve temizleyici) başlatır."""
        if not self.cleaner_thread or not self.cleaner_thread.is_alive():
            self.cleaner_thread = threading.Thread(target=self._clean_queues_loop, name="XBeeCleanerThread", daemon=True)
            self.cleaner_thread.start()
        
        if not self.sender_thread or not self.sender_thread.is_alive():
            self.sender_thread = threading.Thread(target=self._send_loop, name="XBeeSenderThread", daemon=True)
            self.sender_thread.start()

    def _stop_internal_threads(self):
        """Modülün iç thread'lerini durdurur (şu an için Daemon olduklarından doğrudan kontrol edilemiyorlar)."""
        # Daemon thread'ler program sonlandığında otomatik ölür.
        # Eğer manuel kontrol gerekiyorsa, thread'lere bir bayrak eklemek gerekir.
        pass

    def send_data(self, package: XBeePackage, remote_xbee_addr_hex: str = None):
        """
        Belirtilen XBeePackage nesnesini gönderim kuyruğuna ekler.
        Gönderim işlemi arka plandaki _send_loop tarafından yönetilir.
        :param package: Gönderilecek XBeePackage nesnesi.
        :param remote_xbee_addr_hex: Hedef XBee'nin 64-bit adresi (hex string olarak).
                                  Sadece API modunda kullanılır. Broadcast için "000000000000FFFF".
        """
        with self.queue_lock:
            self.send_queue.append((package, remote_xbee_addr_hex))
        # print(f"Paket gönderim kuyruğuna eklendi: {package.package_type}")

    def _send_loop(self):
        """Arka planda gönderim kuyruğundaki paketleri periyodik olarak gönderir."""
        while self.xbee_device and self.xbee_device.is_open():
            with self.queue_lock:
                if self.send_queue:
                    package, remote_xbee_addr_hex = self.send_queue.popleft()
                    self._do_send(package, remote_xbee_addr_hex)
            time.sleep(self.send_interval)
        print("XBee Sender Thread durduruldu.")

    def _do_send(self, package: XBeePackage, remote_xbee_addr_hex: str = None):
        """Paket gönderme işlemini gerçekleştirir."""
        data_to_send = bytes(package)
        
        # Maksimum payload genellikle 72 byte.
        if len(data_to_send) > 72: 
            print(f"UYARI: Gönderilmek istenen paket boyutu ({len(data_to_send)} bayt) XBee'nin yaklaşık 72 bayt limitini aşıyor!")
            # Bu durumda paketi göndermeyebilir veya kırpabilirsiniz. Şimdilik devam ediyoruz.

        try:
            if self.is_api_mode:
                if remote_xbee_addr_hex:
                    remote_addr_obj = XBee64BitAddress(bytes.fromhex(remote_xbee_addr_hex)) 
                    remote_xbee = RemoteXBeeDevice(self.xbee_device, remote_addr_obj)
                    self.xbee_device.send_data(remote_xbee, data_to_send)
                    # print(f"Paket API modunda gönderildi: Tipi='{package.package_type}', Hedef='{remote_xbee_addr_hex}', Boyut={len(data_to_send)} bayt")
                else:
                    self.xbee_device.send_data_broadcast(data_to_send)
                    # print(f"Paket API modunda BROADCAST edildi: Tipi='{package.package_type}', Boyut={len(data_to_send)} bayt")
            else:
                self.xbee_device.send_data_local(data_to_send)
                # print(f"Paket AT modunda gönderildi (Transparent): Tipi='{package.package_type}', Boyut={len(data_to_send)} bayt")
            
        except TimeoutException:
            print(f"Hata: Paket gönderilirken zaman aşımı oluştu. Hedef XBee ulaşılamıyor olabilir.")
        except XBeeException as e:
            print(f"Hata: XBee gönderme hatası: {e}")
        except Exception as e:
            print(f"Beklenmedik bir hata oluştu paket gönderilirken: {e}")

    def read_received_data(self):
        """
        Kuyruktan gelen ilk paketi okur ve döndürür.
        Eğer kuyruk boşsa None döner.
        """
        with self.queue_lock:
            if self.received_queue:
                # Kuyrukta saklanan format: (timestamp, package_json_dict)
                timestamp, package_data = self.received_queue.popleft()
                return package_data
            else: 
                return None

    def _receive_data_callback(self, xbee_message):
        """
        XBee'den veri geldiğinde otomatik olarak çağrılan geri çağırma fonksiyonu.
        Gelen verinin formatını moda göre işler ve kuyruğa ekler.
        """
        data = xbee_message.data
        
        # Uzak adres bilgisi sadece loglama/hata ayıklama için kullanılabilir
        remote_address_64bit = None
        if hasattr(xbee_message, 'remote_device') and xbee_message.remote_device:
            try:
                remote_address_64bit = xbee_message.remote_device.get_64bit_addr().address.hex() 
            except Exception as e:
                # print(f"Uyarı: Uzak cihaz adres bilgisi alınamadı (geri çağırma içinde): {e}")
                pass
            
        try:
            received_package = XBeePackage.from_bytes(data)
            # print(f"\n<<< Paket Alındı (Kaynak: {remote_address_64bit or 'Bilinmiyor'}) >>>")
            # print(f"  Tip: {received_package.package_type}, Gönderen: {received_package.sender}")
            with self.queue_lock:
                self.received_queue.append((time.time(), received_package.to_json()))

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # print(f"\n<<< Ham Metin/Bayt Verisi Alındı (Hata) >>>")
            # print(f"  Kaynak: {remote_address_64bit or 'Bilinmiyor'}, Hata: {e}")
            with self.queue_lock:
                self.received_queue.append((time.time(), {"error": str(e), "raw_data_hex": data.hex(), "source_addr": remote_address_64bit}))
        except Exception as e:
            # print(f"Hata: Gelen paket işlenirken beklenmedik sorun oluştu: {e}")
            with self.queue_lock:
                self.received_queue.append((time.time(), {"error": "Genel İşleme Hatası: " + str(e), "source_addr": remote_address_64bit}))

    def _clean_queues_loop(self):
        """Belirli bir süreden eski kuyruk öğelerini temizler."""
        while True:
            now = time.time()
            with self.queue_lock:
                # Gelen kutusunu temizle
                while self.received_queue and now - self.received_queue[0][0] > self.queue_retention: 
                    self.received_queue.popleft()
                # Giden kutusunu temizle (şimdilik gidenler hemen işlenip siliniyor, bu kısım gerekmiyebilir)
                # Ancak bir hata durumunda veya gecikmede birikirse faydalı olabilir.
                # while self.send_queue and now - self.send_queue[0][0][0] > self.queue_retention: 
                #     self.send_queue.popleft()
            time.sleep(1)

# Dosya doğrudan çalıştırıldığında bir mesaj gösterelim
if __name__ == '__main__':
    print("xbee_controller.py dosyası doğrudan çalıştırıldı. Bu dosya XBee iletişim katmanını sağlar.")
    print("XBeePackage ve XBeeModule sınıflarını içerir.")
    print("Kullanmak için 'from xbee_controller import *' ifadesini projenize ekleyin.")