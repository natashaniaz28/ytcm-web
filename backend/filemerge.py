import json

# import glob
# files = glob.glob("*.json")


files = ["Comments0.json", "Comments.json"]

merged = {}

for file in files:
    print("Handling file", file)
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
        merged.update(data)

with open("merged.json", "w", encoding="utf-8") as output:
    json.dump(merged, output, ensure_ascii=False, indent=2)
