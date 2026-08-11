import sys
import json
from pathlib import Path

from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import pyqtSignal

from tab import Tab

UI_DIR = Path(__file__).parent / 'ui'


class SlicerAnnotationWindow(QtWidgets.QDialog):
    data_saved = pyqtSignal(object)

    def __init__(self, data_dict, path_to_def_json):
        super().__init__()
        self.setWindowTitle("Slicer Annotation")
        self.data_dict = data_dict

        with open(path_to_def_json) as f:
            self.def_dict = json.load(f)

        uic.loadUi(str(UI_DIR / 'gui_main_window.ui'), self)

        for i in reversed(range(self.tabWidget.count())):
            widget = self.tabWidget.widget(i)
            self.tabWidget.removeTab(i)
            widget.deleteLater()

        info = self.data_dict['info']
        self.label_filename.setText(str(Path(info['filepath']).name))
        self.label_filepath.setText(str(Path(info['filepath']).parent))
        self.label_markupCoord.setText(str(info['markup_coord']))
        self.label_markupName.setText(info['markup_name'])

        self.construct_from_window()

        self.pushButton_addTab.clicked.connect(self.event_addTab)
        self.pushButton_saveAndExit.clicked.connect(self.event_saveAndExit)

    def construct_from_window(self):
        if len(self.data_dict['lst_data']) == 0:
            self.event_addTab()
        else:
            for lst_data_item in self.data_dict['lst_data']:
                self.tabWidget.addTab(Tab(self.tabWidget, self.def_dict, lst_data_item), '*')
            self.tabWidget.setCurrentIndex(len(self.tabWidget.findChildren(Tab)) - 1)

    def event_addTab(self):
        self.tabWidget.addTab(Tab(self.tabWidget, self.def_dict, []), '*')
        self.tabWidget.setCurrentIndex(len(self.tabWidget.findChildren(Tab)) - 1)

    def event_saveAndExit(self):
        lst_checked = [self.tabWidget.widget(i).check_selected() for i in range(self.tabWidget.count())]
        if all(lst_checked):
            data_dict = {'info': self.data_dict['info'], 'lst_data': []}
            for i in range(self.tabWidget.count()):
                data_dict['lst_data'].append(self.tabWidget.widget(i).get_lst_data_item())
            self.data_saved.emit(data_dict)
            self.close()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    demo = {
        'info': {'filepath': './demo.nii.gz', 'markup_coord': [0.0, 0.0, 0.0], 'markup_name': 'F1'},
        'lst_data': [],
    }
    window = SlicerAnnotationWindow(
        data_dict=demo,
        path_to_def_json=str(Path(__file__).parent / 'sample' / 'sample_struct.json'),
    )
    window.show()
    sys.exit(app.exec())
