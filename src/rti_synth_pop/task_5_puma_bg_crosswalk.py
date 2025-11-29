# Description: This script creates a crosswalk between PUMA and block groups.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
from pathlib import Path
from typing import Annotated

import geopandas as gpd
import pandas as pd
from pytask import Product, mark, task

from rti_synth_pop.config import STATE_INFO, YEAR, interim_data_dir, raw_data_dir


# %%
def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr + "_pums_bg_crosswalk"] = {
            "input_pums_path": raw_data_dir / f"tl_{YEAR}_{st_fips}_puma10.zip",
            "input_bg_path": raw_data_dir / f"tl_{YEAR}_{st_fips}_bg.zip",
            "output_path": interim_data_dir
            / f"{st_fips}_{YEAR}_pums_2_bg_crosswalk.parquet",
        }
    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%

for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_pums_bg_crosswalk(
        input_pums_path: Path,
        input_bg_path: Path,
        output_path: Annotated[Path, Product],
    ) -> None:
        """Identify which PUMA each block group falls into

        input_pums_path: Path = The path to the PUMS geographic data.
        input_bg_path: Path = The path to the census block group geographic data.
        output_path: Path = path to output parquet file

        Returns: None
        """
        # %%
        puma_gdf = gpd.read_file(input_pums_path)
        bg_gdf = gpd.read_file(input_bg_path)
        # NOTE: setting the geometry as the representative points ensures that we get a
        # block group to one puma relationship. Inexact polygons give us many
        # pumas for a single block group. Representative point gives us a point that
        # falls within the polygon, and the sjoin gives us results for all block groups.
        # TODO: this should futher be tested. Currently I've worked this out for NC.
        bg_gdf["geometry"] = bg_gdf.representative_point()
        # %%
        crosswalk = (
            puma_gdf[["GEOID10", "geometry"]]
            .sjoin(bg_gdf[["GEOID", "geometry"]])
            .rename(columns={"GEOID10": "PUMA_GEOID", "GEOID": "BG_GEOID"})
            .drop(columns=["geometry", "index_right"])
        )

        bg_all_ones = (crosswalk["BG_GEOID"].value_counts() == 1).all()
        all_geoids_in_result = bg_gdf["GEOID"].isin(crosswalk["BG_GEOID"]).all()
        if not all([bg_all_ones, all_geoids_in_result]):
            Warning("NOT ALL BLOCK GROUPS HAVE RESULTS IN CROSSWALK")

        crosswalk.to_parquet(output_path)
