# Description: This script assigns coordinates to the synthetic population households.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
from pathlib import Path
from typing import Annotated

from pyarrow import parquet
import pandas as pd
import osgeo

import duckdb
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from joblib import Parallel, delayed
from pytask import Product, mark, task
from rasterio.features import shapes
from rasterio.mask import mask
from shapely import box
from tqdm.auto import tqdm
import threading

from rti_synth_pop.config import (
    STATE_INFO,
    YEAR,
    interim_data_dir,
    raw_data_dir,
    processed_data_dir,
)

parallel = Parallel(
    n_jobs=250, require="sharedmem", prefer="threads", return_as="generator"
)

SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng()
# gpd.options.io_engine = "pyogrio"


def sample_points(record, bg_pop_arr, bg_transform, out_crs):

    geom = record.geometry
    household_count = record.household_count
    # if we don't have any households in the geometry, return None
    if household_count < 1:
        return None

    # if the pop raster has no data, but our synthpop has persons, we randomly
    # distribution them in the block group without a distribution.
    elif (np.sum(bg_pop_arr) == 0) | (bg_pop_arr.size == 0):
        bg_points = (
            gpd.GeoSeries(geom)
            .sample_points(household_count)
            .explode(ignore_index=True)
        )
    # if we have a pop distribution and households to assign points...
    else:
        # create an zero array to hold the household counts
        count_arr = np.zeros_like(bg_pop_arr)
        # calculate the probability of the household in a cell, normed to 1
        prob_arr = bg_pop_arr / bg_pop_arr.sum()

        # sample the number of households we need from the probability, get the cell
        # indexes. by default, replace = True so a high prob cell could get selected
        # many times
        r_idx, c_idx = np.unravel_index(
            RNG.choice(prob_arr.size, size=household_count, p=prob_arr.flatten()),
            prob_arr.shape,
        )

        # for each of the selected sample cells, add 1 to it.
        for r, c in zip(r_idx, c_idx):
            count_arr[r, c] += 1

        # transform the cells to polygons.
        # Assign a unique index array, make it the shape of our input raster. For any
        # cell with no counts, make that 0. Rasterio will merge neighbor cells with same
        # values, so any cells without counts will get merged together. This greatly
        # reduces the number of cell polygons that get made.
        idx_arr = np.array(range(1, count_arr.size + 1)).reshape(count_arr.shape)
        idx_arr_filtered = np.where(count_arr > 0, idx_arr, 0)
        idx_arr_filtered = idx_arr_filtered.astype(np.int32)

        results = [
            {"properties": {"cell_idx": v}, "geometry": s}
            for s, v in shapes(idx_arr_filtered, transform=bg_transform)
        ]
        # cell polygons are created and then clipped the boundary of the block group,
        # so partial cells on the edge of the block group are not full, but we will
        # generate points inside the partial area according to it's probability.
        cell_gdf = (
            gpd.GeoDataFrame.from_features(results, crs=out_crs)
            # remove the aggregated zero count polygon
            .query("cell_idx > 0")
            # assign the count of households we need in each cell
            .assign(cell_pop=count_arr[*np.where(count_arr)].ravel())
            .to_crs(out_crs)
            # clip to the geometry
            .clip(geom)
            # another check to only get cells with counts
            .query("cell_pop > 0")
            .astype({"cell_pop": int})
            .drop(columns="cell_idx")
        )
        # create a sample of points within each cell
        bg_points = cell_gdf.sample_points(size=cell_gdf["cell_pop"]).explode(
            ignore_index=True
        )
    return bg_points


def generate_params(st_info: list[tuple]) -> dict:
    id_to_kwargs = {}
    for st_abbr, st_fips in st_info:
        id_to_kwargs[st_abbr] = {
            # "serialno_path": interim_data_dir
            # / f"{st_fips}_household_synthpop_serialnos.parquet",
            "h_sp_path": interim_data_dir / f"{st_fips}_{YEAR}_households.parquet",
            "bg_geo_path": raw_data_dir / f"tl_{YEAR}_{st_fips}_bg.zip",
            "pop_raster_path": raw_data_dir / f"landscan-usa-{YEAR}-merged-night.tif",
            "points_output_path": interim_data_dir
            / f"{st_fips}_{YEAR}_household_points.parquet",
            "h_sp_w_xy_output_path": processed_data_dir
            / f"{st_abbr}_{YEAR}_households.parquet",
            "h_sp_w_geom_output_path": processed_data_dir
            / f"{st_abbr}_{YEAR}_households_w_geom.parquet",
        }
    return id_to_kwargs


_ID_TO_KWARGS = generate_params(STATE_INFO)
_ID_TO_KWARGS
# %%


for _id, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=_id, kwargs=kwargs)
    def task_assign_coordinates(
        h_sp_path: Path,
        bg_geo_path: Path,
        pop_raster_path: Path,
        points_output_path: Annotated[Path, Product],
        h_sp_w_xy_output_path: Annotated[Path, Product],
        h_sp_w_geom_output_path: Annotated[Path, Product],
    ) -> None:

        with rasterio.open(pop_raster_path) as src:
            raster_meta = src.meta
        raster_meta

        # this is a stand in for summing the households per block group that will come
        # out of the synthetic population.
        h_sp = (
            duckdb.execute(
                f"""
            SELECT blkgrp_fips as GEOID, hh_id
            FROM '{h_sp_path}'
            """
            )
            .df()
            .assign(GEOID=lambda df: df["GEOID"].astype(str).str.zfill(12))
            .set_index("hh_id")
        )
        h_sp
        household_count = h_sp.groupby("GEOID").size().rename("household_count")
        household_count

        bg_gdf = (
            gpd.read_file(bg_geo_path)
            .loc[:, ["GEOID", "COUNTYFP", "geometry"]]
            .to_crs(raster_meta["crs"])
            .set_index("GEOID")
            .join(household_count)
            .fillna({"household_count": 0})
            .astype({"household_count": int})
            # .query("household_count > 0")
        )
        bg_gdf.plot("household_count")

        sample_output = []
        with rasterio.open(pop_raster_path) as src:
            read_lock = threading.Lock()

            def get_pop_array(record, out_crs):
                # get the population count raster for that block group. all_touched will
                # give us cells who even touched the boundary. All edge cells will be
                # captured and clipped later
                with read_lock:
                    bg_pop_arr, bg_transform = mask(
                        src,
                        shapes=[record.geometry],
                        # all_touched=True,
                        crop=True,
                        nodata=0,
                        indexes=1,
                    )
                result = sample_points(record, bg_pop_arr, bg_transform, out_crs)
                return result

            for geoid, data in tqdm(h_sp.groupby("GEOID"), total=h_sp.GEOID.nunique()):
                bg_geom = bg_gdf.loc[geoid]
                points = get_pop_array(bg_geom, bg_gdf.crs)
                out_data = gpd.GeoDataFrame(data, geometry=points.values)
                sample_output.append(out_data)

            # benchmark: 3:59 minutes for Wake county, 591 records
            # about 1:25 for all of NC
            # sample_output = list(
            #     tqdm(
            #         parallel(
            #             delayed(get_pop_array)(row, bg_gdf.crs)
            #             for row in bg_gdf[gdf_mask].itertuples()
            #             # for row in bg_gdf.itertuples()
            #         ),
            #         # total=bg_gdf.shape[0],
            #         total=gdf_mask.sum(),
            #     )
            # )
        output_points = pd.concat(sample_output)

        output_points.assign(
            lon_4326=lambda df: df["geometry"].x, lat_4326=lambda df: df["geometry"].y
        ).to_parquet(points_output_path)

        # output_points.groupby("GEOID").size().rename("point_count").to_frame().join(
        #     bg_gdf
        # ).assign(diff=lambda df: df["household_count"] - df["point_count"]).query(
        #     "diff > 0"
        # )

        # NOTE: Why two different joins in the out? Well, duckdb is MUCH faster, but
        # I couldn't get it to write out the spatial stuff correctly. So this is an
        # open TODO if performance becomes an issue with the geo/pandas join & write
        # below.
        duckdb.execute(
            f"""
            COPY (
            SELECT sp.*, points.lon_4326, points.lat_4326
            FROM (SELECT * FROM '{h_sp_path}') as sp
            JOIN (SELECT * EXCLUDE geometry FROM '{points_output_path}') as points
            ON sp.hh_id = points.hh_id
            ) TO '{h_sp_w_xy_output_path}' (FORMAT PARQUET)
            """
        )

        gpd.read_parquet(points_output_path).join(
            pd.read_parquet(h_sp_path).set_index("hh_id")
        ).to_parquet(h_sp_w_geom_output_path)
