# PAVIAn — Point-based Annotation and Validation for Image Analysis

PAVIAn is a tool for **point-based annotation** of brain MRI in
[3D Slicer](https://www.slicer.org/), with a differential-diagnosis GUI that is
configured from JSON (no code changes). Each annotation is saved as one JSON file
next to the image. A supporting preprocessing pipeline prepares the volumes and
carries the annotation coordinates into the processed space for use as
machine-learning ground truth.

_This repository contains the annotation pipeline used in the author's PhD thesis, reduced to its essentials and refactored for readability with help from Claude Opus 4.8. The underlying methods and results are unchanged._

## Modules

| Module | Description |
|--------|-------------|
| [`annotate/`](annotate) | **Core.** 3D Slicer point-annotation tool with a JSON-configured GUI; one JSON per point, reconstructed on reopen. |
| [`preprocess/`](preprocess) | Supporting MRI pipeline (defacing, registration, skull stripping, normalization) and annotation coordinate translation. |

## Quick start

Annotation (needs 3D Slicer + PyQt5):

```bash
cd annotate
python run_interactor_selector.py
```

Drag-drop a dataset folder, select a subject, click **Annotate**, then place
points in Slicer. Each point opens the differential-diagnosis dialog and is saved
as its own JSON. See [`annotate/README.md`](annotate/README.md) for the full
workflow and how to configure the GUI.

Preprocessing is optional and documented in
[`preprocess/README.md`](preprocess/README.md).

## License

MIT — see [`LICENSE`](LICENSE).