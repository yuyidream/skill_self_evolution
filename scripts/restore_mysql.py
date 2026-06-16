"""Restore MySQL rules_config from disk YAML."""
import os, sys
os.environ["DB_PASSWORD"] = "local_root_123"
sys.path.insert(0, "E:/projects/skill_self_evolution/src")
from skill_self_evolution.config_loader import ConfigVersionManager
from pathlib import Path

disk = Path("E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/rules_config.yaml")
yaml_content = disk.read_text(encoding="utf-8")

mgr = ConfigVersionManager()
mgr.save("nickname-selector", "rules_config", yaml_content)
print("Restored MySQL from disk")

# Verify
from ruamel.yaml import YAML
y = YAML(typ="safe")
cfg = y.load(mgr.load_raw("nickname-selector", "rules_config"))
bc = cfg.get("correctness_criteria", {}).get("bad_categories", [])
rr = cfg.get("rejection_rules", [])
vc = cfg.get("correctness_criteria", {}).get("verification_conditions", [])
print(f"bad_categories: {len(bc)}")
print(f"rejection_rules: {len(rr)}")
print(f"verification_conditions: {len(vc)}")
for v in vc:
    print(f"  {v.get('id')}: {v.get('description','')[:40]}")
mgr.close()
