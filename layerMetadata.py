from pathlib import Path
import geopandas as gpd

def main():
    gpkg_path = (
        Path(__file__).resolve().parent
        / "layers"
        / "Lakes-30MileBuffer-NotNull-NotUnamed-1AcreorMore.gpkg"
    )

    # Read the GeoPackage file and list its layers
    layers = gpd.list_layers(gpkg_path)
    if layers.empty:
        print("No layers found in:", gpkg_path)
        return

    # Show Layer metadata
    print("Layers found in the GeoPackage:")
    print(layers)

    gdf = gpd.read_file(gpkg_path, layer=0)
    print(gdf.head())

if __name__ == "__main__":
    main()