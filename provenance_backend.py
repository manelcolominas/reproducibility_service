#!/usr/bin/env python3
#
#  Copyright 2002-2026 Barcelona Supercomputing Center (www.bsc.es)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""
RS provenance flag logic Module

This module gets used in case the user triggers the provenance flag. It does the necessary
steps to generate the provenence for COMPSs Runtime

"""
import os
import time

from rocrate.rocrate import ROCrate
from ruamel.yaml import YAML
from utils import (
    get_instrument,
    get_yes_or_no,
    get_name_and_description,
    get_ro_crate_info,
    print_colored,
    TextColor,
)


def update_yaml(crate_path: str):
    """
    Update the 'ro-crate-info.yaml' file with workflow metadata.

    Args:
        crate_path (str): Path to the root directory of the RO-Crate.

    Raises:
        FileNotFoundError: If the specified files or directories do not exist.

    Notes:
        This function updates the 'ro-crate-info.yaml' file with metadata such as sources,
        main file, name, and description retrieved from the RO-Crate.
    """
    crate = ROCrate(crate_path)

    print_colored(" The copied Workflow structure inside the reproducibility_service directory : " ,
        TextColor.YELLOW,
    )

    # To get the instrument ID from the CreateAction entity. application_sources/src/abcde.py
    instrument = get_instrument(crate)

    # Get the sources_main_file from the instrument
    sources_main_file = os.path.join(crate_path, instrument)
    # Get the sources from the directory application_sources in the crate_path
    sources = os.path.join(crate_path, "application_sources")
    # Get the name, description, and authors from the crate_path
    name, description, authors = get_name_and_description(crate_path)
    # Create a YAML instance
    yaml = YAML()
    # Set preserve_quotes to True to maintain the original formatting of the YAML file , to preserve the quotes ("")
    yaml.preserve_quotes = True

    print_colored(
        "Current working directory, the reproducibility_service directory: " + os.getcwd(),
        TextColor.YELLOW,
    )

    print_colored(
        "The reproducibility_service directory current structure : " + os.getcwd(),
        TextColor.YELLOW,
    )

    
    # reproducibility_service_20260723_112328/
    #     ├── log/
    #     │   └── rs_log.txt
    #     ├── Workflow/
    #     │   ├── application_sources/
    #     │   │   ├── src/
    #     │   │   │   └── wordcount.py
    #     │   │   ├── pom.xml
    #     │   │   └── README
    #     │   ├── dataset/
    #     │   │   └── data/
    #     │   │       ├── file0.txt
    #     │   │       ├── file1.txt
    #     │   │       ├── file2.txt
    #     │   │       └── file3.txt
    #     │   ├── App_Profile.json
    #     │   ├── complete_graph.svg
    #     │   ├── compss_submission_command_line.txt
    #     │   ├── ro-crate-info.yaml
    #     │   ├── ro-crate-metadata.json
    #     │   └── ro-crate-preview.html
    #     └── ro-crate-info.yaml
  

    # Doesn't have any sense to find the yaml it will always be called "ro-crate-info.yaml" and it will always be in the reproducibility_service directory, so we can just use the path to the file directly
    # yaml_file_path = find_yaml_with_compss_section(os.getcwd())

    # Get the current working directory and join it with the filename "ro-crate-info.yaml" to get the full path of the YAML file
    yaml_file_path = os.path.join(os.getcwd(), "ro-crate-info.yaml")

    # Read the YAML content from the file
    with open(yaml_file_path, "r", encoding="utf-8") as file:
        data = yaml.load(file)

    # Update the name and description fields
    # Update the fields in the loaded YAML content
    data["COMPSs Workflow Information"]["sources"] = sources
    data["COMPSs Workflow Information"]["sources_main_file"] = sources_main_file
    data["COMPSs Workflow Information"]["name"] = name
    data["COMPSs Workflow Information"]["description"] = description
    data["Authors"] = authors

    # Ask for submitter details
    print_colored(
        "Please provide the submitter's detail for provenance generation: ",
        TextColor.YELLOW,
    )

    # Get the submitter details from the data dictionary, either from the "Submitter" key or the "Agent" key
    submitter_details = data.get("Submitter") or data.get("Agent")
    # While loop to ensure that the user provides a non-empty name for the agent
    while True:
        name = input("Agent's Name [Name]: ").strip()
        if name:
            submitter_details["name"] = name
            break
        print_colored("Agent's Name cannot be empty. Please provide a valid name.", TextColor.RED)
    
    # Remove this keys from the submitter_details dictionary if they exist
    submitter_details.pop("e-mail", None)
    submitter_details.pop("orcid", None)
    submitter_details.pop("organisation_name", None)
    submitter_details.pop("ror", None)
    
    # Assign the 'Agent' field with the submitter details if 'Submitter' entry exists and deletes the 'Submitter' entry
    data.pop("Submitter", None)
    data["Agent"] = submitter_details

    # Write the updated dictionary back to the YAML file
    with open(yaml_file_path, "w", encoding="utf-8") as file:
        yaml.dump(data, file)

    print("Updated the ro-crate-info.yaml file with the workflow information.")

def provenance_info_collector(execution_path: str, service_path: str) -> bool:
    """
    Collect provenance information for the workflow based on user input.

    Returns:
        bool: True if provenance collection is enabled; False otherwise.

    Notes:
        This function prompts the user to confirm if they want to collect provenance information.
        If confirmed, it checks for the existence of 'ro-crate-info.yaml' file and prompts the user
        to ensure it is filled correctly. If not found or verified, it invokes 'get_ro_crate_info'
        to generate the file. It returns True if provenance collection is enabled, False otherwise.
    """
    provenance_flag = get_yes_or_no(
        "Do you want to generate the provenance of your workflow run?"
    )
    # print("Provenance_flag:",provenance_flag)
    if provenance_flag:
        files = os.listdir(os.getcwd())
        already_exists = "ro-crate-info.yaml" in files
        if not already_exists:
            get_ro_crate_info(execution_path, service_path)

    return provenance_flag


def provenance_checker(execution_path: str):
    # for file in os.listdir(os.getcwd()):
    #     if file == "ro-crate-info.yaml":
    #         os.unlink(os.path.join(os.getcwd(), file))
    #         break
    result_path = os.path.join(execution_path, "Result")
    if not os.path.exists(result_path):
        contains_crate = False
    else:
        contains_crate = any(
            name.startswith("COMPSs_RO-Crate_")
            for name in os.listdir(result_path)
            if os.path.isdir(os.path.join(result_path, name))
        )

    if contains_crate:
        print_colored(
            f"RO_CRATE has been generated successfully inside {result_path}",
            TextColor.GREEN,
        )
    else:
        print_colored(
            "Could not generate the RO_CRATE for provenance, please see the above provenance log for more details",
            TextColor.RED,
        )
