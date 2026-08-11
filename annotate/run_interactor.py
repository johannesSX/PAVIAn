import sys
import ast
import glob
import json
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import slicer
import qt
import vtk

from gui import SlicerAnnotationWindow

PATH_TO_DEF_STRUCT = str(pathlib.Path(__file__).parent / 'sample' / 'sample_struct.json')


class MarkupAnnoInteractor:
    def __init__(self):
        self.gui_window = None
        self.onStorageNewDataDict = None
        self.markup_point_active = {'active': False}

        slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)
        slicer.mrmlScene.AddObserver(slicer.mrmlScene.NodeAddedEvent, self.onStorageNodeAdded)
        slicer.mrmlScene.AddObserver(slicer.vtkMRMLScene.NodeRemovedEvent, self.onNodeRemoved)

    def check_if_id_and_coord_exist(self, markup_created, markup_coord):
        nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsNode")
        nodes.UnRegister(None)
        for i in range(nodes.GetNumberOfItems()):
            node = nodes.GetItemAsObject(i)
            data_dict = json.loads(node.GetAttribute('data_dict'))
            if (data_dict['info']['markup_created'] == markup_created
                    or data_dict['info']['markup_coord'] == markup_coord):
                return False
        return True

    def read_json_data_dict(self, nii_path):
        nii_path = pathlib.Path(nii_path)
        json_path = str(nii_path).replace(''.join(nii_path.suffixes), '*.json')
        lst_data_dict = []
        for json_path in glob.glob(json_path):
            if pathlib.Path(json_path).is_file():
                with open(json_path) as f:
                    data_dict = json.load(f)
                if self.check_if_id_and_coord_exist(data_dict['info']['markup_created'],
                                                    data_dict['info']['markup_coord']):
                    lst_data_dict.append(data_dict)
        return lst_data_dict

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onStorageNodeAdded(self, caller, event, callData):
        node = callData
        if node.IsA('vtkMRMLStorageNode') and node.GetFileName() is not None:
            for data_dict in self.read_json_data_dict(node.GetFileName()):
                coord = ast.literal_eval(data_dict['info']['markup_coord'])
                markupNode = slicer.mrmlScene.AddNewNodeByClass(
                    'vtkMRMLMarkupsFiducialNode', data_dict['info']['markup_name'])
                self.onStorageNewDataDict = data_dict
                markupNode.AddControlPoint(coord[0], coord[1], coord[2])
                self.onStorageNewDataDict = None

    def add_observer_to_node(self, node):
        node.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionDefinedEvent, self.onPointSet)
        node.AddObserver(slicer.vtkMRMLMarkupsNode.PointPositionUndefinedEvent, self.onPointRemoved)
        node.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onPointModified)
        node.AddObserver(slicer.vtkMRMLMarkupsNode.PointEndInteractionEvent, self.onMarkupPointDeactivated)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onNodeAdded(self, caller, event, callData):
        node = callData
        if node.IsA('vtkMRMLMarkupsFiducialNode'):
            self.add_observer_to_node(node)

    def onMarkupPointDeactivated(self, caller, event):
        # Ctrl + releasing a point re-opens its annotation dialog.
        modifiers = qt.QApplication.keyboardModifiers()
        if modifiers & qt.Qt.ControlModifier:
            data_dict = json.loads(caller.GetAttribute('data_dict'))
            self.gui_window = SlicerAnnotationWindow(data_dict=data_dict, path_to_def_json=PATH_TO_DEF_STRUCT)
            self.gui_window.data_saved.connect(self.onDataSaved)
            self.gui_window.exec_()

    def onPointSet(self, caller, event):
        if self.onStorageNewDataDict is None:
            volumeNode = slicer.app.layoutManager().sliceWidget('Red').mrmlSliceCompositeNode().GetBackgroundVolumeID()
            volumeNode = slicer.mrmlScene.GetNodeByID(volumeNode)
            storageNode = volumeNode.GetStorageNode()
            if storageNode is not None:
                numberOfPoints = caller.GetNumberOfFiducials()
                markup_coord = [0.0, 0.0, 0.0]
                caller.GetNthFiducialPosition(numberOfPoints - 1, markup_coord)
                now = datetime.now()
                data_dict = {
                    'info': {
                        'filepath': storageNode.GetFullNameFromFileName(),
                        'markup_coord': str(markup_coord),
                        'markup_name': caller.GetNthControlPointLabel(numberOfPoints - 1),
                        'markup_created': f"{now.year}{now.month:02d}{now.day:02d}"
                                          f"{now.hour:02d}{now.minute:02d}{now.second:02d}",
                    },
                    'lst_data': [],
                }
                caller.SetAttribute("data_dict", json.dumps(data_dict))
                self.gui_window = SlicerAnnotationWindow(data_dict=data_dict, path_to_def_json=PATH_TO_DEF_STRUCT)
                self.gui_window.data_saved.connect(self.onDataSaved)
                self.gui_window.exec_()
        else:
            caller.SetAttribute("data_dict", json.dumps(self.onStorageNewDataDict))
            numberOfPoints = caller.GetNumberOfFiducials()
            caller.SetNthControlPointLabel(numberOfPoints - 1, self.onStorageNewDataDict['info']['markup_name'])

    def onDataSaved(self, data_dict):
        nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsNode")
        nodes.UnRegister(None)
        for i in range(nodes.GetNumberOfItems()):
            node = nodes.GetItemAsObject(i)
            _data_dict = json.loads(node.GetAttribute('data_dict'))
            if _data_dict['info']['markup_created'] == data_dict['info']['markup_created']:
                node.SetAttribute('data_dict', json.dumps(data_dict))
                out_path = data_dict['info']['filepath'].replace(
                    ''.join(pathlib.Path(data_dict['info']['filepath']).suffixes),
                    '_{}.json'.format(data_dict['info']['markup_created']))
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(data_dict, f, ensure_ascii=False, indent=4)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def onNodeRemoved(self, caller, event, callData):
        node = callData
        if node.IsA('vtkMRMLMarkupsFiducialNode'):
            data_str = node.GetAttribute('data_dict')
            if data_str is not None:
                try:
                    data_dict = json.loads(data_str)
                    filepath = data_dict['info']['filepath']
                    markup_created = data_dict['info']['markup_created']
                    json_path = pathlib.Path(filepath).parent / f"{pathlib.Path(filepath).stem}_{markup_created}.json"
                    if json_path.exists():
                        json_path.unlink()
                        print(f"Deleted annotation file (node removed): {json_path}")
                except Exception as e:
                    print(f"Error deleting JSON file on node removal: {e}")

    @vtk.calldata_type(vtk.VTK_INT)
    def onPointRemoved(self, caller, event, callData=None):
        # When the last control point is removed, delete the annotation file.
        if caller.GetNumberOfControlPoints() == 0:
            data_str = caller.GetAttribute('data_dict')
            if data_str is not None:
                try:
                    data_dict = json.loads(data_str)
                    filepath = data_dict['info']['filepath']
                    markup_created = data_dict['info']['markup_created']
                    json_path = pathlib.Path(filepath).parent / f"{pathlib.Path(filepath).stem}_{markup_created}.json"
                    if json_path.exists():
                        json_path.unlink()
                        print(f"Deleted annotation file (last point removed): {json_path}")
                except Exception as e:
                    print(f"Error deleting JSON file: {e}")

    def onPointModified(self, caller, event):
        if self.onStorageNewDataDict is None:
            data_str = caller.GetAttribute('data_dict')
            if data_str is None:
                return
            data_dict = json.loads(data_str)
            dp = caller.GetDisplayNode()
            i = dp.GetActiveControlPoint() if dp else -1
            data_dict['info']['markup_name'] = caller.GetNthControlPointLabel(caller.GetNumberOfFiducials() - 1)
            if i >= 0:
                pos = [0, 0, 0]
                caller.GetNthControlPointPosition(i, pos)
                data_dict['info']['markup_coord'] = str(pos)
                out_path = data_dict['info']['filepath'].replace(
                    ''.join(pathlib.Path(data_dict['info']['filepath']).suffixes),
                    '_{}.json'.format(data_dict['info']['markup_created']))
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(data_dict, f, ensure_ascii=False, indent=4)
            caller.SetAttribute('data_dict', json.dumps(data_dict))


def load_nifti_files_from_args():
    volume_files = []
    segmentation_file = None
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--segmentation':
            i += 1
            if i < len(sys.argv):
                segmentation_file = sys.argv[i]
        elif arg.endswith('.nii') or arg.endswith('.nii.gz'):
            if 'dseg' in pathlib.Path(arg).name.lower():
                segmentation_file = arg
            else:
                volume_files.append(arg)
        i += 1

    total_files = len(volume_files) + (1 if segmentation_file else 0)
    if total_files == 0:
        print("WARNING: No NIfTI files provided as arguments")
        return

    for nifti_path in volume_files:
        nifti_path = pathlib.Path(nifti_path)
        if not nifti_path.exists():
            print(f"Volume not found: {nifti_path}")
            continue
        try:
            if slicer.util.loadVolume(str(nifti_path)):
                print(f"Loaded volume: {nifti_path.name}")
            else:
                print(f"Failed to load volume: {nifti_path.name}")
        except Exception as e:
            print(f"Error loading volume {nifti_path.name}: {e}")

    if segmentation_file:
        seg_path = pathlib.Path(segmentation_file)
        if not seg_path.exists():
            print(f"Segmentation not found: {seg_path}")
        else:
            try:
                labelmap_node = slicer.util.loadLabelVolume(str(seg_path))
                if labelmap_node:
                    print(f"Loaded segmentation: {seg_path.name}")
                    try:
                        segmentation_node = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode')
                        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                            labelmap_node, segmentation_node)
                        slicer.mrmlScene.RemoveNode(labelmap_node)
                    except Exception as e:
                        print(f"Warning: could not convert to segmentation node: {e}")
                else:
                    print(f"Failed to load segmentation: {seg_path.name}")
            except Exception as e:
                print(f"Error loading segmentation {seg_path.name}: {e}")


def initialize():
    interactor = MarkupAnnoInteractor()
    load_nifti_files_from_args()
    return interactor


interactor = initialize()
