# English Garden Speedrun (100% Glitchless)


## What is?

The goal of this project to stay fit and gamify the (sometimes boring) running activities by adding a small challenge to it.
The idea is to run all available paths in the [English Garden](https://en.wikipedia.org/wiki/Englischer_Garten), a pretty big park in the heart of Munich.

The scripts in this repository will analyze your gpx files and match it with data from [OpenStreetMap](https://www.openstreetmap.org) to visualize your runned paths and give you some stats about your progress.

This project can be quite easily adapted for other parks/areas. Note however, that some aspects like the highway type blacklist were especially fine-tuned on the English Garden (to avoid running on the Autobahn).


## Map Matching

Each gpx file recorded by your GPS device (phone, smart watch, ...) will contain a list of gps coordinates with timestamps that were recorded during your run.
At the same time, using OpenSteetMap and [osmnx](https://github.com/gboeing/osmnx), we derived a graph data structure (nodes and edges) with coordinate information.

To track your progress, we now need to derive the runned path (a list of edges) from the list of points (e.g. by matching each measured point to an edge in the graph).


### Problems

There are multiple difficulties with getting a good map match:

* **GPS accuracy**: Could be closer to wrong path than actual path
* **Measurement frequency**: Small edges not matched
* **Intersections**: Could match wrong edge
* **Route consistency**: Route should ideally be connected, and in correct order
* **Off-route runs**: Like running through the middle of the field. These shouldn't be matched ideally.

There is a lot of research into map matching and there exist sophisticated algorithms using assumptions on route connectivity and human behavior together with markov chain models to match sensible routes.


### False Negatives vs. False Positives

As this is a classification problem (is a specific edge in the path that was run), we are interested to keep both the *false-positive-rate* and the *false-negative-rate* low.
And as usually, because of the inaccuracies in the measurements, these two rates usually trade off against each other.

For this project, it seems more important to keep the false-positive-rate low (not classify non-runned edges as runned edges) for the following reasons:

* Classifying non-runned edges as "runned" is cheating the 100% challenge
* As they usually represent gaps in the runned route, missing edges can be fixed manually easier than edges that were wrongly classified as "runned"
* Missing edges can be strategically re-runned (e.g. do a short pause at the edge so that there are more gps points, ...)



### Dead-ends

* Using only `osmnx.get_nearest_edges`: Wrong classifications due to GPS accuracy and intersection problems
* Using only [mapbox](https://www.mapbox.com/) for map matching: does not contain edges/osmids




### How it's done here

0. (Optionally) use mapbox map matching API to set gps points onto closest road
1. Use valhalla to get way_id of osm way
2. Look in osmnx graph which edges are part of the way
3. Choose edge with smallest distance to the point
