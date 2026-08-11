"""PAVIAn preprocessing pipeline: BIDS conversion, defacing, registration,
skull stripping, normalization, and annotation coordinate translation."""

import argparse
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Dict, List, Optional

import nibabel as nib
import numpy as np
import SimpleITK as sitk
import torchio as tio
import tqdm
from scipy.ndimage import map_coordinates

from lib import sitk_registration

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"
MATLAB_DIR = SCRIPT_DIR / "matlab"

MNI_T1 = str(TEMPLATE_DIR / "mni_icbm152_t1_tal_nlin_sym_09c.nii")
MNI_T2 = str(TEMPLATE_DIR / "mni_icbm152_t2_tal_nlin_sym_09c.nii")
BRAIN_MASK = str(TEMPLATE_DIR / "mni_icbm152_t1_tal_nlin_sym_09c_mask.nii")
FACE_MASK = str(TEMPLATE_DIR / "mni_icbm152_t1_tal_nlin_sym_09c_face_mask.nii")

DEFAULT_SEQUENCES = ['t1', 't1ce', 't2', 'flair', 'swi']
DEFAULT_SEQ_MATCHING = {'t1': ['t1'], 't2': ['t2', 'flair', 'swi']}


# --- Sequence-name matching ---

def match_sequence_name(sequence_paths: List[str], seq_names: List[str]) -> Dict[str, Optional[str]]:
    """Map each file path to the longest sequence name that matches its filename."""
    path_to_seqname = {}
    for path in sequence_paths:
        filename = os.path.basename(path).lower()
        matched_seq = None
        max_match_len = 0
        for seq_name in seq_names:
            pattern = r'(?:^|_|-)' + re.escape(seq_name.lower()) + r'(?:$|_|-|\.)'
            if re.search(pattern, filename) and len(seq_name) > max_match_len:
                matched_seq = seq_name
                max_match_len = len(seq_name)
        path_to_seqname[path] = matched_seq
    return path_to_seqname


def get_sequence_name(path: str, seq_names: List[str]) -> Optional[str]:
    return match_sequence_name([path], seq_names)[path]


def _pick_template(filename: str, seq_matching: Dict[str, List[str]],
                   path_t1: str, path_t2: str) -> Optional[str]:
    name = filename.lower()
    if any(seq.lower() in name for seq in seq_matching['t1']):
        return path_t1
    if any(seq.lower() in name for seq in seq_matching['t2']):
        return path_t2
    return None


# --- Normalization ---

def run_norm_simple(
        src_root: str,
        input_suffix: str = "BIDS_DEFACED_REG_SKULL",
        output_suffix: str = "NORM",
        sequence_names: Optional[List[str]] = None,
) -> None:
    if sequence_names is None:
        sequence_names = DEFAULT_SEQUENCES

    src_root_path = Path(src_root)
    if input_suffix not in str(src_root_path):
        print(f"Warning: input_suffix '{input_suffix}' not found in src_root '{src_root}'")

    output_root = str(src_root_path).replace(input_suffix, f'{input_suffix}_{output_suffix}')
    nifti_files = glob.glob(str(src_root_path / '*' / 'anat' / 'w_*.nii'))
    if not nifti_files:
        print(f"Warning: No registered files (w_*.nii) found under {src_root}")
        return

    print(f"Input:  {src_root}\nOutput: {output_root}\nImages: {len(nifti_files)}")

    # Train histogram-standardization landmarks per sequence type.
    sequence_images = {seq: [] for seq in sequence_names}
    for src_path in nifti_files:
        seq = get_sequence_name(src_path, sequence_names)
        if seq is not None:
            sequence_images[seq].append(src_path)

    landmarks = {}
    for seq in sequence_names:
        if sequence_images[seq]:
            landmarks[seq] = tio.HistogramStandardization.train(sequence_images[seq])
        else:
            landmarks[seq] = None

    processed, skipped = 0, 0
    for src_path in tqdm.tqdm(nifti_files, desc='Normalizing'):
        try:
            seq = get_sequence_name(src_path, sequence_names)
            if seq is None or landmarks[seq] is None:
                skipped += 1
                continue

            img = tio.ScalarImage(src_path)
            img = tio.HistogramStandardization({'image': landmarks[seq]})(tio.Subject(image=img)).image

            mean, std = img.data.mean(), img.data.std()
            if std > 0:
                img.data = (img.data - mean) / std

            out_path = Path(src_path.replace(input_suffix, f'{input_suffix}_{output_suffix}'))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out_path))
            processed += 1
        except Exception as e:
            print(f"Error processing {Path(src_path).name}: {e}")
            skipped += 1

    print(f"Normalization done. Processed: {processed}, skipped: {skipped}")


# --- Skull stripping (SimpleITK) ---

def run_skull_remove_simple(
        src_root: str,
        input_suffix: str = "BIDS_DEFACED_REG",
        output_suffix: str = "SKULL",
        path_to_mni_t1: str = MNI_T1,
        path_to_mni_t2: str = MNI_T2,
        path_to_brain_mask: str = BRAIN_MASK,
        sequence_matching: Optional[Dict[str, List[str]]] = None,
) -> None:
    if sequence_matching is None:
        sequence_matching = DEFAULT_SEQ_MATCHING

    src_root_path = Path(src_root)
    output_root = str(src_root_path).replace(input_suffix, f'{input_suffix}_{output_suffix}')
    nifti_files = glob.glob(str(src_root_path / '*' / 'anat' / 'w_*.nii'))
    if not nifti_files:
        print(f"Warning: No registered files (w_*.nii) found under {src_root}")
        return

    print(f"Input:  {src_root}\nOutput: {output_root}\nImages: {len(nifti_files)}")

    for src_path in tqdm.tqdm(nifti_files, desc='Skull stripping'):
        template_path = _pick_template(Path(src_path).name, sequence_matching,
                                       path_to_mni_t1, path_to_mni_t2)
        if template_path is None:
            print(f"Warning: No template match for {Path(src_path).name}")
            continue

        try:
            fixed_image = sitk.ReadImage(src_path, sitk.sitkFloat32)
            moving_image = sitk.ReadImage(template_path, sitk.sitkFloat32)
            final_transform = sitk_registration(fixed_image, moving_image)
            if final_transform is None:
                print(f"Warning: Registration failed for {Path(src_path).name}")
                continue

            brain_mask = sitk.ReadImage(path_to_brain_mask, sitk.sitkFloat32)
            brain_mask_subject = sitk.Resample(
                brain_mask, fixed_image, final_transform,
                sitk.sitkNearestNeighbor, 0.0, moving_image.GetPixelID(),
            )
            stripped = sitk.Multiply(fixed_image, brain_mask_subject)

            out_path = Path(src_path.replace(input_suffix, f'{input_suffix}_{output_suffix}'))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sitk.WriteImage(stripped, str(out_path))
        except Exception as e:
            print(f"Error processing {Path(src_path).name}: {e}")

    print(f"Skull stripping done. Output: {output_root}")


# --- Registration / segmentation (SPM12 via MATLAB) ---

def _prepare_matlab_path(path: str) -> str:
    return f"'{path}'"


def _copy_to_spm_directory(src_path: str, input_suffix: str, output_suffix: str) -> str:
    trg_path = src_path.replace(input_suffix, f'{input_suffix}_{output_suffix}')
    Path(trg_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, trg_path)
    return trg_path


def _ensure_matlab_scripts(work_dir: str) -> None:
    """Make sure the SPM batch scripts are present in work_dir (MATLAB's start dir)."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    for name in ("run_matlab_1.m", "matlab_script_1.m", "run_matlab_2.m", "matlab_script_2.m"):
        src, dst = MATLAB_DIR / name, work / name
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)


def _run_matlab_batch(matlab_function: str, *args, matlab_bin: str, work_dir: str) -> None:
    matlab_cmd = f'{matlab_function}({", ".join(args)})'
    subprocess.call([matlab_bin, '-sd', work_dir, '-batch', matlab_cmd])


def spm_segmentation_worker_1(src_path, spm_path, work_dir, input_suffix, output_suffix, matlab_bin):
    trg_path = _copy_to_spm_directory(src_path, input_suffix, output_suffix)
    _run_matlab_batch(
        'run_matlab_1',
        _prepare_matlab_path(trg_path.replace('.nii', '.nii,1')),
        _prepare_matlab_path(spm_path),
        _prepare_matlab_path(work_dir),
        matlab_bin=matlab_bin, work_dir=work_dir,
    )


def spm_segmentation_worker_2(trg_path, rep_path, spm_path, work_dir, input_suffix, output_suffix, matlab_bin):
    trg_path_spm = trg_path.replace(input_suffix, f'{input_suffix}_{output_suffix}')
    rep_path_spm = rep_path.replace(input_suffix, f'{input_suffix}_{output_suffix}')
    _run_matlab_batch(
        'run_matlab_2',
        _prepare_matlab_path(trg_path_spm.replace('.nii', '.nii,1')),
        _prepare_matlab_path(rep_path_spm),
        _prepare_matlab_path(spm_path),
        _prepare_matlab_path(work_dir),
        matlab_bin=matlab_bin, work_dir=work_dir,
    )


def _get_reorientation_paths(nii_paths: List[str], output_prefix: str = 'y_') -> List[str]:
    return [str(Path(p).parent / f'{output_prefix}{Path(p).name}') for p in nii_paths]


def run_spm_segmentation_parallel(
        src_root: str,
        spm_path: str,
        work_dir: Optional[str] = None,
        matlab_bin: str = "matlab",
        input_suffix: str = "BIDS_DEFACED",
        output_suffix: str = "SPM",
        output_prefix: str = "y_",
        nifti_pattern: str = "*.nii",
        n_processes: Optional[int] = None,
        exclude_patterns: Optional[List[str]] = None,
) -> None:
    if spm_path is None:
        raise ValueError("REG_SPM requires --spm-path (path to your SPM12 install).")
    if work_dir is None:
        work_dir = str(MATLAB_DIR)
    if n_processes is None:
        n_processes = cpu_count()
    if exclude_patterns is None:
        exclude_patterns = ['_seg.nii', '_dseg.nii', '_probseg.nii']

    _ensure_matlab_scripts(work_dir)

    src_root_path = Path(src_root)
    output_root = str(src_root_path).replace(input_suffix, f'{input_suffix}_{output_suffix}')
    nii_files = glob.glob(f'{src_root}/*/anat/{nifti_pattern}')
    nii_files = [f for f in nii_files if not any(p in f for p in exclude_patterns)]
    if not nii_files:
        print(f"Warning: No NIfTI files found under {src_root}")
        return

    print(f"Input:  {src_root}\nOutput: {output_root}\nFiles: {len(nii_files)}\nSPM: {spm_path}")

    print("Stage 1: SPM segmentation")
    with Pool(processes=n_processes) as pool:
        pool.starmap(spm_segmentation_worker_1,
                     [(p, spm_path, work_dir, input_suffix, output_suffix, matlab_bin) for p in nii_files])

    print("Stage 2: normalise/write")
    rep_paths = _get_reorientation_paths(nii_files, output_prefix)
    with Pool(processes=n_processes) as pool:
        pool.starmap(spm_segmentation_worker_2,
                     [(n, r, spm_path, work_dir, input_suffix, output_suffix, matlab_bin)
                      for n, r in zip(nii_files, rep_paths)])

    print(f"SPM pipeline done. Output: {output_root}")


# --- Registration (SimpleITK) ---

def run_registration_simple(
        src_root: str,
        input_suffix: str = "BIDS_DEFACED",
        output_suffix: str = "REG",
        path_to_mni_t1: str = MNI_T1,
        path_to_mni_t2: str = MNI_T2,
        sequence_matching: Optional[Dict[str, List[str]]] = None,
) -> None:
    if sequence_matching is None:
        sequence_matching = DEFAULT_SEQ_MATCHING

    src_root_path = Path(src_root)
    output_root = str(src_root_path).replace(input_suffix, f'{input_suffix}_{output_suffix}')
    nifti_files = glob.glob(str(src_root_path / '*' / 'anat' / '*.nii'))
    if not nifti_files:
        print(f"Warning: No .nii files found under {src_root}")
        return

    print(f"Input:  {src_root}\nOutput: {output_root}\nImages: {len(nifti_files)}")

    for src_path in tqdm.tqdm(nifti_files, desc='Registering to template'):
        template_path = _pick_template(Path(src_path).name, sequence_matching,
                                       path_to_mni_t1, path_to_mni_t2)
        if template_path is None:
            print(f"Warning: No template match for {Path(src_path).name}")
            continue

        try:
            moving_image = sitk.ReadImage(src_path, sitk.sitkFloat32)
            fixed_image = sitk.ReadImage(template_path, sitk.sitkFloat32)
            final_transform = sitk_registration(fixed_image, moving_image)
            if final_transform is None:
                print(f"Warning: Registration failed for {Path(src_path).name}")
                continue

            registered = sitk.Resample(
                moving_image, fixed_image, final_transform,
                sitk.sitkBSpline4, 0.0, moving_image.GetPixelID(),
            )

            out = Path(src_path.replace(input_suffix, f'{input_suffix}_{output_suffix}'))
            image_path = out.parent / f"w_{out.name}"
            transform_path = out.parent / f"y_t_{out.stem}.tfm"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            sitk.WriteImage(registered, str(image_path))
            sitk.WriteTransform(final_transform, str(transform_path))
        except Exception as e:
            print(f"Error processing {Path(src_path).name}: {e}")

    print(f"Registration done. Output: {output_root}")


# --- Defacing ---

def run_deface_afni(src_root: str, afni_bin: str = "") -> None:
    lst_nii = [f for f in glob.glob(src_root + '/*/anat/*.nii') if not f.endswith('.deface.nii')]
    for src_path in tqdm.tqdm(lst_nii, desc='Defacing (AFNI)'):
        cmd = [f"{afni_bin}@afni_refacer_run", "-input", src_path, "-mode_all",
               "-prefix", src_path, "-anonymize_output", "-overwrite"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error defacing {src_path}:\n{result.stderr}")
            continue

        deface = Path(src_path.replace('.nii', '.deface.nii.gz'))
        with gzip.open(str(deface), 'rb') as f_in, open(str(deface).replace('.nii.gz', '.nii'), 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        for suffix in ('.deface.nii.gz', '.face.nii.gz', '.face_plus.nii.gz',
                       '.reface.nii.gz', '.reface_plus.nii.gz'):
            p = Path(src_path.replace('.nii', suffix))
            if p.exists():
                p.unlink()
        qc_dir = Path(src_path.replace('.nii', '_QC'))
        if qc_dir.is_dir():
            shutil.rmtree(qc_dir)


def run_deface_simple(
        src_root: str,
        input_suffix: str = "BIDS",
        output_suffix: str = "DEFACED",
        path_to_mni_t1: str = MNI_T1,
        path_to_mni_t2: str = MNI_T2,
        path_to_face_mask: str = FACE_MASK,
        sequence_matching: Optional[Dict[str, List[str]]] = None,
) -> None:
    if sequence_matching is None:
        sequence_matching = DEFAULT_SEQ_MATCHING

    src_root_path = Path(src_root)
    output_root = str(src_root_path).replace(input_suffix, f'{input_suffix}_{output_suffix}')
    nifti_files = glob.glob(str(src_root_path / '*' / 'anat' / '*.nii'))
    if not nifti_files:
        print(f"Warning: No .nii files found under {src_root}")
        return

    print(f"Input:  {src_root}\nOutput: {output_root}\nImages: {len(nifti_files)}")

    for src_path in tqdm.tqdm(nifti_files, desc='Defacing (SimpleITK)'):
        template_path = _pick_template(Path(src_path).name, sequence_matching,
                                       path_to_mni_t1, path_to_mni_t2)
        if template_path is None:
            print(f"Warning: No template match for {Path(src_path).name}")
            continue

        try:
            fixed_image = sitk.ReadImage(src_path, sitk.sitkFloat32)
            moving_image = sitk.ReadImage(template_path, sitk.sitkFloat32)
            final_transform = sitk_registration(fixed_image, moving_image)
            if final_transform is None:
                print(f"Warning: Registration failed for {Path(src_path).name}")
                continue

            face_mask = sitk.ReadImage(path_to_face_mask, sitk.sitkFloat32)
            face_mask = sitk.Resample(
                face_mask, moving_image, sitk.Transform(),
                sitk.sitkNearestNeighbor, 0.0, moving_image.GetPixelID(),
            )

            # Keep-everything mask, then zero out the face region (inverse of face mask).
            keep_array = np.ones(sitk.GetArrayFromImage(moving_image).shape, dtype=np.float32)
            keep_array[sitk.GetArrayFromImage(face_mask) == 1.0] = 0.0
            keep_mask = sitk.GetImageFromArray(keep_array)
            keep_mask.SetOrigin(moving_image.GetOrigin())
            keep_mask.SetSpacing(moving_image.GetSpacing())
            keep_mask.SetDirection(moving_image.GetDirection())

            keep_mask_subject = sitk.Resample(
                keep_mask, fixed_image, final_transform,
                sitk.sitkNearestNeighbor, 0.0, fixed_image.GetPixelID(),
            )
            defaced = sitk.Multiply(fixed_image, keep_mask_subject)

            out_path = Path(src_path.replace(input_suffix, f'{input_suffix}_{output_suffix}'))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sitk.WriteImage(defaced, str(out_path))
        except Exception as e:
            print(f"Error processing {Path(src_path).name}: {e}")

    print(f"Defacing done. Output: {output_root}")


# --- Dataset-specific BIDS converters (call directly, or via TO_BIDS + --dataset) ---

def run_brats_to_bids(src_root: str, bids_root: str, max_subjects: Optional[int] = None) -> None:
    contrast_map = {'t1': 'T1w', 't1ce': 'T1ce', 't2': 'T2w', 'flair': 'FLAIR'}
    os.makedirs(bids_root, exist_ok=True)
    subject_dirs = sorted(d for d in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, d)))
    if max_subjects is not None:
        subject_dirs = subject_dirs[:max_subjects]

    for subj_dir in tqdm.tqdm(subject_dirs, desc='BraTS -> BIDS'):
        bids_subj = f"sub-{subj_dir}"
        anat_dir = os.path.join(bids_root, bids_subj, "anat")
        os.makedirs(anat_dir, exist_ok=True)
        for niigz_file in glob.glob(os.path.join(src_root, subj_dir, "*.nii.gz")):
            base = os.path.basename(niigz_file)
            for brats_label, bids_label in contrast_map.items():
                if base.lower().endswith(f"_{brats_label}.nii.gz"):
                    dest = os.path.join(anat_dir, f"{bids_subj}_{bids_label}.nii")
                    with gzip.open(niigz_file, 'rb') as f_in, open(dest, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    break


def run_bratsmet_to_bids(src_root: str, bids_root: str, max_subjects: Optional[int] = None) -> None:
    contrast_map = {'t1n': 'T1w', 't1c': 'T1ce', 't2w': 'T2w', 't2f': 'FLAIR', 'seg': 'dseg'}
    os.makedirs(bids_root, exist_ok=True)
    subject_dirs = sorted(d for d in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, d)))
    if max_subjects is not None:
        subject_dirs = subject_dirs[:max_subjects]

    for subj_dir in tqdm.tqdm(subject_dirs, desc='BraTS-MET -> BIDS'):
        bids_subj = f"sub-{subj_dir}"
        anat_dir = os.path.join(bids_root, bids_subj, "anat")
        os.makedirs(anat_dir, exist_ok=True)
        for nii_file in glob.glob(os.path.join(src_root, subj_dir, "*.nii")):
            base = os.path.basename(nii_file)
            for brats_label, bids_label in contrast_map.items():
                if base.lower().endswith(f"-{brats_label}.nii"):
                    shutil.copy2(nii_file, os.path.join(anat_dir, f"{bids_subj}_{bids_label}.nii"))
                    break

def run_ixi_to_bids(src_root: str, bids_root: str, max_subjects: Optional[int] = None) -> None:
    contrast_map = {"T1": "T1w", "T2": "T2w"}
    os.makedirs(bids_root, exist_ok=True)
    for modality, bids_suffix in contrast_map.items():
        modality_dir = os.path.join(src_root, f"IXI-{modality}")
        if not os.path.isdir(modality_dir):
            print(f"Warning: Directory not found: {modality_dir}")
            continue
        files = sorted(glob.glob(os.path.join(modality_dir, "*.nii*")))
        if max_subjects is not None:
            files = files[:max_subjects]
        for nii_file in tqdm.tqdm(files, desc=f"IXI-{modality} -> BIDS"):
            subj_id = os.path.basename(nii_file).split('-')[0]
            bids_subj = f"sub-{subj_id}"
            anat_dir = os.path.join(bids_root, bids_subj, "anat")
            os.makedirs(anat_dir, exist_ok=True)
            dest = os.path.join(anat_dir, f"{bids_subj}_{bids_suffix}.nii")
            if nii_file.endswith('.nii.gz'):
                with gzip.open(nii_file, 'rb') as f_in, open(dest, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            elif nii_file.endswith('.nii'):
                shutil.copy2(nii_file, dest)


BIDS_CONVERTERS = {
    'brats': run_brats_to_bids,
    'bratsmet': run_bratsmet_to_bids,
    'ixi': run_ixi_to_bids,
}


# --- Annotation coordinate translation ---

def _ras_to_lps(coord: np.ndarray) -> np.ndarray:
    """Slicer stores markups in RAS; ITK/nibabel work in LPS (flip X and Y)."""
    lps = coord.copy()
    lps[0] = -lps[0]
    lps[1] = -lps[1]
    return lps


def run_translate_physical_to_index_coords(src_root: str, mark_radius: Optional[int] = 7) -> None:
    for json_path in tqdm.tqdm(glob.glob(str(Path(src_root) / '*/anat/w_*.json')),
                               desc='Physical -> index coords'):
        with open(json_path) as f:
            json_data = json.load(f)

        src_root_path = Path(src_root)
        file_path = Path(json_data['info']['filepath'])
        anchor = src_root_path.parts[-1]
        if anchor not in file_path.parts:
            raise ValueError(f"'{anchor}' not found in path: {file_path}")
        relative_parts = file_path.parts[file_path.parts.index(anchor) + 1:]
        mri_path = src_root_path.joinpath(*relative_parts)

        sitk_mri = sitk.ReadImage(str(mri_path))
        coord_ras = np.array(json.loads(json_data['info']['markup_coord']))
        coord_lps = _ras_to_lps(coord_ras)
        index_coord = sitk_mri.TransformPhysicalPointToIndex(coord_lps.tolist())

        json_data['info']['markup_coord_index'] = str(list(index_coord))
        json_data['info']['markup_coord_lps'] = str(coord_lps.tolist())

        if mark_radius:
            tio_img = tio.ScalarImage(str(mri_path))
            x, y, z = index_coord
            for dx in range(-mark_radius, mark_radius + 1):
                for dy in range(-mark_radius, mark_radius + 1):
                    for dz in range(-mark_radius, mark_radius + 1):
                        if dx * dx + dy * dy + dz * dz <= mark_radius * mark_radius:
                            nx, ny, nz = x + dx, y + dy, z + dz
                            if (0 <= nx < tio_img.shape[1] and 0 <= ny < tio_img.shape[2]
                                    and 0 <= nz < tio_img.shape[3]):
                                tio_img.data[0, nx, ny, nz] = 100
            tio_img.save(str(mri_path).replace('.nii', '_marked.nii'))

        with open(json_path, 'w') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=4)


def run_translate_reg_coords(json_root: str, src_root: str) -> None:
    json_files = glob.glob(str(Path(json_root) / '*' / 'anat' / '*.json'))
    if not json_files:
        print(f"Warning: No JSON files found under {json_root}")
        return

    processed, skipped = 0, 0
    counts = {'tfm': 0, 'deformation_field': 0}
    src_root_path = Path(src_root)
    anchor = src_root_path.parts[-1]

    for json_path in tqdm.tqdm(json_files, desc='Coords -> template space'):
        try:
            with open(json_path) as f:
                json_data = json.load(f)
            coord_ras = np.array(json.loads(json_data['info']['markup_coord']))

            file_path = Path(json_data['info']['filepath'])
            if anchor not in file_path.parts:
                skipped += 1
                continue
            relative_parts = file_path.parts[file_path.parts.index(anchor) + 1:]
            registered_image_path = src_root_path.joinpath(*relative_parts)
            registered_image_path = registered_image_path.parent / f"w_{registered_image_path.name}"
            if not registered_image_path.exists():
                skipped += 1
                continue

            sitk_registered = sitk.ReadImage(str(registered_image_path), sitk.sitkFloat32)
            transform_path = registered_image_path.parent / f"y_t_{registered_image_path.stem}.tfm"

            if transform_path.exists():
                # Parametric transform (SimpleITK registration route).
                counts['tfm'] += 1
                sitk_transform = sitk.ReadTransform(str(transform_path))
                world_template = sitk_transform.TransformPoint(_ras_to_lps(coord_ras).tolist())
                voxel_indices = np.array(sitk_registered.TransformPhysicalPointToIndex(world_template))
            else:
                # Deformation field (SPM route): iy_<name>.
                deformation_field_path = registered_image_path.parent / f"iy_{registered_image_path.name}"
                if not deformation_field_path.exists():
                    skipped += 1
                    continue
                counts['deformation_field'] += 1

                nib_registered = nib.load(str(registered_image_path))
                nib_deformation = nib.load(str(deformation_field_path))
                deformation_data = np.squeeze(nib_deformation.get_fdata())

                world_lps = _ras_to_lps(coord_ras)
                def_voxel = np.linalg.inv(nib_deformation.affine) @ np.append(world_lps, 1)
                coords = def_voxel[:3].reshape(3, 1)
                world_template = np.array([
                    map_coordinates(deformation_data[..., i], coords, order=1, mode='nearest')[0]
                    for i in range(3)
                ])
                voxel_indices = (np.linalg.inv(nib_registered.affine) @ np.append(world_template, 1))[:3]

            json_data['info']['markup_coord_index'] = str(list(np.asarray(voxel_indices).astype(int)))
            json_data['info']['markup_coord_lps'] = str(list(np.asarray(world_template)))
            with open(json_path, 'w') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            processed += 1
        except Exception as e:
            print(f"Error processing {Path(json_path).name}: {e}")
            skipped += 1

    print(f"Coordinate translation done. Processed: {processed}, skipped: {skipped}")
    print(f"  parametric (.tfm): {counts['tfm']}, deformation field: {counts['deformation_field']}")


# --- Pipeline dispatch ---

def run_processing_pipeline(tasks: List[str], src_root: Optional[str] = None,
                            spm_path: Optional[str] = None, work_dir: Optional[str] = None,
                            matlab_bin: str = "matlab", afni_bin: str = "",
                            templates_dir: Optional[str] = None, json_root: Optional[str] = None,
                            dataset: Optional[str] = None, bids_root: Optional[str] = None,
                            n_processes: Optional[int] = None) -> None:

    tdir = Path(templates_dir) if templates_dir else TEMPLATE_DIR
    mni_t1 = str(tdir / "mni_icbm152_t1_tal_nlin_sym_09c.nii")
    mni_t2 = str(tdir / "mni_icbm152_t2_tal_nlin_sym_09c.nii")
    brain_mask = str(tdir / "mni_icbm152_t1_tal_nlin_sym_09c_mask.nii")
    face_mask = str(tdir / "mni_icbm152_t1_tal_nlin_sym_09c_face_mask.nii")

    def require_src():
        if src_root is None:
            raise ValueError(f"--src_root is required for this task.")
        return src_root

    for task in tasks:
        if task == 'TO_BIDS':
            if dataset is None or bids_root is None:
                raise ValueError("TO_BIDS requires --dataset "
                                 f"({'/'.join(BIDS_CONVERTERS)}) and --bids-root.")
            BIDS_CONVERTERS[dataset](src_root=require_src(), bids_root=bids_root)
        elif task == 'DEFACE_AFNI':
            run_deface_afni(src_root=require_src(), afni_bin=afni_bin)
        elif task == 'DEFACE_SIMPLE':
            run_deface_simple(src_root=require_src(), input_suffix="BIDS", output_suffix="DEFACED",
                              path_to_mni_t1=mni_t1, path_to_mni_t2=mni_t2, path_to_face_mask=face_mask)
        elif task == 'REG_SPM':
            run_spm_segmentation_parallel(src_root=require_src(), spm_path=spm_path, work_dir=work_dir,
                                          matlab_bin=matlab_bin, input_suffix="BIDS", output_suffix="SPM",
                                          n_processes=n_processes)
        elif task == 'REG_SIMPLE':
            run_registration_simple(src_root=require_src(), input_suffix="BIDS_DEFACED", output_suffix="REG",
                                    path_to_mni_t1=mni_t1, path_to_mni_t2=mni_t2)
        elif task == 'SKULL_SIMPLE':
            run_skull_remove_simple(src_root=require_src(), input_suffix="BIDS_DEFACED_REG",
                                    output_suffix="SKULL", path_to_mni_t1=mni_t1, path_to_mni_t2=mni_t2,
                                    path_to_brain_mask=brain_mask)
        elif task == 'NORM_SIMPLE':
            run_norm_simple(src_root=require_src(), input_suffix="BIDS_DEFACED_REG_SKULL", output_suffix="NORM")
        elif task == 'TRANSLATE_TO_INDEX':
            run_translate_physical_to_index_coords(src_root=require_src())
        elif task == 'TRANSLATE_REG_COORDS':
            if json_root is None:
                raise ValueError("TRANSLATE_REG_COORDS requires --json-root and --src_root.")
            run_translate_reg_coords(json_root=json_root, src_root=require_src())
        else:
            raise ValueError(f"Unknown task: {task}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MRI preprocessing tasks in sequence.")
    parser.add_argument("--tasks", nargs="+", required=True, choices=[
        "TO_BIDS", "DEFACE_AFNI", "DEFACE_SIMPLE", "REG_SPM", "REG_SIMPLE",
        "SKULL_SIMPLE", "NORM_SIMPLE", "TRANSLATE_TO_INDEX", "TRANSLATE_REG_COORDS",
    ], help="Tasks to execute, in order.")
    parser.add_argument("--src_root", default=None, help="Source directory tree to process.")
    parser.add_argument("--json-root", default=None, help="Annotation JSON root (TRANSLATE_REG_COORDS).")
    parser.add_argument("--dataset", default=None, choices=list(BIDS_CONVERTERS),
                        help="Dataset converter for TO_BIDS.")
    parser.add_argument("--bids-root", default=None, help="Output BIDS root for TO_BIDS.")
    parser.add_argument("--templates-dir", default=None, help="Directory with MNI templates/masks.")
    parser.add_argument("--spm-path", default=None, help="Path to SPM12 install (REG_SPM).")
    parser.add_argument("--work-dir", default=None, help="MATLAB start dir holding the batch scripts.")
    parser.add_argument("--matlab-bin", default="matlab", help="MATLAB executable.")
    parser.add_argument("--afni-bin", default="", help="Directory holding @afni_refacer_run (DEFACE_AFNI).")
    parser.add_argument("--n-processes", type=int, default=None, help="Parallel workers for REG_SPM.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_processing_pipeline(
        args.tasks,
        src_root=args.src_root,
        spm_path=args.spm_path,
        work_dir=args.work_dir,
        matlab_bin=args.matlab_bin,
        afni_bin=args.afni_bin,
        templates_dir=args.templates_dir,
        json_root=args.json_root,
        dataset=args.dataset,
        bids_root=args.bids_root,
        n_processes=args.n_processes,
    )