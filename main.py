from pathlib import Path
import json
import geopandas as gpd
import pandas as pd

def main():
    base_dir = Path(__file__).resolve().parent
    gpkg_path = base_dir / "layers" / "Lakes-30MileBuffer-NotNull-NotUnamed-1AcreorMore.gpkg"
    db_dir = base_dir / "db"
    db_dir.mkdir(exist_ok=True)

    # 1) Save layer-level metadata
    layers = gpd.list_layers(gpkg_path)
    if layers.empty:
        print("No layers found.")
        return
    layers.to_csv(db_dir / "gpkg_layers_metadata.csv", index=False)

    # 2) Read first layer by index and save schema metadata
    gdf = gpd.read_file(gpkg_path, layer=0)

    schema_df = pd.DataFrame({
        "column": gdf.columns,
        "dtype": [str(t) for t in gdf.dtypes]
    })
    schema_df.to_csv(db_dir / "layer0_schema.csv", index=False)

    # 3) Save a compact JSON summary
    summary = {
        "source_file": str(gpkg_path),
        "layer_index": 0,
        "row_count": int(len(gdf)),
        "column_count": int(len(gdf.columns)),
        "crs": str(gdf.crs),
        "geometry_type_counts": {
            str(k): int(v) for k, v in gdf.geom_type.value_counts(dropna=False).to_dict().items()
        }
    }

    with open(db_dir / "layer0_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("Saved metadata files to:", db_dir)

if __name__ == "__main__":
    main()