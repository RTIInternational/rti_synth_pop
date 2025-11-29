# Description: This script generates complete synthetic population files.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
# %load_ext autoreload
# %autoreload 2

from pathlib import Path
from typing import Annotated
from zipfile import ZipFile

import pandas as pd
from pytask import Product, mark, task

from rti_synth_pop.config import (
    STATE_INFO,
    YEAR,
    category_maps,
    interim_data_dir,
    processed_data_dir,
    raw_data_dir,
    rename_synpop_h,
)

# %%


def derive_fips_codes(df: pd.DataFrame):
    """Derive higher level FIPS codes from block group level FIPS code.

    df: pd.DataFrame = A dataframe with blkgrp_fips column that will be edited in place.

    Returns: None
    """
    df["state_fips"] = df["blkgrp_fips"].apply(lambda x: x[:2])
    df["county_fips"] = df["blkgrp_fips"].apply(lambda x: x[:5])
    df["tract_fips"] = df["blkgrp_fips"].apply(lambda x: x[:-2])


# %%
def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr] = {
            "pums_h_path": interim_data_dir / f"csv_h{st_fips}_{YEAR}_recoded.parquet",
            "pums_p_path": raw_data_dir / f"csv_p{st_abbr.lower()}_{YEAR}.zip",
            "sampled_serialno_path": interim_data_dir
            / f"{st_fips}_{YEAR}_household_synthpop_serialnos.parquet",
            "output_path": interim_data_dir / f"{st_fips}_{YEAR}_households.parquet",
            "output_path_persons": processed_data_dir
            / f"{st_fips}_{YEAR}_persons.parquet",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    # @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_derive_synpop_files(
        pums_h_path: Path,
        pums_p_path: Path,
        sampled_serialno_path: Path,
        output_path: Annotated[Path, Product],
        output_path_persons: Annotated[Path, Product],
    ) -> None:
        """Generate complete synthetic population files.

        pums_h_path: Path = Path to cleaned Household PUMS file.
        pums_p_path: Path = Path to raw Person PUMS zip folder.
        sampled_serialno_path: Path = Path to PUMS sampled for population.
        output_path: Annotated[Path, Product] = Household-level synthetic population file.
        output_path_persons: Annotated[Path, Product] = Person-level synthetic population file.

        Returns: None
        """
        # %%
        # Get the matches generated in task 6
        all_matches_df = pd.read_parquet(sampled_serialno_path)
        pums_h_df = pd.read_parquet(pums_h_path)
        pums_h_df["PUMA_GEOID"] = pums_h_df["PUMA_GEOID"].astype(int)

        # %%
        # Merge onto the cleaned PUMS to get the complete household variables for
        # those serialno
        synthpop_df = all_matches_df.drop(columns=["expansion"]).merge(
            pums_h_df, on=["SERIALNO"], how="left"
        )

        # Cast variables as integers using category mapping
        for col in category_maps.keys():
            reverse_dict = {v: k for k, v in category_maps[col].items()}
            synthpop_df[col] = synthpop_df[col].apply(lambda x: reverse_dict[x])

        # set up FIPS code fields and a unique household ID variable
        synthpop_df.rename(columns=rename_synpop_h, inplace=True)
        synthpop_df.reset_index(drop=False, inplace=True)
        derive_fips_codes(synthpop_df)
        synthpop_df["hh_id"] = synthpop_df["state_fips"] + synthpop_df["index"].astype(
            int
        ).astype(str)
        synthpop_df = synthpop_df[
            [
                "hh_id",
                "hh_age",
                "hh_income",
                "hh_race",
                "size",
                "serialno",
                "state_fips",
                "puma_fips",
                "county_fips",
                "tract_fips",
                "blkgrp_fips",
            ]
        ]

        synthpop_df.to_parquet(output_path, index=False)

        # read in the raw PUMS values
        pums_p_df = pd.concat(
            [
                pd.read_csv(
                    ZipFile(pums_p_path).open(i),
                    usecols=[
                        "SERIALNO",
                        "SPORDER",
                        "RAC1P",
                        "HISP",
                        "AGEP",
                        "SEX",
                        "RELSHIPP",
                    ],
                )
                for i in ZipFile(pums_p_path).namelist()
                if i.endswith(".csv")
            ],
            ignore_index=True,
        )
        pums_p_df.rename(
            columns={c: c.lower() for c in pums_p_df.columns}, inplace=True
        )
        pums_p_df["serialno"] = pums_p_df["serialno"].astype(str)

        # merge the household population with the person-level file to get the
        # unique persons in the synthetic population
        # NOTE: hh_id + sporder combine to make a unique person ID in the population
        synthpop_persons_df = synthpop_df[["hh_id", "serialno"]].merge(
            pums_p_df, on=["serialno"], how="left"
        )[["hh_id", "serialno", "sporder", "rac1p", "agep", "sex", "relshipp"]]
        synthpop_persons_df.to_parquet(output_path_persons, index=False)
