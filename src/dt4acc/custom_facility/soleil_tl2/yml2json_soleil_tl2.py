"""SOLEIL TL2: the device database (accelerator_setup.json) from SOLEIL's
tl2_database.yaml, as yml2json_soleil.py for the ring. Run in the folder of
the file. SOLEIL's nomenclature of the line differs: entries are flat, the
BPMs are markers (family BPM), the correctors Corrector elements."""
import json
from typing import Dict, List

import yaml
from bson import ObjectId

# classes considered magnets
MAGNET_CLASSES = {"Quadrupole", "Bend"}
STEERER_CLASSES = {"Corrector"}
BPM_FAMILIES = {"BPM"}

INPUT_YAML = "tl2_database.yaml"
OUTPUT_JSON = "accelerator_setup.json"


def device_entries(db: Dict[str, Dict]) -> List[Dict]:
    output = []
    for uuid, entry in db.items():
        cls = entry.get("Class")
        fam_name = entry.get("FamName")
        name = entry.get("TANGO")
        pc_name = entry.get("TANGO_AE")

        if not name:
            continue

        # --- BPMs ---
        if fam_name in BPM_FAMILIES:
            output.append({
                "_id": {"$oid": str(ObjectId())},
                "uuid": uuid,
                "type": "BPM",
                "FamName": fam_name,
                "name": name,
                "s_pos": entry.get("S_pos", 0.0),
            })
            continue

        if cls in STEERER_CLASSES:
            cls = "Steerer"
        # skip non-magnets (the screens)
        elif cls not in MAGNET_CLASSES:
            continue

        output.append({
            "_id": {"$oid": str(ObjectId())},
            "uuid": uuid,
            "type": cls,
            "FamName": fam_name,
            "name": name,
            "magnetic_strength": 1.0,
            "pc": pc_name,
            "k": 1.0,
        })
    return output


def main():
    with open(INPUT_YAML, "r") as f:
        db = yaml.safe_load(f)

    output = device_entries(db)

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Generated {len(output)} entries in {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
