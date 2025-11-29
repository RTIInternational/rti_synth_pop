# Description: This file contains the functions to sample PUMS records to fill in a specific block group and variable combo.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software]. https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import euclidean_distances

from rti_synth_pop.config import label_dict


# %%
def query_new_df(q_dict: dict):
    """Builds a query to subset a dataframe by particular options.

    q_dict : dict = Dictionary with current values to filter the dataframe by

    Returns: a query string
    """
    queries = []
    for key, val in q_dict.items():
        if type(val) is not list:
            val = [val]
        queries.append(f"({key}.isin({val}))")
    q = " and ".join(queries)
    return q


def expand_var(label: str, val: str):
    """Expands the options for a particular variable to the three values around it.

    label: str = The variable being expanded.
    val: str = The current variable value.

    Returns: A list of options for the variable.
    """
    label_list = label_dict[label]

    code_idx = label_list.index(val)

    max_idx = len(label_list) - 1
    min_idx = 0

    if code_idx == min_idx:
        code_range = [code_idx, code_idx + 1, code_idx + 2]
    elif code_idx == max_idx:
        code_range = [code_idx - 2, code_idx - 1, code_idx]
    else:
        code_range = [code_idx - 1, code_idx, code_idx + 1]

    expanded_vals = [label_list[x] for x in code_range]
    return expanded_vals


def get_similarity_df(input_df: pd.DataFrame, var_list: dict, scaled=True):
    """Samples 'count' PUMS records to fill in a specific block group and variable combo.

    input_df: pd.DataFrame = A dataframe
    var_list: dict = List of variables to use for the similarity measure.
    scaled: True = Wether or not the similarity vectors should be scaled.

    Returns: A dataframe with the vector distances between each pair of PUMA.
    """
    vars_of_interest = ["PUMA_GEOID"] + var_list

    agg = input_df[vars_of_interest].groupby(vars_of_interest).size()
    for _ in range(len(var_list)):
        agg = agg.unstack()

    agg.columns = agg.columns.map(lambda x: "|".join([str(i) for i in x]))
    agg = agg.fillna(0)

    df = agg.div(agg.sum(1), 0).assign(Total=lambda agg: agg.sum(axis=1))

    euclidean_matrix = euclidean_distances(df)

    euclidean_df = pd.DataFrame(
        euclidean_matrix, index=df.index.values, columns=df.index.values
    )

    if scaled:
        scaled_euclidean_df = (
            euclidean_df.div(euclidean_df.sum(axis=1), axis=0).multiply(-1).add(1)
        )
        return scaled_euclidean_df
    else:
        return euclidean_df


# %%
def sample_pums_data(
    row: pd.Series, pums_h_df: pd.DataFrame, puma_sample_weights: pd.DataFrame
):
    """Samples 'count' PUMS records to fill in a specific block group and variable combo.

    row: pd.Series = A specific row from the IPF results for the state.
    pums_h_df: pd.DataFrame = The PUMS records for the state to sample from.
    puma_sample_weights: pd.DataFrame = The distances between each PUMA and the PUMA
    the IPF row is in.

    Returns: A list of PUMS serial number to block group combinations.
    """

    geoid = row["GEOID"]

    # this is the count of the synthetic persons we need to have in the final data
    num_needed = np.ceil(row["count"]).astype(int)
    if num_needed < 1:
        return None

    # this defines the number of pums records we want before we do the sampling.
    # the sample_size_requirement is a function of the number of records from IPF that
    # we need. We start with a 10/1 ratio of records we need to records
    # in the pums data. Above that, we reduce the ratio to 15/2, 20/3, and 25/4.
    sample_size_requirement = 5
    if num_needed <= 10:
        sample_size_requirement = 1
    elif num_needed <= 15:
        sample_size_requirement = 2
    elif num_needed <= 20:
        sample_size_requirement = 3
    elif num_needed <= 25:
        sample_size_requirement = 4

    # this is the GEOID of the PUMA that the block group is in
    puma_geoid = row["PUMA_GEOID"]

    # create the base query with exactly matching of all variable categories.
    query_dict = {
        k: v for k, v in row.items() if k not in ["count", "GEOID", "PUMA_GEOID"]
    }

    expansion = "None."

    # subset to this puma and variable set to look for exact matches
    puma_samples = pums_h_df.loc[pums_h_df["PUMA_GEOID"] == puma_geoid]
    for key, val in query_dict.items():
        puma_samples = puma_samples.loc[puma_samples[key] == val]
    # see how many records we have to sample from. If it needs the required ratio,
    # (matching_record_count to sample_size_required) we will sample from it.
    matching_record_count = puma_samples.shape[0]

    # ----- Pass #1: Weight all PUMAs by similarity:
    # if geoid_sample_ratio < SAMPLE_RATIO:
    # if matching_record_count < sample_size_requirement:

    # pass 1: expand to state with weights
    if matching_record_count < sample_size_requirement:
        keys = list(query_dict.keys())
        # just subset by the variables (not the puma)
        puma_samples = pums_h_df.loc[pums_h_df[keys[0]] == query_dict[keys[0]]]
        for key, val in query_dict.items():
            if key == keys[0]:
                continue
            puma_samples = puma_samples.loc[puma_samples[key] == val]
        matching_record_count = puma_samples.shape[0]

    # pass 2: expand variables -> add state weights
    # if there are not enough PUMS records to sample, start expanding the variables
    # to see if we can get enough. First within only the target PUMA, then at the
    # state level.
    if matching_record_count < sample_size_requirement:

        # create a copy of the original dictionary so we don't modify it. If we need
        # to return to the original filter we can.
        expanded_query_dict = query_dict.copy()
        # in the spirit of the original code, size was handled separately before age and
        # income. However, due to a bug, that was not the actual implementation. So in
        # this update, I follow the implementation of the code to persist the expansion
        # updates for each of the variables throughout the following attempts to query
        # the pums data.
        # So for each of the variables, the expasion occurs. If there are not enough
        # records, try to broaden to the state with weights. If the loop moves on to the
        # next expansion, the previous expansion is retained. So size goes to 3
        # categories, the age, then income.
        # for variable in ["size"]:
        expanded_query_dict = query_dict.copy()
        expanded_query_dict["PUMA_GEOID"] = puma_geoid

        expanded_variables = []
        for variable in ["size", "age", "income"]:
            expanded_variables.append(variable)
            expansion = ", ".join(expanded_variables) + " expanded."
            expanded_query_dict[variable] = expand_var(
                variable, expanded_query_dict[variable]
            )
            the_query = query_new_df(expanded_query_dict)

            puma_samples = pums_h_df.query(the_query)
            matching_record_count = puma_samples.shape[0]
            if matching_record_count >= sample_size_requirement:
                break

            else:
                # expand to the state
                expansion = expansion + " state weights added."
                puma_samples = pums_h_df.query(
                    " and ".join(the_query.split(" and ")[:-1])
                )
                matching_record_count = puma_samples.shape[0]
                if matching_record_count >= sample_size_requirement:
                    break

    # if after expanding the variables we still do not have enough records to sample
    # from, start eliminating variables to see if we can find enough matches.
    # pass 2: eliminate variables -> add state weights
    if matching_record_count < sample_size_requirement:
        eliminated_variables = []
        for variable in ["ethnicity", "age", "income"]:
            eliminated_variables.append(variable)
            expansion = (
                ", ".join(expanded_variables)
                + " expanded. "
                + ", ".join(eliminated_variables)
                + " eliminated."
            )
            expanded_query_dict.pop(variable)
            the_query = query_new_df(expanded_query_dict)
            puma_samples = pums_h_df.query(the_query)
            matching_record_count = puma_samples.shape[0]
            if matching_record_count >= sample_size_requirement:
                break
            # expand to the state
            else:
                expansion = expansion + " state weights added."
                puma_samples = pums_h_df.query(
                    " and ".join(the_query.split(" and ")[:-1])
                )
                matching_record_count = puma_samples.shape[0]
                if matching_record_count >= sample_size_requirement:
                    break

    # if we've made it this far with no matching, we have an issue that needs to be
    # addressed. record this missing record and come back to investigate the issue.
    if matching_record_count < sample_size_requirement:
        expansion = "NO MATCHES"
        output_records = None
    else:
        # TODO: check this logic. SO what happens is that when we get a set of records
        # to sample, we can do the merge only once to stick the weights on the table for
        # sampling, istead of doing it in the loop. This is not the adaptive weighting
        # that happened in v1. This would not work for the adaptive scaling in v1. So
        # revisit this later to see if we want to do that again.
        # This step only appears to impact when we have to add state weights to expanded
        # or eliminated variables, which looks like < 5% of the resulting synthetic pop.
        if "state weights added" in expansion:
            puma_samples = puma_samples.merge(
                puma_sample_weights,
                how="left",
                left_on="PUMA_GEOID",
                right_index=True,
            )
            weights = "sample_weights"
        else:
            weights = None

        # sample the records for the number that is needed.
        output_records = puma_samples.sample(
            num_needed, replace=True, weights=weights, random_state=42
        )[["SERIALNO"]].assign(BG_GEOID=geoid, expansion=expansion)
    return output_records.to_dict("records")
