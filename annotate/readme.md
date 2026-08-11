# PAVIAn — Annotation

Interactive **point annotation** of brain MRI in [3D Slicer](https://www.slicer.org/),
with a differential-diagnosis GUI that is configured from a JSON file (no code
changes). Each annotation is stored as one JSON file next to the image, so
provenance is transparent and the results feed straight into the
[`preprocess`](../preprocess) module's `TRANSLATE_*` tasks.

## Demo
 
A short screen recording of the annotation workflow:

<video src="https://github.com/johannesSX/PAVIAn/assets/12345678/abcd-....mp4" controls muted></video>

## Components

| File | Runs in | Role |
|------|---------|------|
| `run_interactor_selector.py` | host Python (PyQt5) | BIDS browser / launcher. Drag-drop a BIDS root, pick a subject, launch Slicer. |
| `run_interactor.py` | 3D Slicer | Core interactor: captures fiducial points, opens the dialog, reads/writes per-point JSON, reconstructs points on reopen. |
| `gui.py` | 3D Slicer | `SlicerAnnotationWindow` — the tabbed annotation dialog. |
| `tab.py` | 3D Slicer | `Tab` — one annotation record, built dynamically from the structure definition. |
| `ui/*.ui` | — | Qt Designer layouts. |
| `sample/sample_struct.json` | — | GUI definition: entity list + radio/checkbox boxes. Edit this to reconfigure the options. |
| `sample/sample_data.json` | — | Example of one saved annotation record. |

## How it works

```
BIDS root ──▶ run_interactor_selector.py  (host PyQt5)
                   │  launches Slicer with the subject's NIfTI files + run_interactor.py
                   ▼
             run_interactor.py  (Slicer Python)
                   │  place a fiducial point ──▶ SlicerAnnotationWindow (gui.py + tab.py)
                   ▼
             <image>_<timestamp>.json   (one file per point, next to the image)
```

- Placing a point opens the dialog; **Save & Exit** writes the JSON.
- Moving a point rewrites its JSON; deleting a point or node deletes it.
- Reopening a dataset reconstructs all points from the JSON files.
- **Ctrl + release** on an existing point re-opens its editor.

## Requirements

- **3D Slicer** (5.x) — provides the `slicer`, `qt`, and `vtk` modules used by
  `run_interactor.py`, `gui.py`, and `tab.py`. Not pip-installable.
- **Python 3.8+** with **PyQt5** for the launcher (`run_interactor_selector.py`).

## Usage

```bash
python run_interactor_selector.py
```

1. Click the Slicer-path field and select your 3D Slicer directory (the one
   containing the `Slicer` executable). It is remembered in
   `~/.bids_annotation_config.json`.
2. Drag-drop a BIDS root onto the window. Subjects with an existing annotation
   show a green ✓.
3. Select a subject and click **Annotate**.
4. In Slicer, place fiducial points and fill in the dialog. Save writes one JSON
   per point beside the image.

## Configuring the GUI

The entity list and the radio/checkbox groups are defined entirely in
`sample/sample_struct.json` — add or change entries there to adapt the tool to a
different ontology or diagnosis scheme; no source edits required.

## Output format

Each point produces `<image>_<timestamp>.json` containing an `info` block
(filepath, world coordinate, markup name, creation timestamp) and `lst_data`, a
list of records (selected entity plus the chosen radio/checkbox values). See
`sample/sample_data.json` for the `lst_data` shape.

## Note on AI segmentation

Unlike the demonstration video, this release does **not** include the
`AI Annotate` button — AI segmentation is not part of the published tool. PAVIAn
will be reimplemented as a web application, where both annotation and AI
evaluation run in the browser.
