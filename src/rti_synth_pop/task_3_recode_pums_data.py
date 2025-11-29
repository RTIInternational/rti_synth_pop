# Description: This script recodes the PUMS data to match the synthetic population data
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
from pathlib import Path
from typing import Annotated
from zipfile import ZipFile

import pandas as pd
from pytask import Product, mark, task

from rti_synth_pop.config import (
    STATE_INFO,
    YEAR,
    age_map,
    ethnicity_map,
    income_map,
    interim_data_dir,
    pums_col_list,
    race_map,
    raw_data_dir,
)

# TODO: turn this into a task
# fold all this information into the larger dictionary in the config file.
# look at how to change config files for different years
# The steps that will charge are:
#   1. which columns to download and how ar
#   2. the form of the queries based on the different columns
#   3. PUMS household data column names
#   The config file could take a request of "get dictionary based on the year" so the
#   top key would be the year and that retuns all the config things we need. Keep
#   pulling from the existing dictionaries in the OG SP code as example.


def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr] = {
            "input_path": raw_data_dir / f"csv_h{st_abbr.lower()}_{YEAR}.zip",
            "input_persons_path": raw_data_dir / f"csv_p{st_abbr.lower()}_{YEAR}.zip",
            "output_path": interim_data_dir / f"csv_h{st_fips}_{YEAR}_recoded.parquet",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_recode_pums_data(
        input_path: Path,
        input_persons_path: Path,
        output_path: Annotated[Path, Product],
    ) -> None:
        """Read in and prep pums household data for IPF

        input_path: Path = The path to the PUMS Household zip
        input_persons_path: Path = The path to the PUMS Person zip
        output_path: Path = path to output parquet file

        Returns: None
        """

        # read in the raw PUMS household data
        # subset to the columns we need for IPF and selection
        # 2021 added head of household columns to the household file
        # for earlier years we need the persons file
        if YEAR < 2021:
            # need to read in the pums persons file and pull out sporder 1
            pums_p_df = pd.concat(
                [
                    pd.read_csv(
                        ZipFile(input_persons_path).open(i),
                        usecols=["SERIALNO", "SPORDER", "RAC1P", "AGEP", "HISP"],
                    )
                    for i in ZipFile(input_persons_path).namelist()
                    if i.endswith(".csv")
                ],
                ignore_index=True,
            ).rename(
                columns={
                    "RAC1P": "HHLDRRAC1P",
                    "HISP": "HHLDRHISP",
                    "AGEP": "HHLDRAGEP",
                }
            )
            pums_p_df = pums_p_df.loc[pums_p_df["SPORDER"].astype(int) == 1].drop(
                columns=["SPORDER"]
            )
            pums_h_df = pd.concat(
                [
                    pd.read_csv(
                        ZipFile(input_path).open(i),
                        usecols=["SERIALNO", "PUMA", "ST", "HINCP", "NP"],
                    )
                    for i in ZipFile(input_path).namelist()
                    if i.endswith(".csv")
                ],
                ignore_index=True,
            )
            pums_df = pums_h_df.merge(pums_p_df, on=["SERIALNO"], how="left").dropna(
                subset=pums_col_list[1:], how="all"
            )

        else:
            pums_df = pd.concat(
                [
                    pd.read_csv(
                        ZipFile(input_path).open(i),
                        usecols=["SERIALNO", "PUMA", "ST"] + pums_col_list,
                    )
                    for i in ZipFile(input_path).namelist()
                    if i.endswith(".csv")
                ],
                ignore_index=True,
            ).dropna(subset=pums_col_list[1:], how="all")

        pums_recode = (
            # remove households reporting 0 people
            pums_df.query("NP > 0")
            # drop rows that are missing values
            # NOTE: NP is always filled. The other 4 base columns appear to be missing
            # all their data together. This was verified using:
            # import missingno
            # missingno.matrix(pums_df[pums_col_list])
            # missingno.heatmap(pums_df[pums_col_list])
            .dropna(subset=pums_col_list[1:], how="all")
            # recode the data to match out synthetic population values.
            .assign(
                size=lambda df: df["NP"]
                .apply(lambda x: "7+" if x >= 7 else str(x))
                .astype("category")
                .cat.as_ordered(),
                race=lambda df: df["HHLDRRAC1P"]
                .fillna(3)
                .replace(race_map)
                .astype("category"),
                income=lambda df: income_map(df["HINCP"]),
                age=lambda df: age_map(df["HHLDRAGEP"]),
                ethnicity=lambda df: ethnicity_map(df["HHLDRHISP"]),
                PUMA_GEOID=lambda df: df["ST"].astype(str).str.zfill(2)
                + df["PUMA"].astype(str).str.zfill(5),
                # ethnicity=lambda df: df["HHLDRHISP"].apply(lambda x: 1 if x == 1 else 0),
            )
            # now remove the original columns
            .drop(columns=pums_col_list + ["ST", "PUMA"])
            # make the serialno a str
            # NOTE: I ignore the mixed column type on read of the PUMS csvs, so this
            # fixes that before the write.
            .astype({"SERIALNO": str})
        )
        pums_recode.to_parquet(output_path)
