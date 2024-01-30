"""
Jack's thought process:

1. I see the list of folders i want to generate loras out of
2. Using this, I calculate the number of epochs necessary (based on 8ks teps, batch size 8, e.t.c)
2a. Also adjust the concepts model as needed
3. With this caculation, I load in arguments.json into a python object, and adjust the necessary spots (num epochs, trained model output file, e.t.c)
4. I turn around and load this json file into the directory that contains data I'm training
5. I feed this into a python script that trains the model
"""

import subprocess
import json
from modules.util.params.ConceptParams import ConceptParams
import os
import argparse
from pathlib import Path


template_argument_file = "arguments.json"
template_concepts_file = "default-concepts.json"
batch_size = 8
max_steps = 8000


def read_json_to_object(file_path) -> dict:
    try:
        with open(file_path, 'r') as file:
            # Load JSON data from file
            data = json.load(file)
            return data
    except Exception as e:
        return f"Error reading JSON file: {e}"

def dict_to_command_line_args(dictionary):
    cmd_args = []
    for key, value in dictionary.items():
        if isinstance(value, bool):
            if value:
                cmd_args.append(f"--{key}")
        else:
            cmd_args.append(f"--{key}={value}")

    return ' '.join(cmd_args)

def json_to_command_line_args(json_file_path):
    try:
        # Load the JSON file
        with open(json_file_path, 'r') as file:
            data = json.load(file)

        # Generate command line arguments
        cmd_args = []
        for key, value in data.items():
            # Check if the value is a boolean, if it's True, add only key
            if isinstance(value, bool):
                if value:
                    cmd_args.append(f"--{key}")
            else:
                cmd_args.append(f"--{key}=\"{value}\"")

        return ' '.join(cmd_args)

    except Exception as e:
        return f"Error: {e}"


def get_png_filenames(directory):
    png_files = []
    for file in os.listdir(directory):
        if file.endswith(".png"):
            png_files.append(file)
    return png_files


def replace_vowels_with_8(input_string):
    vowels = 'aeiouAEIOU'
    for vowel in vowels:
        input_string = input_string.replace(vowel, '8')
    return input_string


def create_concepts_file(train_data_path, concepts_dir):
    name = os.path.basename(train_data_path).split(' - ')[-1:][0]

    # Reading and parsing the JSON data into a Python object
    with open(template_concepts_file, 'r') as file:
        python_object = json.load(file)

    python_object[0]['seed'] = ConceptParams.default_values().seed
    python_object[0]['path'] = train_data_path
    python_object[0]['name'] = replace_vowels_with_8(name)
    Path(concepts_dir).mkdir(parents=True, exist_ok=True)
    with open(concepts_dir + '/concepts.json', 'w') as json_file:
        json.dump(python_object, json_file, indent=4)


def parse_console_args(parser):
    parser.add_argument('--input_directory', type=str, help='Absolute path containing the folders you want to create models for', required=True)
    parser.add_argument('--model_output_destination', type=str, help='Absolute path of folder you want models in', default='./brennen-models', required=False)

    return parser.parse_args()

def main(input_directory, model_destination_folder):
    folder_names = os.listdir(input_directory)
    for folder in folder_names:
        name = replace_vowels_with_8(folder.split(' - ')[-1:][0])
        num_pics = max(len(get_png_filenames(input_directory + '/' + folder)), 1)
        print("num_pics", num_pics)
        num_epochs = int(max(max_steps / (num_pics / batch_size), 1))
        #fix this dude
        create_concepts_file(input_directory + '/' + folder, model_destination_folder + '/' + name)
        train_model(model_destination_folder + '/' + name, model_destination_folder + '/' + name + '/' + name + '.safetensors', model_destination_folder + '/' + name + '/concepts.json', num_epochs)


def train_model(home_dir, model_output_destination, concepts_loc, num_epochs):
    train_commands = read_json_to_object(template_argument_file)
    """
    1. reconfigure epochs
    2. set concepts folder
    3. set model output folder
    """
    train_commands['workspace-dir'] = home_dir + '/workspace/run'
    train_commands['cache-dir'] = home_dir + '/workspace-cache/run'
    train_commands['concept-file-name'] = concepts_loc
    train_commands['epochs'] = num_epochs
    train_commands['batch-size'] = batch_size
    train_commands['output-model-destination'] = model_output_destination
    subprocess.run("python scripts/train.py " + dict_to_command_line_args(train_commands) + " --tensorboard --gradient-checkpointing --backup-before-save --aspect-ratio-bucketing --latent-caching --clear-cache-before-training --train-unet --train-prior --samples-to-tensorboard --non-ema-sampling --backup-before-save", shell=True)
    print('Completed training for ' + model_output_destination)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                        prog='auto-brennen',
                        description='expedite brennen\'s workflow via python',
                        epilog='\'Nuff said')

    args = parse_console_args(parser)
    main(args.input_directory, args.model_output_destination)