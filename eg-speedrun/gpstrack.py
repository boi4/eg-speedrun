import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime

import osmnx as ox
import requests
from shapely.geometry import Point


def my_hash(text):
    h=0
    [(h := ((h*281^ord(ch)*997)&0xffffffff)) for ch in text]
    return str(h)


class GPSTrack:
    trkpt_pattern = re.compile(r'<trkpt.*?</trkpt>', flags=re.DOTALL)
    point_pattern = re.compile(r'<trkpt lat="([\d.-]+)" lon="([\d.-]+)">')
    name_pattern = re.compile(r'<name>([^<]+)</name>')
    date_pattern = re.compile(r'<time>([^<]+)</time>')
    track_type_pattern = re.compile(r'<type>([^<]+)</type>')

    # TODO: also cache mapbox calls!!!!!!
    cache_path = None
    request_cache = None

    def __init__(self, name, points, timestamps, track_type, date, filepath=None):
        """Create new GPSTrack

        :param name: the name of the gps track
        :param points: list of (lat, long) floats
        :param timestamps: list of datetime objects corresponding to the points
        :param track_type: one of ["running"]
        :param date: datetime object representing the time of the run
        """
        self.name = name
        self.points = points
        self.timestamps = timestamps
        self.track_type = track_type
        self.date = date
        self.filepath = filepath

    @classmethod
    def from_gpx(cls, filepath):
        with open(filepath) as f:
            content = f.read()

        name = cls.name_pattern.search(content).group(1)

        m = cls.date_pattern.search(content)
        if m is None:
            date = None
        else:
            datestr = m.group(1)
            try:
                date = datetime.strptime(datestr, "%Y-%m-%dT%H:%M:%S.000Z")
            except ValueError:
                print(f"Failed to parse timestamp: {datestr}")
                date = None

        track_type = cls.track_type_pattern.search(content)


        track_points = cls.trkpt_pattern.findall(content)

        points = [cls.point_pattern.search(text) for text in track_points]
        if any(p is None for p in points):
            print(filepath)
            breakpoint()
        points = [point.groups() for point in points]
        points = [tuple(float(p) for p in point) for point in points]

        timestamps = [datetime.strptime(cls.date_pattern.search(text).group(1), "%Y-%m-%dT%H:%M:%S.000Z")
                      for text in track_points]
        return cls(name=name, points=points, timestamps=timestamps, track_type=track_type, date=date, filepath=filepath)


    @classmethod
    def set_cachefile(cls, filepath):
        cls.cache_path = filepath

        if os.path.isfile(filepath):
            with open(filepath, "r") as f:
                cls.request_cache = json.load(f)
                # print(cls.request_cache.keys())

    @classmethod
    def flush_cachefile(cls):
        if cls.cache_path is not None and cls.request_cache is not None:
            dir = os.path.dirname(cls.cache_path)
            if not os.path.isdir(dir):
                os.makedirs(dir)

            with open(cls.cache_path, "w") as f:
                tmp = json.dumps(cls.request_cache)
                f.write(tmp)

    def __str__(self):
        return f"""
GPSTrack(name={self.name}, date={self.date}, type={self.track_type}, points={len(self.points)} points)
        """.strip()

    __repr__ = __str__



    def match_graph(self, G, valhalla_url=None, mapbox_token=None):
        """match route against edges in G using valhalla APIII

        :param G: graph to match against
        :returns: list of matched edges contained in G
        """

        # Query API

        if valhalla_url is not None:
            baseurl = valhalla_url
        else:
            baseurl = os.environ.get("VALHALLA_URL")
        url = f"{baseurl}/trace_attributes"
        # shape = [{"lat": p[0], "lon": p[1], "type": "via"} for p in self.points]
        # shape[0]["type"] = "break"
        # shape[-1]["type"] = "break"
        if mapbox_token is not None:
            points = GPSTrack.fit_points_mapbox(self.points, self.timestamps, mapbox_token)
        else:
            points = self.points
        shape = [OrderedDict({"lat": p[0], "lon": p[1]}) for p in points]

        d = OrderedDict()
        d["shape"] = shape
        d["costing"] = "pedestrian"
        d["shape_match"] = "map_snap"
        # d["begin_time"] = self.timestamps[0].strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # d["durations"] = [(d-d_prev).total_seconds() for (d_prev,d) in zip(self.timestamps[:-1], self.timestamps[1:])]

        headers = {'Content-type': 'application/json'}


        if GPSTrack.request_cache is None:
            GPSTrack.request_cache = {}

        request_hash = my_hash(json.dumps(d))
        if request_hash not in GPSTrack.request_cache:
            print("Sending request to Valhalla for map matching")
            r = requests.post(url, data=json.dumps(d), headers=headers)
            if r.status_code != 200:
                print(self.name)
                print("Unexpected valhalla http return value")
                print(r.text)
                return None

            GPSTrack.request_cache[request_hash] = r.text
            GPSTrack.flush_cachefile()

        text = GPSTrack.request_cache[request_hash]

        res = json.loads(text)

        # parse result
        mp = [p for p in res["matched_points"] if p["type"] == "matched"]

        # save for optional later use
        self.matched_points = [(p['lat'],p['lon']) for p in mp]


        edges = res["edges"]
        edges_is = [p["edge_index"] for p in mp]

        if any(ei >= len(edges) for ei in edges_is):
            print("Warning: Encountered edge indizes higher than number of edges?!!")
            edges_is = [ei for ei in edges_is if ei < len(edges)]

        matched_edges = [edges[ei] for ei in edges_is]

        gdf_edges = ox.graph_to_gdfs(G, nodes=False)

        matched_graph_edges = []
        matchcount = 0
        for me in matched_edges:
            osmid = me['way_id']
            mask = gdf_edges["osmid"].apply(lambda x: (type(x) == int and osmid == x)
                                                      or (type(x) == list and osmid in x))
            filtered = gdf_edges[mask]
            if len(filtered) > 0:
                matchcount += 1
            for index,_ in filtered.iterrows():
                matched_graph_edges.append(index)

        # print(f"Matched {matchcount/len(matched_edges) * 100}% of edges")
        return matched_graph_edges



    @staticmethod
    def fit_points_mapbox(points, timestamps, mapbox_token):
        # https://mapbox-mapbox.readthedocs-hosted.com/en/latest/mapmatching.html
        from mapbox import MapMatcher
        mm = MapMatcher(access_token=mapbox_token)


        # API only allows 100 points
        history = []
        for i in range(0, len(points), 100):
            j = min(i + 100, len(points))
            line = {
                "type": "Feature",
                "properties": {
                    "coordTimes": [d.strftime("%Y-%m-%dT%H:%M:%S.000Z") for d in timestamps[i:j]]
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[p[1],p[0]] for p in points[i:j]]
                }
            }

            r = mm.match(line, profile="mapbox.walking")
            if r.status_code != 200:
                breakpoint()
            #assert(r.status_code == 200)

            corrected = r.geojson()['features'][0]['geometry']['coordinates']
            history += corrected

            time.sleep(1)


        return [(c[1],c[0]) for c in history]



    def match_graph2(self, G, max_distance=10):
        """Match the route points to the edges of graph G

        :param G:
        :param max_distance: maximum allowed distance of point in meters to an
                             edge to count the edge
        :returns: list of edges in G
        """

        # project graph and points
        P = ox.project_graph(G)
        points_p = []
        for plat,plon in self.points:
            point_p, _ = ox.projection.project_geometry(Point(plon,plat), to_crs=P.graph['crs'])
            points_p.append(point_p)


        # find neared edge for each point
        es = ox.nearest_edges(P, [p.x for p in points_p], [p.y for p in points_p], return_dist=True)
        #return es[0]


        # make list of (edge, distance, point)
        es = [(e,es[1][i],self.points[i]) for (i,e) in enumerate(es[0])]

        gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

        # remove edges too far away from measurement
        es2 = []
        for i,e in enumerate(es):
            dist = e[1]
            if dist < max_distance:
                es2.append(e)

        es3 = []


        # A very hacky heuristic
        prev_e = None
        edge_streak = []
        from collections import defaultdict
        d = defaultdict(list)
        MIN_STREAK = 3
        for i,e in enumerate(es2 + [((-1,-1,-1),-1,(-1,-1))]):
            if prev_e != None:
                if prev_e[0] != e[0]:
                    # if we measured MIN_STREAK or more points on the edge after each other
                    # we confirm the edge
                    if len(edge_streak) >= MIN_STREAK:
                        es3 += edge_streak
                    else:
                        # to avoid path where we where only shortly close to them
                        # but not really on the path, we check whether our measurements
                        # where too "close" to an intersection
                        l = []
                        for check_e in edge_streak:
                            length = gdf_edges.loc[check_e[0]]["length"]
                            p = check_e[2]
                            p0 = check_e[0][0]
                            p1 = check_e[0][1]
                            d0 = ox.distance.great_circle_vec(gdf_nodes.loc[p0]["y"],gdf_nodes.loc[p0]["x"],p[0],p[1])
                            d1 = ox.distance.great_circle_vec(gdf_nodes.loc[p1]["y"],gdf_nodes.loc[p1]["x"],p[0],p[1])
                            dist = min(d0,d1)
                            l.append(dist/length)
                            #d[e[0]].append(dist/length)
                        if max(l) > 0.2:
                            es3 += edge_streak

                    edge_streak = []

            edge_streak.append(e)
            prev_e = e


        route = [e[0] for e in es3]
        return route
