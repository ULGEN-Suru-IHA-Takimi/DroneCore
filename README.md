# DroneCore

- [ ] communication/xbee_communication.py olustururulacak
- [*] basit veri gonderip alma islemi class based bir hale getirilecek 
- [*]veri gonderme ve alma gibi fonksiyonlar class halinde moduler olacak

## Xbee Paket Tipleri
```
handshake_package = XBeePackage(
    package_type="H",
    sender="1"
)

gps_package = XBeePackage(
    package_type="G",
    sender="1",
    params={
        "x": int(40.7128 * 10000),
        "y": int(-74.0060 * 10000)}
)

add_waypoint_package = XBeePackage(
    package_type="W",
    sender=f"{waypoint_no}",
    params={
        "x": int(40.7128 * 10000),
        "y": int(-74.0060 * 10000)}
)

remove_waypoint_package = XBeePackage(
    package_type="w",
    sender=f"{waypoint_no}"
)

order_package = XBeePackage(
    package_type="O",
    sender=f"{mission.index}",
    params={
        "f": "V",
        "wp": [1,2,3]}  #Göreve eklenecek özel parametreler
)

mission_confirm_package = XBeePackage(
    package_type="MC",
    sender="1",
    params={
        "id": f"{mission_id}"
    }
)
mission_status_package = XBeePackage(
    package_type="MS",
    sender="1",
    params={
        "status": "continues" # successful / failed gibi durum ifadeleri
    }
)
```