def get_osm_data():
    import pandas as pd
    from pathlib import Path
    import geopandas as gpd
    from shapely.geometry import shape, Point, Polygon
    import json


    listings_dir = Path("/opt/airflow/data/properties_for_each_brokerage")
    output_bucket = Path("/opt/airflow/data/additional_property_info")
    data_dir = Path("/opt/airflow/data")

    def get_all_properties():
        # Get all csv files in listings_dir and combine into a single dataframe
        all_property_csvs = [pd.read_csv(file) for file in listings_dir.glob("*.csv")]
        all_listings_df = pd.concat(all_property_csvs, ignore_index=True)
        return all_listings_df

    all_listings_df = get_all_properties().head(5) ##################### .head(5) For testing #####################

    businesses_gdf = gpd.read_file(data_dir / "businesses/edmonton_businesses.geojson")
    businesses_gdf = gpd.GeoDataFrame(businesses_gdf, geometry='geometry', crs="EPSG:4326")

    amenities_gdf = gpd.read_file(data_dir / "amenities/edmonton_amenities.geojson")
    amenities_gdf = gpd.GeoDataFrame(amenities_gdf, geometry='geometry', crs="EPSG:4326")

    all_listings_df['geometry'] = all_listings_df.apply(
        lambda row: Point(row['longitude'], row['latitude']), axis=1
    )
    properties_gdf = gpd.GeoDataFrame(all_listings_df, geometry='geometry', crs="EPSG:4326")

    businesses_gdf = businesses_gdf.to_crs("EPSG:32612")
    amenities_gdf = amenities_gdf.to_crs("EPSG:32612")
    properties_gdf = properties_gdf.to_crs("EPSG:32612")

    # Create a spatial index for businesses and amenities
    businesses_sindex = businesses_gdf.sindex
    amenities_sindex = amenities_gdf.sindex

    def find_nearby_businesses(point, businesses_gdf, businesses_sindex, radius=1000):
        # Find businesses within the bounding box of the radius
        possible_matches_index = list(businesses_sindex.intersection(point.buffer(radius).bounds))
        possible_matches = businesses_gdf.iloc[possible_matches_index]
        # Filter for exact distance (in meters)
        nearby_businesses = possible_matches[possible_matches.distance(point) <= radius]
        return nearby_businesses

    def find_nearby_amenities(point, amenities_gdf, amenities_sindex, radius=1000):
        # Find amenities within the bounding box of the radius
        possible_matches_index = list(amenities_sindex.intersection(point.buffer(radius).bounds))
        possible_matches = amenities_gdf.iloc[possible_matches_index]
        # Filter for exact distance (in meters)
        nearby_amenities = possible_matches[possible_matches.distance(point) <= radius]
        return nearby_amenities

    osm_data_dict = {"properties": {}}

    for idx, row in properties_gdf.iterrows():
        uuid = row['uuid']

        property_dict = {
            "uuid": uuid
        }

        # Find nearby businesses
        property_point = Point(row['longitude'], row['latitude'])
        property_point = gpd.GeoSeries([property_point], crs="EPSG:4326").to_crs("EPSG:32612").iloc[0]
        nearby_businesses = find_nearby_businesses(property_point, businesses_gdf, businesses_sindex)
        property_dict["nearby_businesses"] = []

        for _, business in nearby_businesses.iterrows():
            if isinstance(business["geometry"], Point):
                latitude = business["geometry"].y
                longitude = business["geometry"].x
            elif isinstance(business["geometry"], Polygon):
                centroid = business["geometry"].centroid
                latitude = centroid.y
                longitude = centroid.x
            else:
                continue

            if business["shop"] is not None:
                business_type = business["shop"]
            elif business["amenity"] is not None:
                business_type = business["amenity"]
            elif "healthcare" in business["tags"]:
                business_type = "Healthcare"
            else:
                business_type = None

            property_dict["nearby_businesses"].append({
                "latitude": latitude,
                "longitude": longitude,
                "name": business['name'],
                "type": business_type,
            })
    

        # Find nearby amenities
        nearby_amenities = find_nearby_amenities(property_point, amenities_gdf, amenities_sindex)
        property_dict["nearby_amenities"] = []
        
        for _, amenity in nearby_amenities.iterrows():
            if amenity["amenity"] == "place_of_worship":
                continue
            else:
                if isinstance(amenity["geometry"], Point):
                    latitude = amenity["geometry"].y
                    longitude = amenity["geometry"].x
                elif isinstance(amenity["geometry"], Polygon):
                    centroid = amenity["geometry"].centroid
                    latitude = centroid.y
                    longitude = centroid.x
                else:
                    continue

                if amenity["amenity"] is not None:
                    amenity_type = amenity["amenity"]
                elif amenity["leisure"] is not None:
                    amenity_type = amenity["leisure"]
                elif amenity["tags"] is not None and "man_made" in amenity["tags"]:
                    amenity_type = json.loads(amenity["tags"])["man_made"]
                elif amenity["building"] == "hotel":
                    amenity_type = amenity["building"]
                else:
                    amenity_type = None


                property_dict["nearby_amenities"].append({
                    "latitude": latitude,
                    "longitude": longitude,
                    "name": amenity['name'],
                    "type": amenity_type,
                })

        osm_data_dict["properties"][uuid] = property_dict

    with open(output_bucket / "osm_data_dict.json", "w") as f:
        json.dump(osm_data_dict, f, indent=4)