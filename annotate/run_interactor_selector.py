import sys
import os
import json
import subprocess
from pathlib import Path

from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import Qt, QFileSystemWatcher
from PyQt5.QtWidgets import QListWidgetItem, QFileDialog

UI_DIR = Path(__file__).parent / 'ui'
CONFIG_FILE = Path.home() / '.bids_annotation_config.json'


class BIDSAnnotationWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(str(UI_DIR / 'gui_selector_window.ui'), self)
        self.setAcceptDrops(True)

        self.bids_root = None
        self.slicer_path = None
        self.script_path = Path(__file__).parent / 'run_interactor.py'

        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.directoryChanged.connect(self.on_directory_changed)

        self.listWidgetSubjectDirs.itemClicked.connect(self.on_subject_clicked)
        self.pushButtonAnnotate.clicked.connect(self.on_annotate_clicked)
        self.pushButtonAIAnnotate.hide()  # AI segmentation is a separate, optional component

        self.lineEditSlicerPath.mousePressEvent = self.on_slicer_path_clicked
        self.listWidgetNiftiFiles.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.listWidgetNiftiFiles.setStyleSheet("QListWidget { background-color: #f0f0f0; }")

        self.load_slicer_path()

    def on_slicer_path_clicked(self, event):
        directory = QFileDialog.getExistingDirectory(
            self, "Select 3D Slicer Directory",
            self.lineEditSlicerPath.text() or str(Path.home()),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if directory:
            self.slicer_path = Path(directory)
            self.lineEditSlicerPath.setText(str(self.slicer_path))
            self.save_slicer_path()

    def load_slicer_path(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    slicer_path = json.load(f).get('slicer_path')
                if slicer_path and Path(slicer_path).exists():
                    self.slicer_path = Path(slicer_path)
                    self.lineEditSlicerPath.setText(str(self.slicer_path))
            except Exception as e:
                print(f"Error loading config: {e}")

    def save_slicer_path(self):
        try:
            config = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
            config['slicer_path'] = str(self.slicer_path)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isdir(path):
                self.bids_root = Path(path)
                self.load_bids_subjects()
            else:
                QtWidgets.QMessageBox.warning(self, "Invalid Input", "Please drop a BIDS directory")

    def load_bids_subjects(self):
        self.listWidgetSubjectDirs.clear()
        self.listWidgetNiftiFiles.clear()
        if not self.bids_root:
            return

        if self.file_watcher.directories():
            self.file_watcher.removePaths(self.file_watcher.directories())

        subject_dirs = sorted(
            d for d in self.bids_root.iterdir() if d.is_dir() and (d / 'anat').is_dir())

        for subject_dir in subject_dirs:
            anat_dir = subject_dir / 'anat'
            item = QListWidgetItem(subject_dir.name)
            if self.is_annotated(anat_dir):
                item.setText(f"✓ {subject_dir.name}")
                item.setForeground(Qt.darkGreen)
            item.setData(Qt.UserRole, str(subject_dir))
            self.listWidgetSubjectDirs.addItem(item)
            self.file_watcher.addPath(str(anat_dir))

        if not subject_dirs:
            QtWidgets.QMessageBox.information(
                self, "No subjects found",
                f"No subject folders containing an 'anat' directory were found under:\n{self.bids_root}")

    def is_annotated(self, anat_dir):
        return len(list(anat_dir.glob('*.json'))) > 0

    def on_directory_changed(self, path):
        anat_dir = Path(path)
        subject_dir = anat_dir.parent
        for i in range(self.listWidgetSubjectDirs.count()):
            item = self.listWidgetSubjectDirs.item(i)
            if Path(item.data(Qt.UserRole)) == subject_dir:
                if self.is_annotated(anat_dir):
                    if not item.text().startswith("✓"):
                        item.setText(f"✓ {subject_dir.name}")
                        item.setForeground(Qt.darkGreen)
                else:
                    if item.text().startswith("✓"):
                        item.setText(subject_dir.name)
                        item.setForeground(Qt.black)
                break

    def on_subject_clicked(self, item):
        self.listWidgetNiftiFiles.clear()
        anat_dir = Path(item.data(Qt.UserRole)) / 'anat'
        if not anat_dir.exists():
            return
        nifti_files = sorted(list(anat_dir.glob('*.nii')) + list(anat_dir.glob('*.nii.gz')))
        for nifti_file in nifti_files:
            file_item = QListWidgetItem(nifti_file.name)
            file_item.setData(Qt.UserRole, str(nifti_file))
            self.listWidgetNiftiFiles.addItem(file_item)

    def launch_slicer_with_files(self, nifti_files, segmentation_file=None):
        slicer_executable = self.slicer_path / 'Slicer'
        if not slicer_executable.exists():
            QtWidgets.QMessageBox.critical(
                self, "Slicer Not Found",
                f"Slicer executable not found at: {slicer_executable}")
            return
        if not self.script_path.exists():
            QtWidgets.QMessageBox.critical(
                self, "Script Not Found",
                f"run_interactor.py not found at: {self.script_path}")
            return

        cmd = [str(slicer_executable), '--python-script', str(self.script_path)]
        cmd += [str(f) for f in nifti_files]
        if segmentation_file:
            cmd += ['--segmentation', str(segmentation_file)]

        try:
            subprocess.Popen(cmd)
            msg = f"3D Slicer has been launched with {len(nifti_files)} file(s).\n\n"
            msg += "The annotation interface will open once the files are loaded."
            QtWidgets.QMessageBox.information(self, "Slicer Launched", msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Launch Failed", f"Failed to launch Slicer:\n\n{e}")

    def on_annotate_clicked(self):
        if not self.slicer_path or not self.slicer_path.exists():
            QtWidgets.QMessageBox.warning(
                self, "Slicer Path Not Set",
                "Please specify the path to the 3D Slicer directory first.")
            self.lineEditSlicerPath.setFocus()
            return

        selected_subject = self.listWidgetSubjectDirs.currentItem()
        if not selected_subject:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a subject directory first")
            return

        nifti_files = [
            Path(self.listWidgetNiftiFiles.item(i).data(Qt.UserRole))
            for i in range(self.listWidgetNiftiFiles.count())
        ]
        if not nifti_files:
            QtWidgets.QMessageBox.warning(
                self, "No Files", "No NIfTI files found in the selected subject's anat directory")
            return

        self.launch_slicer_with_files(nifti_files)


def run_interactor_selector():
    app = QtWidgets.QApplication(sys.argv)
    window = BIDSAnnotationWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    run_interactor_selector()