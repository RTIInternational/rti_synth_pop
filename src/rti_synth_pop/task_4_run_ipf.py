# Description: This script runs the Iterative Proportional Fitting (IPF) algorithm to
# estimate the combined counts from marginal tables.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
import warnings
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
import xarray as xr
from ipfn import ipfn
from pandas import CategoricalDtype
from pytask import Product, mark, task
from tqdm import tqdm

from rti_synth_pop.config import STATE_INFO, SURVEY, YEAR, interim_data_dir, query_dict


# %%
def _create_parametrization(
    state_info: list[str], var_dict: dict[str, str]
) -> dict[str, str | Path]:
    id_to_kwargs = {}

    for st_abbr, st_fips in state_info:
        input_var_paths = {}
        for var in var_dict.keys():
            input_var_paths[var] = (
                interim_data_dir / f"{st_fips}_{SURVEY}_{YEAR}_{var}.parquet"
            )
        id_to_kwargs[st_abbr] = {
            "input_variables": input_var_paths,
            "output_path": interim_data_dir
            / f"{st_fips}_{SURVEY}_{YEAR}_IPF_counts.parquet",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO, query_dict)
_ID_TO_KWARGS
# %%

for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_run_ipf(
        input_variables: dict[str, Path], output_path: Annotated[Path, Product]
    ):
        """Run IPF to estimate combined counts from marginal tables.

        input_variables: dict[str, Path] = A dictionary of all paths to marginal tables.
        output_path: Path = path to output parquet file

        Returns: None
        """
        data_dict = {}
        variable_label_dict = {}
        for var, input_path in input_variables.items():
            df = pd.read_parquet(input_path)
            data_dict[var] = df
            variable_label_dict[var] = df.iloc[:, 1].unique().tolist()

        # create array of dims matching the count of categories for each marginal
        all_dimensions = [len(x) for x in variable_label_dict.values()]
        dimensions = [[x] for x in range(len(all_dimensions))]
        marginals = np.full(all_dimensions, fill_value=1)

        # all the data should be identical and consistent, so we can pull the geoids
        # from just one of the marginal tables.
        geoids = data_dict[var].GEOID.unique()

        # NOTE: FOR TESTING ONLY.
        # TODO: remove ignore warnings later and make sure there isn't something
        # funky going on.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result_list = []
            for geoid in tqdm(geoids):
                aggregates = []
                for data in data_dict.values():
                    # TODO: this could be a duckdb query instead of loading the entire
                    # dataframe above. Might be a better solution for parallelization.
                    data_values = data[data.GEOID == geoid].value.values
                    aggregates.append(data_values)

                IPF = ipfn.ipfn(marginals, aggregates, dimensions, convergence_rate=1)
                IPF.iteration()
                ipf_result = IPF.iteration()
                ipf_result = np.array(ipf_result)
                # this probabalistic round comes from the original code, but it the counts to be off
                # but a few hundred when summed up over even a small test set.
                # TODO: revisit the rounding.
                # ipf_result = np.floor(ipf_result + np.random.random()).astype(int)

                data = xr.DataArray(
                    ipf_result,
                    coords=variable_label_dict,
                    dims=list(variable_label_dict.keys()),
                )
                data.name = "count"
                result_df = data.to_dataframe().reset_index().assign(GEOID=geoid)
                result_list.append(result_df)
        sp_df = pd.concat(result_list).astype(
            {
                "size": CategoricalDtype(ordered=True),
                "age": CategoricalDtype(ordered=True),
                "income": CategoricalDtype(ordered=True),
                "race": CategoricalDtype(),
                "ethnicity": CategoricalDtype(),
            }
        )
        sp_df.to_parquet(output_path)
