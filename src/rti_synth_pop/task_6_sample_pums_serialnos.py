# Description: This script samples from the PUMS to fill the households expected by IPF.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
# %load_ext autoreload
# %autoreload 2

from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from pandas.api.types import CategoricalDtype
from pytask import Product, mark, task
from tqdm import tqdm

from rti_synth_pop.config import (
    STATE_INFO,
    SURVEY,
    YEAR,
    age_labels,
    income_labels,
    interim_data_dir,
    raw_data_dir,
    size_labels,
    vars_list,
)
from rti_synth_pop.sample_pums import get_similarity_df, sample_pums_data

parallel = Parallel(n_jobs=100, require="sharedmem", prefer="threads")


# %%
def sample_one_puma(
    puma: int,
    ipf_count_rounded_df_puma: pd.DataFrame,
    pums_h_df: pd.DataFrame,
    scaled_euclidean_df: pd.DataFrame,
):
    """For a specific PUMA, sample from the PUMS to fill the households expected by IPF.

    puma: int = The puma FIPS code.
    ipf_count_rounded_df_puma: pd.Dataframe = The IPF households for that PUMA.
    pums_h_df: pd.Dataframe = The PUMS household data from the state.
    scaled_euclidean_df: pd.DataFrame = The most similar PUMA to the PUMA of interest.

    Returns: A list of dictionaries with serial numbers sampled for that PUMA, and their matching criteria.
    """
    puma_sample_weights = scaled_euclidean_df.loc[puma].rename("sample_weights")
    all_results = []
    for i, row in ipf_count_rounded_df_puma.iterrows():
        matches = sample_pums_data(
            row,
            pums_h_df,
            puma_sample_weights,
        )
        all_results += matches
    return all_results


# %%
def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr] = {
            "ipf_path": interim_data_dir
            / f"{st_fips}_{SURVEY}_{YEAR}_IPF_counts.parquet",
            "pums_h_path": interim_data_dir / f"csv_h{st_fips}_{YEAR}_recoded.parquet",
            "crosswalk_path": interim_data_dir
            / f"{st_fips}_{YEAR}_pums_2_bg_crosswalk.parquet",
            # "raw_pums_path": raw_data_dir / f"csv_h{st_abbr.lower()}_{YEAR}.zip",
            "output_path": interim_data_dir
            / f"{st_fips}_{YEAR}_household_synthpop_serialnos.parquet",
            "census_path": raw_data_dir / f"{st_fips}_{SURVEY}_{YEAR}.parquet",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_sample_pumsh(
        ipf_path: Path,
        pums_h_path: Path,
        crosswalk_path: Path,
        census_path: Path,
        output_path: Annotated[Path, Product],
    ) -> None:
        """Sample from the PUMS in parallel to fill all households expected by IPF.

        ipf_path: Path = The path to the IPF counts from task 4.
        pums_h_path: Path = The path to the cleaned PUMS Household data.
        crosswalk_path: Path = The path to the PUMA/block group crosswalk.
        census_path: Path = The path to the ACS population counts (used as reference)
        output_path: Annotated[Path, Product] = The path to the sampled parquet file.

        Returns: None
        """
        # %%
        ipf_count_df = (
            pd.read_parquet(ipf_path)
            .astype(
                {
                    "size": CategoricalDtype(ordered=True),
                    "age": CategoricalDtype(ordered=True),
                    "income": CategoricalDtype(ordered=True),
                    "race": CategoricalDtype(),
                    "ethnicity": CategoricalDtype(),
                }
            )
            .query("count > 0")
            .assign(
                size=lambda df: df["size"].cat.reorder_categories(size_labels),
                age=lambda df: df["age"].cat.reorder_categories(age_labels),
                income=lambda df: df["income"].cat.reorder_categories(income_labels),
            )
            .reset_index(drop=True)
        )
        pums_h_df = pd.read_parquet(pums_h_path)
        pums_h_df["PUMA_GEOID"] = pums_h_df["PUMA_GEOID"].astype(int)
        # TODO: set index for faster query?
        crosswalk = pd.read_parquet(crosswalk_path).rename(
            columns={"BG_GEOID": "GEOID"}
        )
        crosswalk["PUMA_GEOID"] = crosswalk["PUMA_GEOID"].astype(int)
        # geoids = census_df.index.tolist()
        ipf_count_df = ipf_count_df.merge(crosswalk, on="GEOID", how="left")

        # %%
        scaled_euclidean_df = get_similarity_df(pums_h_df, vars_list)
        # %%

        census_df = pd.read_parquet(census_path)
        total_ref_pop = census_df["B11001_001E"].sum()
        sp_pop = ipf_count_df["count"].sum().round().astype(int)
        prob_rounded_pop = (
            np.floor(ipf_count_df["count"] + np.random.random()).astype(int).sum()
        )
        reg_rounded_pop = ipf_count_df["count"].round().sum().astype(int)
        print(f"ref pop:\t\t{total_ref_pop:,}")
        print(f"ipf pop:\t\t{sp_pop:,}")
        print(f"prob rounded pop:\t{prob_rounded_pop:,}")
        print(f"reg rounded pop:\t{reg_rounded_pop:,}")

        ipf_count_rounded_df = ipf_count_df.copy()
        ipf_count_rounded_df["count"] = (
            (ipf_count_df["count"] + 0.1).round().astype(int)
        )
        ipf_count_rounded_df = ipf_count_rounded_df.loc[
            ipf_count_rounded_df["count"] > 0
        ].reset_index(drop=True)
        # %%
        # TODO: do the income adjustment
        total_puma = len(ipf_count_rounded_df["PUMA_GEOID"].unique())

        # Split by PUMA and run through the sampling function
        sample_output = parallel(
            delayed(sample_one_puma)(
                puma,
                ipf_count_rounded_df_puma,
                pums_h_df,
                scaled_euclidean_df,
            )
            for puma, ipf_count_rounded_df_puma in tqdm(
                ipf_count_rounded_df.groupby("PUMA_GEOID"), total=total_puma
            )
        )
        result_list = []
        for res in sample_output:
            result_list += res

        result_df = pd.DataFrame(result_list)
        result_df.to_parquet(output_path)
