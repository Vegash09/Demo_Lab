import json
import yaml

def load_config(file_path):
    if file_path.endswith('.json'):
        with open(file_path, 'r') as f:
            return json.load(f)
    elif file_path.endswith('.yaml') or file_path.endswith('.yml'):
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        raise ValueError("Unsupported config format. Use JSON or YAML.")