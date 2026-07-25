from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString
from tqdm.auto import tqdm

MILES_TO_METERS = 1609.344
MAX_DISTANCE_M = 5 * MILES_TO_METERS
MIN_AREA_RATIO = 0.90
MIN_ACRES = 6.0


def pick_area_field(gdf: gpd.GeoDataFrame) -> str:
    if "acres" in gdf.columns:
        series = gdf["acres"]
        if series.notna().any() and (series > 0).any():
            return "acres"

    gdf["area_acres_calc"] = gdf.geometry.area / 4046.8564224
    return "area_acres_calc"


def main() -> None:
    print("Stage 1/7: Reading source data")

    base_dir = Path(__file__).resolve().parent
    src_gpkg = base_dir / "layers" / "Lakes-30MileBuffer-NotNull-NotUnamed-1AcreorMore.gpkg"
    out_dir = base_dir / "db"
    out_dir.mkdir(exist_ok=True)
    out_gpkg = out_dir / "lake_similarity_5mi_10pct_min6ac.gpkg"

    lakes = gpd.read_file(src_gpkg, layer=0).copy()

    if lakes.crs is None:
        raise ValueError("Input layer has no CRS. Assign CRS before distance analysis.")
    if lakes.crs.is_geographic:
        lakes = lakes.to_crs(26915)

    if "objectid" in lakes.columns:
        lakes["lake_id"] = lakes["objectid"].astype("int64")
    else:
        lakes["lake_id"] = lakes.index.astype("int64")

    area_field = pick_area_field(lakes)
    lakes["area_acres"] = lakes[area_field].astype(float)

    print("Stage 2/7: Applying minimum acreage filter")
    lakes = lakes[lakes["area_acres"] >= MIN_ACRES].copy()
    print(f"Lakes after >= {MIN_ACRES} acre filter: {len(lakes)}")

    if lakes.empty:
        print("No lakes passed the minimum acreage filter.")
        return

    print("Stage 3/7: Building centroids and 5-mile buffers")
    cent = gpd.GeoDataFrame(
        lakes[["lake_id", "area_acres"]].copy(),
        geometry=lakes.geometry.centroid,
        crs=lakes.crs,
    )

    buffers = gpd.GeoDataFrame(
        cent[["lake_id"]].copy(),
        geometry=cent.geometry.buffer(MAX_DISTANCE_M),
        crs=cent.crs,
    )

    print("Stage 4/7: Spatial join for candidate lake pairs")
    pairs = gpd.sjoin(
        cent[["lake_id", "area_acres", "geometry"]],
        buffers[["lake_id", "geometry"]],
        how="inner",
        predicate="intersects",
        lsuffix="a",
        rsuffix="b",
    )

    pairs = pairs.rename(columns={"lake_id_a": "id_a", "lake_id_b": "id_b"})
    pairs = pairs[pairs["id_a"] < pairs["id_b"]].copy()

    if pairs.empty:
        print("No candidate pairs found within 5 miles.")
        return

    print("Stage 5/7: Filtering by area similarity (+/-10%)")
    area_lookup = cent.set_index("lake_id")["area_acres"]
    geom_lookup = cent.set_index("lake_id").geometry

    pairs["area_a"] = pairs["area_acres"]
    pairs["area_b"] = pairs["id_b"].map(area_lookup)

    min_area = np.minimum(pairs["area_a"], pairs["area_b"])
    max_area = np.maximum(pairs["area_a"], pairs["area_b"])
    pairs["area_ratio"] = min_area / max_area
    pairs = pairs[pairs["area_ratio"] >= MIN_AREA_RATIO].copy()

    if pairs.empty:
        print("No pairs passed the area similarity filter.")
        return

    print("Stage 6/7: Computing distances, scores, and edge geometry")
    pair_ids = list(zip(pairs["id_a"].to_numpy(), pairs["id_b"].to_numpy()))

    pairs["distance_m"] = [
        geom_lookup.loc[a].distance(geom_lookup.loc[b])
        for a, b in tqdm(pair_ids, total=len(pair_ids), desc="Computing distances")
    ]

    pairs["distance_score"] = 1 - (pairs["distance_m"] / MAX_DISTANCE_M)
    pairs["size_score"] = (pairs["area_ratio"] - MIN_AREA_RATIO) / (1 - MIN_AREA_RATIO)
    pairs["distance_score"] = pairs["distance_score"].clip(0, 1)
    pairs["size_score"] = pairs["size_score"].clip(0, 1)
    pairs["match_score"] = (0.5 * pairs["distance_score"] + 0.5 * pairs["size_score"]).clip(0, 1)

    pairs["geometry"] = [
        LineString([geom_lookup.loc[a], geom_lookup.loc[b]])
        for a, b in tqdm(pair_ids, total=len(pair_ids), desc="Building edge geometries")
    ]

    edges = gpd.GeoDataFrame(
        pairs[
            [
                "id_a",
                "id_b",
                "area_a",
                "area_b",
                "area_ratio",
                "distance_m",
                "distance_score",
                "size_score",
                "match_score",
                "geometry",
            ]
        ].copy(),
        geometry="geometry",
        crs=cent.crs,
    )

    matched_ids = set(edges["id_a"]).union(set(edges["id_b"]))
    matched_lakes = lakes[lakes["lake_id"].isin(matched_ids)].copy()
    matched_centroids = cent[cent["lake_id"].isin(matched_ids)].copy()

    polygon_cols = ["lake_id", "area_acres", "geometry"]
    if "map_label" in matched_lakes.columns:
        polygon_cols.insert(1, "map_label")
    matched_lakes_out = matched_lakes[polygon_cols].copy()

    print("Stage 7/7: Writing output GeoPackage layers")
    matched_lakes_out.to_file(out_gpkg, layer="matched_lakes_polygons", driver="GPKG")
    matched_centroids.to_file(out_gpkg, layer="matched_lakes_centroids", driver="GPKG")
    edges.to_file(out_gpkg, layer="matched_lake_edges", driver="GPKG")

    print(f"Input lakes after filter: {len(lakes)}")
    print(f"Matched edges: {len(edges)}")
    print(f"Matched lakes: {len(matched_lakes_out)}")
    print(f"Wrote output to: {out_gpkg}")


if __name__ == "__main__":
    main()