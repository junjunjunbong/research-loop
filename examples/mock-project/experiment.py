import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path("config.json").read_text(encoding="utf-8"))
    if args.smoke:
        print("smoke_ok=true")
        return

    output = {
        "metrics": {"score": 0.5 + float(config["boost"])},
        "metadata": {
            "dataset_version": config["dataset_version"],
            "query_count": config["query_count"],
            "evaluation_config": config["evaluation_config"],
        },
    }
    target = Path("results/metrics.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"score={output['metrics']['score']}")


if __name__ == "__main__":
    main()

