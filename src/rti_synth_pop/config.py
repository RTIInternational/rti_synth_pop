# Description: Configuration file for the synthetic population generation
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software]. https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

import pandas as pd
from pyprojroot import here

# FOR THE USER: Currently you can configure the year and states you would like to run
# the synthetic population here. There are two requirements demonstrated below:
#   1)  a list of tuples, containing the 2 character state abbreciate and 2 digit state
#       FIPS/GEOID
#   2)  a 4 digit year. We have tested this code to run years 2019 - 2021. Assuming no
#       no PUMS/ACS changes, it should work for all years that have the same format
#       of those data.


STATE_INFO = [("WY", "56")]
YEAR = 2019
SURVEY = "acs5"
# ======================================================================================

vars_list = ["size", "age", "income", "race", "ethnicity"]
data_dir = here() / "data"
raw_data_dir = data_dir / "raw"
interim_data_dir = data_dir / "interim"
processed_data_dir = data_dir / "processed"

pums_h_col_dict = {
    "size": "NP",
    "race": "HHLDRRAC1P",
    "income": "HINCP",
    "age": "HHLDRAGEP",
    "ethnicity": "HHLDRHISP",
}

size_labels = ["1", "2", "3", "4", "5", "6", "7+"]
size_map = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5"}


race_labels = ["white", "black", "asian", "other", "twoplusraces"]
race_map = {
    1: "white",
    2: "black",
    6: "asian",
    9: "twoplusraces",
    3: "other",
    4: "other",
    5: "other",
    7: "other",
    8: "other",
}

income_labels = [
    "<10k",
    "10k-15k",
    "15k-25k",
    "25k-35k",
    "35k-50k",
    "50k-100k",
    ">100k",
]


def income_map(column):
    return pd.cut(
        column,
        bins=[-(10**10), 9999, 14999, 24999, 34999, 49999, 99999, 10**10],
        labels=income_labels,
    )


age_labels = ["<25", "25-34", "35-44", "45-54", "55-64", "65-74", ">=75"]


def age_map(column):
    return pd.cut(
        column,
        bins=[-1, 24.5, 34.5, 44.5, 54.5, 64.5, 74.5, 10**10],
        labels=age_labels,
    )


ethnicity_labels = ["hispanic", "not_hispanic"]


def ethnicity_map(column):
    return pd.cut(
        column,
        bins=[-1, 1, 100],
        labels=ethnicity_labels,
        ordered=False,
    )


category_maps = {
    "size": {i: size_labels[i] for i in range(len(size_labels))},
    "race": {i: race_labels[i] for i in range(len(race_labels))},
    "income": {i: income_labels[i] for i in range(len(income_labels))},
    "age": {i: age_labels[i] for i in range(len(age_labels))},
    "ethnicity": {i: ethnicity_labels[i] for i in range(len(ethnicity_labels))},
}

label_dict = {
    "size": size_labels,
    "age": age_labels,
    "income": income_labels,
    "race": race_labels,
    "ethnicity": ethnicity_labels,
}


CENSUS_COLS = [
    # RACE & ETHNICITY
    "B11001_001E",
    "B11001A_001E",
    "B11001B_001E",
    "B11001C_001E",
    "B11001D_001E",
    "B11001E_001E",
    "B11001F_001E",
    "B11001G_001E",
    "B11001H_001E",
    "B11001I_001E",
    # SIZE
    "B11016_001E",
    "B11016_003E",
    "B11016_004E",
    "B11016_005E",
    "B11016_006E",
    "B11016_007E",
    "B11016_008E",
    "B11016_010E",
    "B11016_011E",
    "B11016_012E",
    "B11016_013E",
    "B11016_014E",
    "B11016_015E",
    "B11016_016E",
    # INCOME
    "B19001_001E",
    "B19001_002E",
    "B19001_003E",
    "B19001_004E",
    "B19001_005E",
    "B19001_006E",
    "B19001_007E",
    "B19001_008E",
    "B19001_009E",
    "B19001_010E",
    "B19001_011E",
    "B19001_012E",
    "B19001_013E",
    "B19001_014E",
    "B19001_015E",
    "B19001_016E",
    "B19001_017E",
    # AGE
    "B25007_001E",
    "B25007_003E",
    "B25007_004E",
    "B25007_005E",
    "B25007_006E",
    "B25007_007E",
    "B25007_008E",
    "B25007_009E",
    "B25007_010E",
    "B25007_011E",
    "B25007_013E",
    "B25007_014E",
    "B25007_015E",
    "B25007_016E",
    "B25007_017E",
    "B25007_018E",
    "B25007_019E",
    "B25007_020E",
    "B25007_021E",
]

query_dict = {
    "age": """
SELECT GEOID,
B25007_003E + B25007_013E as "<25",
B25007_004E + B25007_014E as "25-34",
B25007_005E + B25007_015E as "35-44",
B25007_006E + B25007_016E as "45-54",
B25007_007E + B25007_017E + B25007_008E + B25007_018E as "55-64",
B25007_009E + B25007_019E as "65-74",
B25007_010E + B25007_011E + B25007_020E + B25007_021E as ">=75"
""",
    "income": """
SELECT GEOID,
B19001_002E as "<10k",
B19001_003E as "10k-15k",
B19001_004E + B19001_005E as "15k-25k",
B19001_006E + B19001_007E as "25k-35k",
B19001_008E + B19001_009E + B19001_010E as "35k-50k",
B19001_011E + B19001_012E + B19001_013E as "50k-100k",
B19001_014E + B19001_015E + B19001_016E + B19001_017E as ">100k"  
""",
    "size": """
SELECT GEOID,
B11016_010E as "1",
B11016_003E + B11016_011E as "2",
B11016_004E + B11016_012E as "3",
B11016_005E + B11016_013E as "4",
B11016_006E + B11016_014E as "5",
B11016_007E + B11016_015E as "6",
B11016_008E + B11016_016E as "7+"
""",
    "ethnicity": """
SELECT GEOID,
B11001I_001E as hispanic,
B11001_001E - B11001I_001E as not_hispanic 
""",
    "race": """
SELECT GEOID,
B11001A_001E as "white",
B11001B_001E as "black",
B11001D_001E as "asian",
B11001C_001E + B11001E_001E + B11001F_001E as "other",
B11001G_001E as "twoplusraces"
""",
}


# PUMS column dictionaries
pums_h_col_dict = {
    "size": "NP",
    "race": "HHLDRRAC1P",
    "income": "HINCP",
    "age": "HHLDRAGEP",
    "ethnicity": "HHLDRHISP",
}
pums_col_list = list(pums_h_col_dict.values())

rename_synpop_h = {
    "SERIALNO": "serialno",
    "BG_GEOID": "blkgrp_fips",
    "race": "hh_race",
    "income": "hh_income",
    "age": "hh_age",
    "ethnicity": "hh_ethnicity",
    "PUMA_GEOID": "puma_fips",
}
