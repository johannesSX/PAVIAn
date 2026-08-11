from pathlib import Path

from PyQt5 import QtWidgets, uic

UI_DIR = Path(__file__).parent / 'ui'


class Tab(QtWidgets.QWidget):
    def __init__(self, tabWidget, def_dict, lst_data_item):
        super().__init__()
        uic.loadUi(str(UI_DIR / 'gui_tab_window.ui'), self)

        self.tabWidget = tabWidget

        self.scrollAreaWidgetContents.setLayout(QtWidgets.QVBoxLayout())
        self.listWidget_entity.addItems(def_dict['lst_entity']['lst_key'])
        if def_dict['lst_entity']['selected']:
            self.set_current_row_by_name(def_dict['lst_entity']['selected'])

        for box_dict in def_dict['lst_box']:
            group_box = QtWidgets.QGroupBox(box_dict['box_title'])
            group_box.setAccessibleName(box_dict['box_title'])
            vbox = QtWidgets.QVBoxLayout()
            for key in box_dict['lst_key']:
                if box_dict['type'] == 'radio':
                    button = QtWidgets.QRadioButton(key)
                elif box_dict['type'] == 'checkbox':
                    button = QtWidgets.QCheckBox(key)
                button.setAccessibleName(key)
                if key in box_dict['selected']:
                    button.setChecked(True)
                vbox.addWidget(button)
            group_box.setLayout(vbox)
            self.scrollAreaWidgetContents.layout().addWidget(group_box)

        self.scrollAreaWidgetContents.layout().addSpacerItem(
            QtWidgets.QSpacerItem(
                20, 40,
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
        )

        self.pushButton_delTab.clicked.connect(self.event_delTab)

        for data_item in lst_data_item:
            if data_item['type'] == 'entity':
                self.set_current_row_by_name(data_item['selected'])
            elif data_item['type'] in ('radio', 'checkbox'):
                for key in data_item['selected']:
                    self.set_button_checked(self.scrollAreaWidgetContents, data_item['box_title'], key)

    def find_group_box(self, parent, group_box_title):
        for gb in parent.findChildren(QtWidgets.QGroupBox):
            if gb.accessibleName() == group_box_title:
                return gb
        return None

    def find_button_in_group(self, group_box, button_key):
        for btn_cls in (QtWidgets.QRadioButton, QtWidgets.QCheckBox):
            for btn in group_box.findChildren(btn_cls):
                if btn.accessibleName() == button_key:
                    return btn
        return None

    def set_button_checked(self, parent, group_box_title, button_key, checked=True):
        gb = self.find_group_box(parent, group_box_title)
        if gb is None:
            print(f"GroupBox '{group_box_title}' not found.")
            return False
        btn = self.find_button_in_group(gb, button_key)
        if btn is None:
            print(f"Button '{button_key}' not found in '{group_box_title}'.")
            return False
        btn.setChecked(checked)
        return True

    def set_current_row_by_name(self, item_name):
        model = self.listWidget_entity.model()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if model.data(index) == item_name:
                self.listWidget_entity.setCurrentIndex(index)
                return True
        return False

    def event_delTab(self):
        if self.tabWidget.count() > 1:
            self.tabWidget.removeTab(self.tabWidget.currentIndex())

    def check_selected(self):
        selected_entity = self.listWidget_entity.currentItem()

        lst_checked = []
        for group_box in self.scrollAreaWidgetContents.findChildren(QtWidgets.QGroupBox):
            lst_radio = group_box.findChildren(QtWidgets.QRadioButton)
            if len(lst_radio) > 0:
                lst_checked.append(any(rb.isChecked() for rb in lst_radio))

        return len(lst_checked) > 0 and all(lst_checked) and selected_entity is not None

    def get_lst_data_item(self):
        lst_data_item = [{
            'type': 'entity',
            'selected': self.listWidget_entity.currentItem().text(),
        }]
        for group_box in self.scrollAreaWidgetContents.findChildren(QtWidgets.QGroupBox):
            lst_radio = group_box.findChildren(QtWidgets.QRadioButton)
            lst_checkbox = group_box.findChildren(QtWidgets.QCheckBox)
            if len(lst_radio) > 0:
                for rb in lst_radio:
                    if rb.isChecked():
                        lst_data_item.append({
                            'box_title': group_box.title(),
                            'type': 'radio',
                            'selected': [rb.text()],
                        })
            if len(lst_checkbox) > 0:
                lst_data_item.append({
                    'box_title': group_box.title(),
                    'type': 'checkbox',
                    'selected': [rb.text() for rb in lst_checkbox if rb.isChecked()],
                })
        return lst_data_item
