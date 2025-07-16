#!/usr/bin/env python3

import serial
from digi.xbee.devices import XBeeDevice, RemoteXBeeDevice, XBee64BitAddress
from digi.xbee.exception import XBeeException, TimeoutException
import time
import threading
import json
from collections import deque
import platform 

# --- Global Yapılandırma ve Kuyruklar için Sabitler ---
DEFAULT_BAUD_RATE = 57600
SEND_INTERVAL = 1  
QUEUE_RETENTION = 10 

# --- XBeePackage Sınıfı ---
class XBeePackage:
    '''
    XBee üzerinden gönderilecek/alınacak paket tanımlaması
    '''
    def __init__(self, package_type: str, # t paket tipi
                 sender: str,             # s gönderen
                 params: dict = None):    # p parametreler
        
        self.package_type = package_type
        self.sender = sender
        self.params = params if params is not None else {}

    def to_json(self):
        """
        Paketi JSON formatına dönüştürür.
        """
        data = {
            "t": self.package_type,
            "s": self.sender,
        }
        if self.params:
            data["p"] = self.params
        return data

    def __bytes__(self):
        """
        Paketi JSON string'ine ve ardından UTF-8 bayt dizisine dönüştürür.
        """
        json_data = json.dumps(self.to_json())
        encoded_data = json_data.encode('utf-8')
        if len(encoded_data) > 70: 
            print(f"Uyarı: Gönderilen paket boyutu ({len(encoded_data)} bayt) XBee limitini aşabilir. Veri kaybı yaşanabilir.")
        return encoded_data
    
    def __str__(self):
        return f"t:{self.package_type}, s:{self.sender},p:{self.params}"
            
    
    @classmethod
    def from_bytes(cls, byte_data):
        """
        Bayt dizisinden XBeePackage nesnesi oluşturur.
        """
        decoded_data = byte_data.decode('utf-8')
        json_data = json.loads(decoded_data)
        
        package_type = json_data.get("t")
        sender = json_data.get("s")
        params = json_data.get("p", {})
        
        return cls(package_type, sender, params)

# --- XBeeModule Sınıfı ---
class XBeeModule:
    def __init__(self, port: str, baudrate: int): 
        """
        XBee modülünü başlatır ve seri port ayarlarını yapar.
        :param port: XBee modülünün bağlı olduğu seri port.
        :param baudrate: Seri portun baud hızı.
        """
        self.port = port
        self.baudrate = baudrate
        self.xbee_device: XBeeDevice = None
        self.local_xbee_address: XBee64BitAddress = None
        self.is_api_mode: bool = False 

        # Gelen ve giden sinyalleri depolamak için thread-safe kuyruk
        self.signal_queue = deque()
        self.queue_lock = threading.Lock()

        print(f"XBeeModule başlatılıyor: Port={self.port}, Baudrate={self.baudrate}")
    
    def connect(self):
        """
        Seri porta bağlanır ve XBee cihazını başlatır.
        `XBeeDevice.open()` metodunun kendi mod algılama esnekliğini kullanır.
        """
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

            # BURASI ÖNEMLİ: XBee'den veri geldiğinde çağrılacak metodu atama
            # Bu, gelen paketlerin otomatik olarak işlenmesini sağlar.
            self.xbee_device.add_data_received_callback(self._receive_data_callback)
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
        """
        XBee cihazını kapatır ve seri port bağlantısını keser.
        """
        if self.xbee_device and self.xbee_device.is_open():
            self.xbee_device.close()
            print(f"XBee bağlantısı '{self.port}' portunda kesildi.")
        else:
            print("XBee zaten bağlı değil.")
        
        self.xbee_device = None
        self.local_xbee_address = None
        self.is_api_mode = False

    def send_package(self, package: XBeePackage, remote_xbee_addr_hex: str = None):
        """
        Belirtilen XBeePackage nesnesini belirli bir hedefe gönderir.
        Moda göre farklı gönderme metotları kullanır.
        :param package: Gönderilecek XBeePackage nesnesi.
        :param remote_xbee_addr_hex: Hedef XBee'nin 64-bit adresi (hex string olarak).
                                  Sadece API modunda kullanılır. AT modunda bu parametre göz ardı edilir.
                                  Yayın için: "000000000000FFFF" (Zigbee için)
                                  Eğer None ise ve API modundaysa, broadcast göndermeyi dener.
        """
        if not self.xbee_device or not self.xbee_device.is_open():
            print("Hata: XBee cihazı bağlı değil. Önce connect() metodunu çağırın.")
            return False
        
        data_to_send = bytes(package)
        
        if len(data_to_send) > 70:
            print(f"Uyarı: Gönderilen paket boyutu ({len(data_to_send)} bayt) XBee limitini aşabilir.")

        try:
            if self.is_api_mode:
                if remote_xbee_addr_hex:
                    # API modunda belirli bir adrese gönderme
                    remote_addr_obj = XBee64BitAddress(bytes.fromhex(remote_xbee_addr_hex)) 
                    remote_xbee = RemoteXBeeDevice(self.xbee_device, remote_addr_obj)
                    self.xbee_device.send_data(remote_xbee, data_to_send)
                    print(f"Paket API modunda gönderildi: Tipi='{package.package_type}', Hedef='{remote_xbee_addr_hex}', Boyut={len(data_to_send)} bayt")
                else:
                    # API modunda broadcast
                    self.xbee_device.send_data_broadcast(data_to_send)
                    print(f"Paket API modunda BROADCAST edildi: Tipi='{package.package_type}', Boyut={len(data_to_send)} bayt")
            else:
                # AT modunda, doğrudan seri porttan ham veri gönderir.
                # AT modunda spesifik bir adrese gönderme mümkün değildir, varsayılan DM/DL ayarına gider.
                self.xbee_device.send_data_local(data_to_send)
                print(f"Paket AT modunda gönderildi (Transparent): Tipi='{package.package_type}', Boyut={len(data_to_send)} bayt")
            with self.queue_lock:
                self.signal_queue.append((time.time(), 'OUT', package.to_json()))
            return True
        except TimeoutException:
            print(f"Hata: Paket gönderilirken zaman aşımı oluştu. Hedef XBee ulaşılamıyor olabilir.")
            return False
        except XBeeException as e:
            print(f"Hata: XBee gönderme hatası: {e}")
            return False
        except Exception as e:
            print(f"Beklenmedik bir hata oluştu paket gönderilirken: {e}")
            return False

    def read_package(self):
        if self.signal_queue:
            first_package = self.signal_queue.popleft()
            if first_package[1] == "IN":
                return first_package[2]

    def _receive_data_callback(self, xbee_message):
        """
        XBee'den veri geldiğinde otomatik olarak çağrılan geri çağırma fonksiyonu.
        Gelen verinin formatını moda göre işler ve kuyruğa ekler.
        """
        data = xbee_message.data
        
        remote_address_64bit = None
        if hasattr(xbee_message, 'remote_device') and xbee_message.remote_device:
            try:
                remote_address_64bit = xbee_message.remote_device.get_64bit_addr().address.hex() 
            except Exception as e:
                print(f"Uyarı: Uzak cihaz adres bilgisi alınamadı (geri çağırma içinde): {e}")
            
        try:
            received_package = XBeePackage.from_bytes(data)
            print(f"\n<<< Paket Alındı >>>")
            if remote_address_64bit:
                print(f"  Kaynak XBee Adresi (64-bit): {remote_address_64bit}")
            else:
                # Bu satır API modunda, RemoteXBeeDevice bilgisi varsa görünmeyecektir.
                print(f"  Kaynak Adres Bilgisi Yok (AT Modu Varsayıldı)") 
                
            print(f"  Tip: {received_package.package_type}")
            print(f"  Gönderen: {received_package.sender}")
            if received_package.params:
                print(f"  Parametreler: {received_package.params}")
            
            with self.queue_lock:
                self.signal_queue.append((time.time(), 'IN', received_package.to_json()))

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            try:
                print(f"\n<<< Ham Metin Verisi Alındı >>>")
                print(f"  Veri: {data.decode('utf-8')}")
                if remote_address_64bit:
                    print(f"  Kaynak XBee Adresi (64-bit): {remote_address_64bit}")
                else:
                    print(f"  Kaynak Adres Bilgisi Yok (AT Modu Varsayıldı)")
            except UnicodeDecodeError:
                print(f"\n<<< Ham Bayt Verisi Alındı >>>")
                print(f"  Veri (Hex): {data.hex()}")
                if remote_address_64bit:
                    print(f"  Kaynak XBee Adresi (64-bit): {remote_address_64bit}")
                else:
                    print(f"  Kaynak Adres Bilgisi Yok (AT Modu Varsayıldı)")
            print(f"  Hata: Gelen veri XBeePackage formatında olmayabilir. Çözümleme hatası: {e}")
            with self.queue_lock:
                self.signal_queue.append((time.time(), 'IN', data.hex()))
        except Exception as e:
            print(f"Hata: Gelen paket işlenirken beklenmedik sorun oluştu: {e}")
            with self.queue_lock:
                self.signal_queue.append((time.time(), 'IN', "Hata: " + str(e)))

    def clean_queue(self):
        """
        Belirli bir süreden eski kuyruk öğelerini temizler.
        Ayrı bir thread olarak çalışır.
        """
        while True:
            now = time.time()
            with self.queue_lock:
                while self.signal_queue and now - self.signal_queue[0][0] > QUEUE_RETENTION: 
                    self.signal_queue.popleft()
            time.sleep(1)


# --- Ana Program Akışı (XBeeModule kullanılarak) ---
if __name__ == '__main__':
    # Kullanıcıdan seri port bilgisini al
    print('XBee bağlantısı için port girin')
    if platform.system() == 'nt':
        input_user = "COM"+str(input('COM? :'))
    elif platform.system() == 'Linux':
        input_user = "/dev/"+str(input('/dev/? :'))
    else:
        input_user = str(input(' :'))
    
    # XBeeModule nesnesini başlat
    my_xbee_module = XBeeModule(port=input_user, baudrate=DEFAULT_BAUD_RATE) 

    # XBee bağlantısını kur
    if not my_xbee_module.connect():
        print("XBee bağlantısı kurulamadı. Lütfen portun doğru olduğundan ve XBee'nin çalıştığından emin olun.")
        exit()
    
    # Broadcast adresi (API modunda kullanılabilir)
    BROADCAST_64BIT_ADDR = "000000000000FFFF"

    try:
        # Periyodik gönderim fonksiyonu
        def periodic_sender_function(xbee_mod):
            while xbee_mod.xbee_device and xbee_mod.xbee_device.is_open():
                gps_package = XBeePackage(
                    package_type="G",
                    sender="1",
                    params={
                        "x": int(40.712800 * 1000000),
                        "y": int(-74.006000 * 1000000)}
                )
                xbee_mod.send_package(gps_package, remote_xbee_addr_hex=BROADCAST_64BIT_ADDR)
                time.sleep(SEND_INTERVAL) 

        # Veri gönderme thread'ini başlat
        sender_thread = threading.Thread(target=periodic_sender_function, args=(my_xbee_module,), daemon=True)
        sender_thread.start()

        # Kuyruk temizleyici thread'ini başlat
        cleaner_thread = threading.Thread(target=my_xbee_module.clean_queue, name="CleanerThread", daemon=True)
        cleaner_thread.start()

        # Ana thread'i, programın çıkışını bekleyecek şekilde tut
        input("Çıkmak için Enter'a basın...\n")

    except KeyboardInterrupt:
        print("\nProgram sonlandırılıyor...")
    finally:
        # Program sonlandığında XBee bağlantısını kapat
        my_xbee_module.disconnect()