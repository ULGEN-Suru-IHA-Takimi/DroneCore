waypoints = {}

class waypoint:
    def __init__(self,lat,lon):
        self.lat = lat
        self.lon = lon

def add_waypoint(id,lat,lon):
    waypoint[id]=waypoint(lat,lon)
    print(f"    Waypoint eklendi/güncellendi: id={id}, latitude={lat}, longitude={lon}")

def read_waypoint(id):
    try:
        return (waypoint[id].lat , waypoint[id].lat)
    except:
        print(f"    Waypoint okuma başarısız: id={id}")
        return None

def remove_waypoint(id):
    try:
        waypoints.pop(id)
        print(f"    Waypoint silindi: id={id}")
    except:
        print(f"    Waypoint silme başarısız: id={id}")

if __name__ == "__main__":
    pass