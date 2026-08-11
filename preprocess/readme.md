# PAVIAn — Preprocessing

Turns raw brain-MRI datasets into model-ready volumes and carries expert point
annotations into the processed coordinate space. It is a **task-based pipeline**:
you name the tasks to run and a source directory, and each task reads one
directory tree and writes a new one.

> Part of [PAVIAn](../README.md). The [`annotate`](../annotate) module produces
> the annotation JSON files consumed by the `TRANSLATE_*` tasks.

## Atlases required

The SimpleITK steps (`DEFACE_SIMPLE`, `REG_SIMPLE`, `SKULL_SIMPLE`) register each
subject to an MNI template and warp a mask into subject space. These atlas files
are **not part of the repository** — download the **ICBM 152 Nonlinear Symmetric
2009c** atlas (NIfTI version) and place four uncompressed `.nii` files in
[`templates/`](templates): `mni_icbm152_t1_tal_nlin_sym_09c.nii` and
`mni_icbm152_t2_tal_nlin_sym_09c.nii` (T1/T2 templates),
`mni_icbm152_t1_tal_nlin_sym_09c_mask.nii` (brain mask, for skull stripping), and
`mni_icbm152_t1_tal_nlin_sym_09c_face_mask.nii` (face mask, for defacing). All
four ship in the 2009c symmetric package.
 
Download from https://www.bic.mni.mcgill.ca/ServicesAtlases/ICBM152NLin2009 or
https://nist.mni.mcgill.ca/icbm-152-nonlinear-atlases-2009/. Use `--templates-dir`
to keep them elsewhere. `REG_SPM`, `DEFACE_AFNI`, `NORM_SIMPLE`, and `TRANSLATE_*`
do **not** need these files.


## Pipeline and naming convention

Every task replaces its input suffix with `input_suffix_output_suffix` in the
directory path, so the folder name records the processing history:

```
BIDS → BIDS_DEFACED → BIDS_DEFACED_REG → BIDS_DEFACED_REG_SKULL → BIDS_DEFACED_REG_SKULL_NORM
```

Registered/normalized images get a `w_` prefix; SPM deformation fields get `y_`.
Because the suffix is taken from the path, **`--src_root` must point at the tree
whose name carries the current suffix**, and each step points at the previous
step's output tree (see the example below).

## Tasks

| Task | Reads → writes | Required arguments | External tool |
|------|----------------|--------------------|---------------|
| `TO_BIDS` | dataset → `BIDS/` | `--src_root`, `--dataset`, `--bids-root` | — |
| `DEFACE_AFNI` | in-place | `--src_root` (`--afni-bin` if not on PATH) | AFNI |
| `DEFACE_SIMPLE` | `BIDS` → `BIDS_DEFACED` | `--src_root` + atlases | — |
| `REG_SPM` | `BIDS` → `BIDS_SPM` | `--src_root`, `--spm-path` | MATLAB + SPM12 |
| `REG_SIMPLE` | `BIDS_DEFACED` → `…_REG` | `--src_root` + atlases | — |
| `SKULL_SIMPLE` | `…_REG` → `…_SKULL` | `--src_root` + atlases | — |
| `NORM_SIMPLE` | `…_SKULL` → `…_NORM` | `--src_root` | — |
| `TRANSLATE_TO_INDEX` | updates annotation JSON | `--src_root` | — |
| `TRANSLATE_REG_COORDS` | updates annotation JSON | `--src_root`, `--json-root` | — |

Two interchangeable registration routes exist: the **SimpleITK route**
(`DEFACE_SIMPLE` / `REG_SIMPLE` / `SKULL_SIMPLE`, atlas-based, no license) and the
**SPM route** (`REG_SPM`, needs MATLAB). `lib.py` holds the shared SimpleITK
registration (multi-resolution Mattes mutual information; versor / euler / affine).

## Requirements

Python: `pip install -r requirements.txt` (SimpleITK, torch, torchio, nibabel,
numpy, scipy, tqdm).

External, per task only:
- **MATLAB + SPM12** — `REG_SPM`. Pass `--spm-path /path/to/spm12`. SPM's tissue
  probability map is resolved automatically from that install.
- **AFNI** — `DEFACE_AFNI`. Pass `--afni-bin` if `@afni_refacer_run` is not on PATH.
- **ICBM152 atlases** — the SimpleITK steps (see above).

## Usage

Run one task per invocation, pointing `--src_root` at the current-stage tree.
Pure-Python route:

```bash
# atlases must already be in templates/
python run_preprocessing.py --tasks DEFACE_SIMPLE  --src_root /data/BIDS/MyDataset/
python run_preprocessing.py --tasks REG_SIMPLE     --src_root /data/BIDS_DEFACED/MyDataset/
python run_preprocessing.py --tasks SKULL_SIMPLE   --src_root /data/BIDS_DEFACED_REG/MyDataset/
python run_preprocessing.py --tasks NORM_SIMPLE    --src_root /data/BIDS_DEFACED_REG_SKULL/MyDataset/
```

SPM registration/segmentation (alternative to the SimpleITK reg/skull steps):

```bash
python run_preprocessing.py --tasks REG_SPM \
    --src_root /data/BIDS/MyDataset/ --spm-path /opt/spm12
```

Convert a public dataset into BIDS layout first:

```bash
python run_preprocessing.py --tasks TO_BIDS \
    --dataset brats --src_root /data/BraTS/ --bids-root /data/BIDS/BraTS/
# --dataset: brats | bratsmet | ixi
```

Carry annotations into processed space (after annotating):

```bash
python run_preprocessing.py --tasks TRANSLATE_TO_INDEX --src_root /data/BIDS_.../MyDataset/
python run_preprocessing.py --tasks TRANSLATE_REG_COORDS \
    --json-root /data/BIDS_ANNO/MyDataset/ --src_root /data/BIDS_DEFACED_REG/MyDataset/
```

Run `python run_preprocessing.py --help` for the full argument list.