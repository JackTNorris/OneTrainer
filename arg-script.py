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
# Path to your batch file
bat_file_path = "train.bat"

# Running the batch file
#subprocess.run(bat_file_path, shell=True)


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

# Example usage
json_file = "arguments.json"  # Replace with your JSON file path
#print("python scripts/train.py " + json_to_command_line_args(json_file))
subprocess.run("python scripts/train.py " + json_to_command_line_args(json_file) + " --tensorboard --gradient-checkpointing --backup-before-save --aspect-ratio-bucketing --latent-caching --clear-cache-before-training --train-unet --train-prior --samples-to-tensorboard --non-ema-sampling --backup-before-save", shell=True)