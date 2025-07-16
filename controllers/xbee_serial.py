#!/usr/bin/env python3

import serial
import time
import threading
import json
from collections import deque
import platform

# --- Global Yapılandırma ve Kuyruklar için Sabitler ---
# Bu sabitler, programın genel ayarlarını belirler.
# AT modunda çoğu XBee varsayılan olarak 9600 baud ile başlar.
# Eğer XBee'nizin baud hızını XCTU ile değiştirdiyseniz, burayı güncelleyin.
DEFAULT_BAUD_RATE = 9600 

# Veri gönderme ve kuyruk yönetimi için ayarlar
SEND_INTERVAL = 1  # Saniyede 10 kez gönderim (1/0.1)
QUEUE_RETENTION = 10 # Saniye, kuyrukta tutulma süresi

# --- XBeePackage Sınıfı ---
# Kendi özel paket formatınız burada tanımlı.
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
        Paketi JSON formatında bir Python sözlüğüne dönüştürür.
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
        if len(encoded_data) > 70: # Bu değer XBee modelinize göre değişebilir (genelde 72-100 byte)
            print(f"Uyarı: Gönderilen paket boyutu ({len(encoded_data)} bayt) XBee limitini aşabilir.")
        return encoded_data
    
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

# --- Global Seri Port Nesnesi ve Kuyruklar ---
# Seri port bağlantısını yönetecek global nesne.
ser = None 

# Gelen ve giden sinyalleri depolamak için thread-safe kuyruk
signal_queue = deque()  
queue_lock = threading.Lock()

# --- Veri Okuma Fonksiyonu (Ayrı bir thread'de çalışır) ---
def read_from_port():
    """
    Seri porttan gelen verileri sürekli okur ve işler.
    """
    global ser
    while ser and ser.is_open:
        try:
            # Gelen veriyi satır satır oku. readline() satır sonu karakteri (örn. \n, \r\n) bekler.
            # timeout ayarı sayesinde bloklamaz, belirli bir süre bekler.
            line = ser.readline().decode('utf-8').strip()
            if line: # Eğer boş bir satır değilse işlem yap
                try:
                    # Gelen veriyi XBeePackage olarak çözmeyi dene
                    received_package = XBeePackage.from_bytes(line.encode('utf-8'))
                    print(f"\n<<< Paket Alındı >>>")
                    print(f"  Tip: {received_package.package_type}")
                    print(f"  Gönderen: {received_package.sender}")
                    if received_package.params:
                        print(f"  Parametreler: {received_package.params}")
                    with queue_lock:
                        signal_queue.append((time.time(), 'IN', received_package.to_json()))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    # Eğer JSON veya UTF-8 olarak çözülemezse ham metin/bayt olarak göster
                    print(f"\n<<< Ham Metin Verisi Alındı >>>")
                    print(f"  Veri: {line} (Hata: {e})")
                    with queue_lock:
                        signal_queue.append((time.time(), 'IN', line))
        except serial.SerialException as e:
            print(f"Hata: Seri port okuma hatası: {e}")
            break # Hata durumunda okuma döngüsünden çık
        except Exception as e:
            print(f"Beklenmedik bir hata oluştu okurken: {e}")
        time.sleep(0.01) # CPU kullanımını azaltmak için kısa bir bekleme

# --- Veri Gönderme Fonksiyonu (Ayrı bir thread'de çalışır) ---
def write_to_port():
    """
    Belirli aralıklarla XBeePackage oluşturup seri porttan gönderir.
    """
    global ser
    while ser and ser.is_open:
        try:
            # HANDSHAKE paketi oluştur
            handshake_package = XBeePackage(
                package_type="G",
                sender="1", # Gönderen dronun ID'si
                params={"status": "online", "time": int(time.time())}
            )
            data_to_send = bytes(handshake_package)
            
            # AT modunda, veriyi doğrudan seri porta yazın.
            # Karşı cihazın okuyabilmesi için satır sonu karakteri (\r\n) ekliyoruz.
            ser.write(data_to_send + b'\r\n') 
            print("📡 Mesaj gönderildi.")

            with queue_lock:
                signal_queue.append((time.time(), 'OUT', handshake_package.to_json()))
        except serial.SerialException as e:
            print(f"Hata: Seri port yazma hatası: {e}")
            break # Hata durumunda yazma döngüsünden çık
        except Exception as e:
            print(f"Beklenmedik bir hata oluştu gönderirken: {e}")
        time.sleep(SEND_INTERVAL) # Global SEND_INTERVAL değişkeni kullanıldı

# --- Kuyruk Temizleyici Fonksiyonu (Ayrı bir thread'de çalışır) ---
def queue_cleaner_function():
    """
    Belirli bir süreden eski kuyruk öğelerini temizler.
    """
    while True:
        now = time.time()
        with queue_lock:
            # Global QUEUE_RETENTION değişkeni kullanıldı
            while signal_queue and now - signal_queue[0][0] > QUEUE_RETENTION: 
                signal_queue.popleft()
        time.sleep(1)

# --- Ana Program Akışı ---
if __name__ == '__main__':
    print('XBee bağlantısı için port girin')
    if platform.system() == 'Windows':
        input_user = "COM"+str(input('COM? :'))
    elif platform.system() == 'Linux':
        input_user = "/dev/"+str(input('/dev/? :'))
    else:
        input_user = str(input(' :'))
    
    port_to_use = input_user

    try:
        # pyserial ile seri portu aç
        # timeout=0.5: readline() metodu için bir bekleme süresi ayarlar, böylece sürekli bloklamaz.
        ser = serial.Serial(port_to_use, DEFAULT_BAUD_RATE, timeout=0.5) 
        print(f"Seri port '{port_to_use}' başarıyla açıldı (Baud: {DEFAULT_BAUD_RATE}).")

        # Okuma thread'ini başlat
        read_thread = threading.Thread(target=read_from_port, daemon=True)
        read_thread.start()

        # Yazma thread'ini başlat
        write_thread = threading.Thread(target=write_to_port, daemon=True)
        write_thread.start()

        # Kuyruk temizleyici thread'ini başlat
        cleaner_thread = threading.Thread(target=queue_cleaner_function, daemon=True)
        cleaner_thread.start()

        input("Çıkmak için Enter'a basın...\n") # Ana thread'i açık tutar

    except serial.SerialException as e:
        print(f"Hata: Seri porta bağlanılamadı: {e}")
        print("Lütfen portun doğru olduğundan ve boşta olduğundan emin olun.")
    except Exception as e:
        print(f"Beklenmedik bir hata oluştu: {e}")
    finally:
        # Program sonlandığında seri portu kapat
        if ser and ser.is_open:
            ser.close()
            print("🔌 Seri port kapatıldı.")