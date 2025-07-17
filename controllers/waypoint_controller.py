waypoints = {}
class waypoints:
    def __init__(self):
        self.list={}
    def add(self,id,lat,lon,alt,hed):
        self.list[id]=waypoint(lat,lon,alt,hed)
        print(f"    Waypoint eklendi/güncellendi: id={id}, latitude={lat}, altitude={alt} longitude={lon}, heading={hed}")

    def read(self,id):
        try:
            return {"lat":self.list[id].lat , "lon":self.list[id].lon, "alt":self.list[id].alt, "hed":self.list[id].head}
        except:
            print(f"    Waypoint okuma başarısız: id={id}")
            return None

    def remove(self,id):
        try:
            self.list.pop(id)
            print(f"    Waypoint silindi: id={id}")
        except:
            print(f"    Waypoint silme başarısız: id={id}")


class waypoint:
    def __init__(self,lat,lon,alt,hed):
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.hed = hed

if __name__ == "__main__":
    pass