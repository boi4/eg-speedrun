#!/usr/bin/env python3
import argparse
import json
import os
import os.path
import sys
import time
from datetime import datetime
from pprint import pprint

import folium
import folium.plugins
import matplotlib.pyplot as plt
import osmnx as ox
from tqdm import tqdm

from gpstrack import GPSTrack,my_hash

DEFAULT_PLOTS_DIR = "plots"
PLACES = ["Englischer Garten", "Isarinsel Oberföhring", "Wehranlage Oberföhring"]

# don't put regex stuff in here

HIGHWAY_BLACKLIST = ["service", "trunk", "trunk_link"]
HIGHWAY_WHITELIST = [ht for ht in ['footway',
 'cycleway',
 'residential',
 'steps',
 'service',
 'unclassified',
 'track',
 'trunk_link',
 'trunk',
 'path',
 'bridleway'] if ht not in HIGHWAY_BLACKLIST]

custom_filter = f'[highway~"^({"|".join(list(HIGHWAY_WHITELIST))})$"]'

#network_type = "all"

place_str = "@".join(PLACES + [custom_filter])

# we use this file for caching the map data
FNAME = f"data/{my_hash(place_str)}.graphml"

TO_RUN_COLOR = "#d0d0d0"
BGCOLOR = "#333333"




def save_plot(fig, plotname, plotsdir, extension="pdf", **kwargs):
    fig.savefig(f"{plotsdir}/{plotname}.{extension}", format=extension,
                bbox_inches="tight", **kwargs)







def create_parser():
    parser = argparse.ArgumentParser(description="""
Plot graphs in English Garden of past tracks.
""".strip())

    parser.add_argument("--valhalla", default=None, required=False, help="URL to basis of valhalla api endpoint, can also be defined by setting VALHALLA_URL env. var")
    parser.add_argument("--gpxdir", "-d", required=True, help="The directory containing the gpx files for your runs.")
    parser.add_argument("--outdir", "-o", default=DEFAULT_PLOTS_DIR, help="The directory where the plots are produced in.")
    parser.add_argument("--cachefile", "-c", default=None, help="Path to a file where map matching results are cached. File will be created if it does not exist yet")
    parser.add_argument("--debug", default=False, action="store_true", help="The directory where the plots are produced in.")
    parser.add_argument("--filter-date", default=0, type=int, help="Optional UNIX timestamp. Consider only gps tracks recorded later or equal of that timestamp")
    parser.add_argument("--filter-name", default=None, help="Consider only gpx files with that name.")

    return parser

def setup(args):
    # caching is done by this program itself
    ox.config(use_cache=False)

    if args.valhalla is None and "VALHALLA_URL" not in os.environ:
        print("--valhalla flag or VALLHALLA_URL environment variable have to be set")
        sys.exit(1)

    # fetch graph
    if not os.path.isfile(FNAME):
        print(f"Couldn't find cache file {FNAME} - Downloading map...")
        G = ox.graph_from_place(PLACES, custom_filter=custom_filter, retain_all=True,
                                truncate_by_edge=False, simplify=False)
        ox.save_graphml(G, filepath=FNAME)

    # setup cachefile for valhalla requests
    if args.cachefile is not None:
        GPSTrack.set_cachefile(args.cachefile)


def load_relevant_tracks(gpxdir, filter_date, filter_name=None):
    gpxfiles = [os.path.join(gpxdir, f) for f in os.listdir(gpxdir) if f.endswith(".gpx")]

    print(f"Found {len(gpxfiles)} gpxfiles")
    print(f"Parsing gpx files...")
    tracks_tocheck = [GPSTrack.from_gpx(f) for f in tqdm(gpxfiles)]
    print(f"Parsing done.")


    # filter tracks
    tracks = []
    for track in tracks_tocheck:
        if filter_name is not None and track.name != filter_name:
            print(f"Track {track.filepath} - '{track.name}' is not called '{filter_name}', ignoring")
            continue

        if len(track.points) == 0:
            print(f"Track {track.filepath} - '{track.name}' has no points, ignoring")
            continue

        if track.date < filter_date:
            print(f"Track {track.filepath} - '{track.name}' earlier than {filter_date}, ignoring")
            continue

        tracks.append(track)

    return tracks


def plot_html_by_highway(G, fname):
    gdf_edges = ox.graph_to_gdfs(G, nodes=False)
    hwytypes = list(set(gdf_edges["highway"].tolist()))

    # define the colors to use for different edge types
    colorlist = [
            'skyblue',
            'paleturquoise',
            'orange',
            'sienna',
            'lightgreen',
            'grey',
            'lightskyblue'
            'yellow',
            'magenta',
            'cyan',
            'red',
            'green',
            'blue',
            'black',
        ]
    hwy_colors = {hwytypes[i]:colorlist[i] for i in range(len(hwytypes))}

    # return edge IDs that do not match passed list of hwys
    def find_edges(G, hwys):
        edges = []
        for u, v, k, data in G.edges(keys=True, data='highway'):
            check1 = isinstance(data, str) and data not in hwys
            check2 = isinstance(data, list) and all([d not in hwys for d in data])
            if check1 or check2:
                edges.append((u, v, k))
        return set(edges)


    # first plot all edges that do not appear in hwy_colors's types
    G_tmp = G.copy()
    m = ox.plot_graph_folium(G_tmp, weight=5, color='white')

    # then plot each edge type in hwy_colors one at a time
    for hwy, color in hwy_colors.items():
        G_tmp = G.copy()
        G_tmp.remove_edges_from(find_edges(G_tmp, [hwy]))
        if G_tmp.edges:
            m = ox.plot_graph_folium(G_tmp,
                                    graph_map=m,
                                    popup_attribute='highway',
                                    weight=5,
                                    color=color)
    m.save(fname)


def plot_html_debug(G, fname):
    G = ox.load_graphml(filepath=FNAME)
    G = ox.utils_graph.get_undirected(G)
    gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
    gdf_edges['summary'] = gdf_edges.apply(lambda x:
        f"{x['osmid']}, {x['highway']}, {x['access']}, {x['from']}, {x['to']}",
                                           axis=1)
    G_tmp = ox.graph_from_gdfs(gdf_nodes, gdf_edges)
    m = ox.plot_graph_folium(G_tmp,
                            tiles="CartoDB positron",
                            fit_bounds=True,
                            weight=3,
                            popup_attribute="summary")
    m.save(fname)



def main():

    parser = create_parser()
    args = parser.parse_args()

    setup(args)

    outdir = f"{args.outdir}/{int(time.time())}"
    print(f"Using {outdir} as the output directory")
    os.makedirs(outdir, exist_ok=True)


    # load tracks
    tracks = load_relevant_tracks(args.gpxdir,
                                  datetime.fromtimestamp(args.filter_date),
                                  args.filter_name)


    # load our graph
    G = ox.load_graphml(filepath=FNAME)

    # save whole graph as interactive html for debugging
    if args.debug:
        print("Generating debug maps...")
        plot_html_debug(G, f"{outdir}/english_garden_infos.html")
        print(f"Edge info html map done: {outdir}/english_garden_infos.html")
        plot_html_by_highway(G, f"{outdir}/english_garden_highway.html")
        print(f"Highway type html map done: {outdir}/english_garden_highway.html")


    # match tracks with edges
    print("Matching gps points to edges...")
    matched_tracks = []
    for track in tqdm(tracks):
        route = track.match_graph(G, args.valhalla)

        if route is None:
            print(f"Track {track.filepath} - '{track.name}' map matching failed")
        elif len(route) == 0:
            print(f"Track {track.filepath} - '{track.name}' not in English Garden, ignoring")
        else:
            matched_tracks.append((track, route))
    print("Matching done.")




    runned_edges = set(a for t in matched_tracks for a in t[1])
    to_run_edges = G.edges(keys=True) - runned_edges

    # edges will keep track of the color for each edge for static plot
    edges_color = ox.graph_to_gdfs(G, nodes=False)
    # default: to run -> gray
    edges_color["color"] = TO_RUN_COLOR

    G_to_run = G.copy()
    G_to_run.remove_edges_from(runned_edges)

    G_runned = G.copy()
    G_runned.remove_edges_from(to_run_edges)

    # m will be the folium.Map object for html visualization
    # plot to-run edges in gray
    print("Generating interactive html map of tracks...")
    m = ox.plot_graph_folium(G_to_run,
                             tiles="CartoDB positron",
                             fit_bounds=True,
                             weight=3,
                             color=TO_RUN_COLOR,
                             opacity=1.0)




    colors = plt.rcParams['axes.prop_cycle'].by_key()['color']

    for (i,t) in enumerate(tqdm(matched_tracks)):
        track,route = t

        # determine next color
        next_color = colors[i % len(colors)]

        # get graph with only the runned edges
        to_remove = set(e for e in G.edges if e not in route)
        G_track = G.copy()
        G_track.remove_edges_from(to_remove)

        # color edges in our color lookup
        edges_ran = G_track.edges(keys=True)
        edges_color.loc[edges_color.index.isin(edges_ran),"color"] = next_color

        # add route info for interactive html popup
        gdf_nodes, gdf_edges = ox.graph_to_gdfs(G_track)
        gdf_edges['route_info'] = f"{track.date.strftime('%Y-%m-%d')}"
        G_track = ox.graph_from_gdfs(gdf_nodes, gdf_edges)

        # add graph to folium map
        m = ox.plot_graph_folium(G_track,
                                 graph_map=m,
                                 weight=3,
                                 color=next_color,
                                 popup_attribute="route_info",
                                 opacity=1.0)

    # save folium html map
    m.save(f"{outdir}/map.html")
    print("Plotting done.")

    # folium.plugins.Fullscreen(
    #     position="topright",
    #     title="Expand",
    #     title_cancel="Exit Fullscreen",
    #     force_separate_button=True,
    # ).add_to(m)



    if args.debug:
        print("Plotting debug visualization with gps points included")
        # visualize gps points and matched points
        for (i,t) in enumerate(matched_tracks):
            track,route = t
            next_color = colors[i % len(colors)]
            cs = [folium.Circle(point, radius=2, opacity=0.5, color=next_color)
                    for point in track.points]
            for c in cs:
                c.add_to(m)

            cs = [folium.Circle(point, radius=2, color=next_color)
                    for point in track.matched_points]
            for c in cs:
                c.add_to(m)

        m.save(f"{outdir}/map-debug.html")
        print(f"Debug plotting done: {outdir}/map-debug.html")


    print("Creating static plot")
    # create and save static plot
    fig,ax = plt.subplots(facecolor=BGCOLOR)
    ax.set_facecolor(BGCOLOR)
    ox.plot_graph(G,
                  ax=ax,
                  edge_linewidth=1,
                  node_size=0,
                  edge_color=edges_color["color"].tolist(),
                  show=False
                  )
    save_plot(fig, "map", outdir)
    save_plot(fig, "map", outdir, extension="png", dpi=800)
    print("Static plot done")





    # statistics:
    #  - how much is the total length
    #  - how much did i run already (absolute value and percentage)
    #  - how much do i have to run yet (absolute value and percentage)
    #  - how much was run "unnecessarily" (absolute value) TODO
    # for each run:
    #  - date TODO
    #  - how much did i run in absolute values TODO
    #  - how much of the run were new routes (percentage) TODO
    #  - how much of total roads were "uncovered" (percentage) TODO


    edges_total = ox.graph_to_gdfs(G, nodes=False)
    edges_runned = ox.graph_to_gdfs(G_runned, nodes=False)
    edges_to_run = ox.graph_to_gdfs(G_to_run, nodes=False)

    total_length_meters = edges_total["length"].sum()
    runned_length_meters = edges_runned["length"].sum()
    to_run_length_meters = edges_to_run["length"].sum()

    runned_percentage = 100 * runned_length_meters / total_length_meters
    to_run_percentage = 100 * to_run_length_meters / total_length_meters

    number_of_runs = len(matched_tracks)

    stats = {
        "total_length_meters": total_length_meters,
        "runned_length_meters": runned_length_meters,
        "to_run_length_meters": to_run_length_meters,

        "runned_percentage": runned_percentage,
        "to_run_percentage": to_run_percentage,

        "number_of_runs": number_of_runs,
    }
    print("\n\n\nStatistics:")
    print("=========================================")
    pprint(stats)
    print("")

    # dump to file
    json.dump(stats, open(f"{outdir}/stats.json", "w"))
    print(f"Dumped statistics to {outdir}/stats.json")

    return locals()

if __name__ == "__main__":
   locvar = main()
   globals().update(locvar)
