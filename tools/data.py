#!/usr/bin/env python3
"""
TODO: filter out highways
"""
import os.path
import re

import networkx as nx
import osmnx as ox
import numpy as np

network_type = "all"

places = ["Englischer Garten", "Isarinsel Oberföhring"]

simplify=False

fname = f"data/{network_type}-simplify{simplify}.graphml"

cf = '[!"highway"]'

ox.config(use_cache=True)

if not os.path.isfile(fname):
    G = ox.graph_from_place(places, network_type=network_type, retain_all=True, truncate_by_edge=True, simplify=simplify, custom_filter=cf)
    ox.save_graphml(G, filepath=fname)

G = ox.load_graphml(filepath=fname)
#G = ox.graph_from_place(places, network_type=network_type, retain_all=True, truncate_by_edge=True, simplify=False)
#G = ox.graph_from_place(places, network_type=network_type, retain_all=True, truncate_by_edge=True, simplify=True)

# fig, ax = ox.plot_graph(G)
# fig.show()



# # what sized area does our network cover in square meters?
# G_proj = ox.project_graph(G)
# nodes_proj = ox.graph_to_gdfs(G_proj, edges=False)
# graph_area_m = nodes_proj.unary_union.convex_hull.area
# print(graph_area_m)

# # show some basic stats about the network
# a = ox.basic_stats(G_proj, area=graph_area_m, clean_int_tol=15)
# print(a)

# taken from google maps
engga_stusta_north = (11.614826, 48.182839)
engga_stusta_south = (11.612391, 48.181151)

stusta_north_node = ox.nearest_nodes(G, *engga_stusta_north)
stusta_south_node = ox.nearest_nodes(G, *engga_stusta_south)







from shapely.geometry import Point
import geopandas
# p = Point((points[0][1],points[0][0]))
# s = geopandas.GeoSeries({
#     "osmid"        : 111,
#     "y"            : points[0][0],
#     "x"            : points[0][1],
#     "street_count" : 1,
#     "highway"      : None,
#     "geometry"     : p})

# gdf_nodes = gdf_nodes.append(s, ignore_index=True)
# G = ox.utils_graph.graph_from_gdfs(gdf_nodes, gdf_edges, graph_attrs=G.graph)

pattern = re.compile(r'<trkpt lat="([\d.]+)*" lon="([\d.]+)">')
content = open("example/2021-08-13T09:52:49+00:00_7296485764.gpx").read()
points = [(float(a),float(b)) for a,b in pattern.findall(content)]
route = [ox.nearest_nodes(G, p[1], p[0]) for p in points]

prev = None

route = [prev:=v for v in route if prev!=v]

gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

#print(gdf_nodes.loc["x"])

# ymin = gdf_nodes["y"].min()
# ymax = gdf_nodes["y"].max()

def color_node(x):
    #return x in [stusta_north_node, stusta_south_node, 111]
    #return gdf_nodes.loc[x]["y"] < (ymin + (ymax - ymin) * 0.48)
    #return 0
    return x in route



nx.set_node_attributes(G, {x: float(color_node(x)) for x in gdf_nodes.index}, name='is_stusta')
nc = ox.plot.get_node_colors_by_attr(G, attr='is_stusta')

#fig, ax = ox.plot_graph_route(G, route)
ox.plot_graph(G, node_color=nc)
#fig.show()
