# Description: This script downloads the PUMS and geographic data for the given state.
# CC BY-NC-SA 4.0
# Kruskamp, N., Kery, C., & Rineer, J. rti_synth_pop [Computer software].
# https://github.com/RTIInternational/rti_synth_pop
# nkruskamp@rti.org , ckery@rti.org, jrin@rti.org

# %%
import urllib
from pathlib import Path
from typing import Annotated

from pytask import Product, mark, task

from rti_synth_pop.config import STATE_INFO, YEAR, raw_data_dir


# %%
def _create_parametrization(state_info: list[str]) -> dict[str, str | Path]:
    base_tiger_url = f"https://www2.census.gov/geo/tiger/TIGER{YEAR}/"
    base_pums_url = (
        f"https://www2.census.gov/programs-surveys/acs/data/pums/{YEAR}/5-Year/"
    )

    id_to_kwargs = {}

    id_to_kwargs["state_geo"] = {
        "input_url": base_tiger_url + f"STATE/tl_{YEAR}_us_state.zip",
        "output_path": raw_data_dir / f"tl_{YEAR}_us_state.zip",
    }

    for st_abbr, st_fips in state_info:
        id_to_kwargs[st_abbr + "_pums-h"] = {
            "input_url": base_pums_url + f"csv_h{st_abbr.lower()}.zip",
            "output_path": raw_data_dir / f"csv_h{st_abbr.lower()}_{YEAR}.zip",
        }

        id_to_kwargs[st_abbr + "_pums-p"] = {
            "input_url": base_pums_url + f"csv_p{st_abbr.lower()}.zip",
            "output_path": raw_data_dir / f"csv_p{st_abbr.lower()}_{YEAR}.zip",
        }

        id_to_kwargs[st_abbr + "_bg_geo"] = {
            "input_url": base_tiger_url + f"BG/tl_{YEAR}_{st_fips}_bg.zip",
            "output_path": raw_data_dir / f"tl_{YEAR}_{st_fips}_bg.zip",
        }

        id_to_kwargs[st_abbr + "_puma_geo"] = {
            "input_url": base_tiger_url + f"PUMA/tl_{YEAR}_{st_fips}_puma10.zip",
            "output_path": raw_data_dir / f"tl_{YEAR}_{st_fips}_puma10.zip",
        }

    return id_to_kwargs


_ID_TO_KWARGS = _create_parametrization(STATE_INFO)
_ID_TO_KWARGS
# %%
for id_, kwargs in _ID_TO_KWARGS.items():

    @mark.persist
    @task(id=id_, kwargs=kwargs)
    def task_download_pums_data(
        input_url: str,
        output_path: Annotated[Path, Product],
    ) -> None:
        """Download the PUMS data files for the given state

        input_url: str = URL to query to get PUMS zip
        output_path: Path = path to output zip file locally

        Returns: None
        """
        urllib.request.urlretrieve(input_url, output_path)


@mark.persist
@task
def task_get_pums_data_dict(
    url: str = (
        "https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/"
        f"PUMS_Data_Dictionary_{YEAR - 4}-{YEAR}.csv"
    ),
    output_path: Annotated[Path, Product] = raw_data_dir
    / f"PUMS_Data_Dictionary_{YEAR - 4}-{YEAR}.csv",
):
    """Download the PUMS data dictionary file for the given state

    input_url: str = URL to query to get data dictionary CSV
    output_path: Path = path to output CSV file locally

    Returns: None
    """
    urllib.request.urlretrieve(url, output_path)
