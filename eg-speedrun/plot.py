import osmnx as ox



def map_save_highlight_edges(m, fname):
    """Add highlight edge on hover to folium/leaflet map
    and saves it to filename

    :param m: folium map
    :param fname: file path to save the file to
    """
    polyline_names = [k for k in m._children.keys() if k.startswith("poly_line")]
    #polylines = [m._children[k] for k in m._children.keys() if k.startswith("poly_line")]

    js = f'var polylines = [' + ','.join(polyline_names) + ']'
    js += """
polylines.forEach(polyline => {
    polyline.on('mouseover', function(e) {
        var layer = e.target;

        origcolor = layer['options']['fillColor'];
        layer['origcolor'] = origcolor;

        layer.setStyle({
            color: 'red',
        });
    });
    polyline.on('mouseout', function(e) {
        var layer = e.target;

        if ('origcolor' in layer) {
            layer.setStyle({
                color: layer['origcolor'],
            });
        }
    });
}
)
"""
    m.save(fname)

    with open(fname) as f:
        content = f.read()

    content = content.replace("</script>", js + "</script>")

    with open(fname, "w") as f:
        f.write(content)



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
    map_save_highlight_edges(m, fname)



def plot_html_debug(G, fname, graphml_cache):
    G = ox.load_graphml(filepath=graphml_cache)
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
    map_save_highlight_edges(m, fname)
