# Synthetic professional export fixture

Completely fictitious synthetic.example data, not a collected website audit. data.json contains completed editorial slots for the isolated renderer smoke. It is not a reviewed client report. From the extracted root:

```sh
.venv/bin/python tools/pro_offline.py validate examples/professional-synthetic/data.json
.venv/bin/python tools/pro_offline.py render examples/professional-synthetic/data.json -o output/synthetic.html --pdf output/synthetic.pdf --png output/previews
```

To rebuild the skeleton: use build with report.json, --lang en, --audit-id synthetic-handover and --maya-src "$PWD"; complete only its declared slots before validation/rendering.
