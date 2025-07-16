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
        "la": int(40.7128 * 10000),
        "lo": int(-74.0060 * 10000),
        "a": int(150.5 * 10)}
)

add_waypoint_package = XBeePackage(
    package_type="W",
    sender=f"{waypoint_no}",
    params={
        "la": int(40.7128 * 10000),
        "lo": int(-74.0060 * 10000),
        "a": int(150.5 * 10)}
)

remove_waypoint_package = XBeePackage(
    package_type="w",
    sender=f"{waypoint_no}",
    params={
        "la": int(40.7128 * 10000),
        "lo": int(-74.0060 * 10000),
        "a": int(150.5 * 10)}
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
    sender="1"
)
mission_status_package = XBeePackage(
    package_type="MS",
    sender="1",
    params={
        "status": "continues" # successful / failed gibi durum ifadeleri
    }
)
```