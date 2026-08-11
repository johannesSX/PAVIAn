"""Shared SimpleITK registration used by the SimpleITK preprocessing steps."""

from typing import Optional

import SimpleITK as sitk


def sitk_registration(
        fixed: sitk.Image,
        moving: sitk.Image,
        mode: str = 'versor',
        sampling_seed: int = 42,
) -> Optional[sitk.Transform]:
    """Multi-resolution Mattes mutual-information registration (moving -> fixed).

    Returns the estimated transform, or None if registration raises.
    """
    if mode == 'euler':
        trans = sitk.Euler3DTransform()
    elif mode == 'versor':
        trans = sitk.ScaleSkewVersor3DTransform()
    elif mode == 'affine':
        trans = sitk.AffineTransform(fixed.GetDimension())
    else:
        raise ValueError(f"Unknown registration mode: {mode}")

    initial_transform = sitk.CenteredTransformInitializer(
        fixed, moving, trans,
        sitk.CenteredTransformInitializerFilter.GEOMETRY,
    )

    reg = sitk.ImageRegistrationMethod()
    reg.SetMetricAsMattesMutualInformation(numberOfHistogramBins=50)
    reg.SetMetricSamplingStrategy(reg.RANDOM)
    reg.SetMetricSamplingPercentage(0.1, sampling_seed)
    reg.SetInterpolator(sitk.sitkLinear)
    reg.SetOptimizerAsGradientDescent(
        learningRate=1.0,
        numberOfIterations=1000,
        convergenceMinimumValue=1e-6,
        convergenceWindowSize=10,
        estimateLearningRate=reg.EachIteration,
    )
    reg.SetOptimizerScalesFromPhysicalShift()
    reg.SetShrinkFactorsPerLevel(shrinkFactors=[4, 2, 1])
    reg.SetSmoothingSigmasPerLevel(smoothingSigmas=[2, 1, 0])
    reg.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    reg.SetInitialTransform(initial_transform, inPlace=False)

    try:
        return reg.Execute(
            sitk.Cast(fixed, sitk.sitkFloat32),
            sitk.Cast(moving, sitk.sitkFloat32),
        )
    except RuntimeError as e:
        print(f"Registration failed: {e}")
        return None