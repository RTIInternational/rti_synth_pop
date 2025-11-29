# Description: This script creates the marginal tables for the synthetic population
# generation
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
from pathlib import Path
from typing import Annotated

import duckdb
from pyprojroot import here
from pytask import Product, mark, task

from rti_synth_pop.config import (
    STATE_INFO,
    SURVEY,
    YEAR,
    interim_data_dir,
    query_dict,
    raw_data_dir,
)


# %%
def _create_parametrization(
    state_info: list[str], query_dict: dict[str, str]
) -> dict[str, str | Path]:
    id_to_kwargs = {}
    for st_abbr, st_fips in state_info:
        for var, query in query_dict.items():
            id_to_kwargs[st_abbr + "_" + var] = {
                "input_path": raw_data_dir / f"{st_fips}_{SURVEY}_{YEAR}.parquet",
                "query": query,
                "output_path": interim_data_dir
                / f"{st_fips}_{SURVEY}_{YEAR}_{var}.parquet",
            }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO, query_dict)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    @task(id=id_, kwargs=kwargs)
    def task_make_marginal_tables(
        input_path: Path,
        query: str,
        output_path: Annotated[Path, Product],
    ) -> None:
        """Download the PUMS data dictionary file for the given state

        input_url: str = URL to query to get data dictionary CSV
        query: str =
        output_path: Path = path to output CSV file locally

        Returns: None
        """
        the_query = query + f" FROM '{input_path}'"
        df = duckdb.execute(the_query).df().melt(id_vars="GEOID")
        df.to_parquet(output_path)
