# Description: This script downloads the census data for the states we are interested in.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org
# %%
import io
from pathlib import Path
from typing import Annotated
from zipfile import ZipFile

from pyarrow import parquet
import osgeo  # noqa
import censusdata
import pandas as pd
from pytask import Product, mark, task
from rasterio.merge import merge as rio_merge
from tqdm import tqdm

from rti_synth_pop.config import CENSUS_COLS, STATE_INFO, SURVEY, YEAR, raw_data_dir


# %%
def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr] = {
            "st_fips": st_fips,
            "output_path": raw_data_dir / f"{st_fips}_{SURVEY}_{YEAR}.parquet",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_download_census_data(
        st_fips: str, output_path: Annotated[Path, Product]
    ) -> None:
        """Download all census columns needed for IPF by state
        this will download the block group level data

        st_fips: str = state fips code. 2 digits. As a string
        output_path: Path = path to output parquet file

        Returns: None
        """

        cen_geo_cnty = censusdata.geographies(
            censusdata.censusgeo([("state", str(st_fips)), ("county", "*")]),
            SURVEY,
            YEAR,
        )
        df_list = []
        for cnty_cen_geo in tqdm(list(cen_geo_cnty.values())):
            cen_geo = censusdata.censusgeo(
                list(cnty_cen_geo.geo) + [("block group", "*")]
            )
            df = (
                censusdata.download(src=SURVEY, year=YEAR, geo=cen_geo, var=CENSUS_COLS)
                .assign(
                    GEOID=lambda df: df.index.map(
                        lambda x: "".join([y[1] for y in x.geo])
                    ),
                )
                .set_index("GEOID")
            )
            df_list.append(df)
        output_df = pd.concat(df_list)
        output_df.to_parquet(output_path)


# %%
@mark.persist
@task(id="state_fips")
def test_download_state_fips(
    url: str = (
        "https://www2.census.gov/geo/docs/reference/codes2020/national_state2020.txt"
    ),
    output_path: Annotated[Path, Product] = raw_data_dir / "national_state2020.parquet",
) -> None:
    """
    This downloads a table of the full list of state codes and fips if we wanted to run
    the entire country at once. Currently we list the states in config.py we want to do
    to avoid huge computation.
    """
    st_fips_df = pd.read_table(url, sep="|").assign(
        STATEFP=lambda df: df.STATEFP.astype(str).str.zfill(2)
    )
    st_fips_df.to_parquet(output_path)


# %%


@mark.persist
@task(id="merge_landscan")
def task_merge_landscan(
    input_path: str = raw_data_dir / f"landscan-usa-{YEAR}-night-assets.zip",
    output_path: Annotated[Path, Product] = raw_data_dir
    / f"landscan-usa-{YEAR}-merged-night.tif",
) -> None:
    """extract landscan population rasters and merge them together

    NOTE: the landscan data must be downloaded manually from their website and the zip
    file should be put in the raw data folder. The year of the data downloaded needs
    to match the year of the synthetic population.

    https://landscan.ornl.gov/

    input_path: zip folder downloaded from landsan
    output_path: tif file of merged population counts.
    """

    with ZipFile(input_path) as z1:
        zfiledata = io.BytesIO(z1.read(f"landscan-usa-{YEAR}-night.zip"))
        with ZipFile(zfiledata) as z2:
            file_list = [
                f"landscan-usa-{YEAR}-conus-night.tif",
                f"landscan-usa-{YEAR}-ak-night.tif",
                f"landscan-usa-{YEAR}-hi-night.tif",
            ]
            for file in file_list:
                z2.extract(file, raw_data_dir)

    file_path_list = [raw_data_dir / file for file in file_list]

    _ = rio_merge(file_path_list, dst_path=output_path)

    [file.unlink() for file in file_path_list]


# %%
