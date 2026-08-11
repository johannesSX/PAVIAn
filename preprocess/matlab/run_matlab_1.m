function run_matlab_1(nii_file, spm_path, work_path)
    cd(work_path);
    addpath(spm_path);
    spm('defaults', 'FMRI');
    spm_jobman('initcfg');
    try
        spm_jobman('run', {'./matlab_script_1.m'}, cellstr(nii_file));
    catch
        warning('Skipping %s', char(nii_file));
    end
end