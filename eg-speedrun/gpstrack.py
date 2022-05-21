import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime

import osmnx as ox
import requests
from shapely.geometry import Point
from networkx.exception import NodeNotFound


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



    def match_graph(self, G, valhalla_url=None):
        """match route against edges in G using valhalla APIII

        :param G: graph to match against
        :returns: list of matched edges contained in G
        """
        from shapely.geometry import Point

        # Query API

        if valhalla_url is not None:
            baseurl = valhalla_url
        else:
            baseurl = os.environ.get("VALHALLA_URL")

        if not baseurl.startswith("http"):
            baseurl = "https://" + baseurl

        url = f"{baseurl}/trace_attributes"
        # shape = [{"lat": p[0], "lon": p[1], "type": "via"} for p in self.points]
        # shape[0]["type"] = "break"
        # shape[-1]["type"] = "break"
        shape = [OrderedDict({"lat": p[0], "lon": p[1]}) for p in self.points]

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
        matched_points = [p for p in res["matched_points"] if p["type"] == "matched"]

        # save for optional later use
        self.matched_points = [(p['lat'],p['lon']) for p in matched_points]

        gdf_edges = ox.graph_to_gdfs(G, nodes=False)

        edges = res["edges"]
        matched_graph_edges = []
        matchcount = 0
        for matched_point in matched_points:
            edge_index = matched_point["edge_index"]
            if edge_index >= len(edges):
                print("Warning: Encountered edge index higher than number of edges?!!")
                continue
            matched_edge = edges[edge_index]
            way_id = matched_edge["way_id"]



            mask = gdf_edges["osmid"].apply(lambda x: (type(x) == int and way_id == x)
                                                      or (type(x) == list and way_id in x))

            filtered = gdf_edges[mask]
            if len(filtered) == 0:
                continue

            # one osm "way" contains multiple edges from our graph (if it wasn't simplified)
            # we look which one is closest to the point
            p = Point(matched_point['lon'], matched_point['lat'])
            # TODO: is some projection needed or does "coordinate distance" preserve order?
            with_distance = filtered.assign(distance=filtered.apply(lambda row: row.geometry.distance(p), axis=1))

            # edges in both ways will be containe
            sorted = with_distance.sort_values("distance")
            # u->v and v->u could be saved in graph G
            if sorted.iloc[1]["distance"] == sorted.iloc[0]["distance"]:
                matched_graph_edges += list(sorted[:2].index)
            else:
                matched_graph_edges += list(sorted[:1].index)
            matchcount += 1

        print(f"Matched {matchcount/len(matched_points) * 100}% of valhalla points with graph")


        # post processing
        filler_edges = GPSTrack.fill_gaps(G, matched_graph_edges)

        return matched_graph_edges,filler_edges


    @staticmethod
    def fill_gaps(G, matched_graph_edges, filler_thresh_length=30, filler_thresh_num_nodes=6):
        """Fill gaps in route that seem plausible

        :param G: osmnx Graph
        :param matched_graph_edges: list of edges of route that was matched
        :param filler_thresh_length: minimum length in meters where we don't fill the gap
        :param filler_thresh_num_nodes: minimum number of nodes in filling path where we don't fill the gap
        :returns: list of edges that were part of the gap

        """
        matched_graph_edges_uni = [] # save only one instance for double edges
        for (u,v,_) in matched_graph_edges:
            if u > v:
                u,v = v,u
            if len(matched_graph_edges_uni) == 0 or matched_graph_edges_uni[-1] != (u,v):
                matched_graph_edges_uni.append((u,v))

        # helpers
        edge_dict = {}
        for edge in G.edges(data=True):
            edge_dict[(edge[0],edge[1])] = edge[2]

        def path_length(path):
            return sum(edge_dict[(u,v)]['length'] for (u,v) in zip(path[:-1],path[1:]))

        # run post processing
        filler_edges = []
        filler_lengths = []
        mgeu = matched_graph_edges_uni
        next_node = -1
        for (e_cur,e_next) in zip(mgeu[:-1],mgeu[1:]):
            u_cur,v_cur = e_cur
            u_next,v_next = e_next

            if u_next in [u_cur, v_cur]:
                # edges are connected, continue
                next_node = v_next
                continue
            if v_next in [u_cur, v_cur]:
                # edges are connected, continue
                next_node = u_next
                continue

            # edges are not connected
            try:
                u_path,v_path = ox.shortest_path(G, [next_node, next_node], [u_next, v_next])
            except NodeNotFound:
                next_node = -1
                continue
            if u_path is None or v_path is None:
                next_node = -1
                continue

            u_length,v_length = path_length(u_path),path_length(v_path)
            if u_length < v_length:
                path = u_path
                length = u_length
                pot_next_node = v_next
            else:
                path = v_path
                length = v_length
                pot_next_node = u_next


            # threshold
            if length < filler_thresh_length and len(path) < filler_thresh_num_nodes:
                for (u,v) in zip(path[:-1], path[1:]):
                    filler_edges.append((u,v))
                    filler_lengths.append(length)
                next_node = pot_next_node
            else:
                print(f"Gap-Filling: Discarding too long filler path: {len(path)} nodes, {length:.2f}m")
                next_node = -1


        print(f"Gap-Filling: Filled in {len(filler_edges)} edges with a total length of {sum(filler_lengths):.2f}m")

        # finally, add filler edges to matched edges
        filler_graph_edges = []
        gdf_edges = ox.graph_to_gdfs(G, nodes=False)
        for (u,v) in filler_edges:
            if (u,v,0) in gdf_edges.index:
                filler_graph_edges.append((u,v,0))
            if (v,u,0) in gdf_edges.index:
                filler_graph_edges.append((v,u,0))

        return filler_graph_edges


    @staticmethod
    def fit_points_mapbox(points, timestamps, mapbox_token):
        # https://mapbox-mapbox.readthedocs-hosted.com/en/latest/mapmatching.html
        from mapbox import MapMatcher
        mm = MapMatcher(access_token=mapbox_token)


        # API only allows 100 points
        print(f"Matching {len(points)} points with matchbox")
        history = []
        for i in range(0, len(points), 100):
            if (len(points) - i) < 2:
                # mapbox needs at least 2 coordinates
                # in rare cases when points % 100 = 1
                # we loose one point
                continue
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

            # for some reason, mapbox excludes "highway:cycling" edges when using walking profile
            # TODO: find good gps_precision parameter
            r = mm.match(line, profile="mapbox.cycling")
            if r.status_code != 200:
                print(f"Bad return code from mapbox: {r.status_code}")
                print(r.text)
                breakpoint()
            #assert(r.status_code == 200)

            corrected = r.geojson()['features'][0]['geometry']['coordinates']
            print(f"{i}:{j} ({j-i} points) -> corrected to {len(corrected)} points")
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
