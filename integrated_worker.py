"""Private subprocess for the unified editor (no API or GUI)."""
import json
import sys
from engine.advanced_generator import AdvancedConfig, generate_advanced

if __name__ == '__main__':
    source, output, config = sys.argv[1:]
    generate_advanced(source, output_root=output, config=AdvancedConfig.from_dict(json.loads(config)))
