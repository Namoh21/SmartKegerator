#include "optionselectdialog.h"
#include "ui_optionselectdialog.h"
#include "app.h"
#include <QCloseEvent>
#include <QScrollBar>

OptionSelectDialog* OptionSelectDialog::Instance = NULL;

OptionSelectDialog::OptionSelectDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::OptionSelectDialog)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    padding = 5;

    scrollContents = new QWidget(ui->scrollPane);

    layout = new QVBoxLayout(ui->scrollPane);
    layout->setAlignment(Qt::AlignTop);
    layout->setMargin(0);
    layout->setSpacing(padding);
    scrollContents->setLayout(layout);

    selectedIndex = -1;
    selectedIndexes = NULL;
}

void OptionSelectDialog::getSelection(int selected)
{
    multiSelection = false;
    selectedIndex = selected;
    ui->pushButton_Enter->setEnabled(selected > -1);
    updateButtons();
    showAndExec();
}


void OptionSelectDialog::getSelections(vector<bool> *selected)
{
    multiSelection = true;
    ui->pushButton_Enter->setEnabled(true);
    selectedIndexes = selected;
    updateButtons();
    showAndExec();
}

void OptionSelectDialog::init(string title, vector<string> choices)
{
    setWindowTitle(QString(title.c_str()));
    ui->label->setText(QString(title.c_str()));

    cancelled = false;
    options = choices;

    for (unsigned int i=options.size(); i<buttons.size(); i++)
    {
        QPushButton* button = buttons[i];
        button->setVisible(false);
    }

    for (unsigned int i=buttons.size();i<options.size(); i++)
    {
        QPushButton* button = new QPushButton(scrollContents);
        button->setMinimumHeight(50);
        button->setMaximumHeight(50);
        button->setMinimumWidth(ui->scrollPane->width()-5);
        button->setFocusPolicy(Qt::NoFocus);
        button->setCheckable(true);
        button->setFlat(true);
        button->setFont(QFont("Arial", 12));
        layout->addWidget(button);
        buttons.push_back(button);
        connect(button, SIGNAL(clicked()), this, SLOT(itemClicked()));
    }

    ui->verticalScrollBar->setValue(0);
    //updateButtons();
}

void OptionSelectDialog::updateButtons()
{
    int count = 0;
    int h = -padding;
    for (unsigned int i=0;i<options.size(); i++)
    {
        QPushButton* button = buttons[i];
        button->setVisible(true);
        bool selected = getIsSelected(i);
        button->setChecked(selected);
        button->setText(QString(options[i].c_str()));
        h += button->height() + padding;
        if (selected) count++;
    }

    scrollContents->setFixedHeight(h);

    ui->verticalScrollBar->setPageStep(ui->scrollPane->height());
    ui->verticalScrollBar->setRange(0, h - ui->scrollPane->height());

    if (multiSelection)
    {
        ui->selectAllButton->setVisible(count < options.size());
        ui->selectNoneButton->setVisible(count > 0);
    }
    else
    {
        ui->selectAllButton->setVisible(false);
        ui->selectNoneButton->setVisible(false);
    }
}

void OptionSelectDialog::on_verticalScrollBar_valueChanged(int value)
{
    scrollContents->move(0, -value);
}

bool OptionSelectDialog::getIsSelected(int index)
{
    if (multiSelection)
        return selectedIndexes->at(index);
    else
        return index == selectedIndex;
}

bool OptionSelectDialog::TryGetChoice(int &val, string title, vector<string> choices, int selectedIndex)
{
    val = GetChoice(title, choices, selectedIndex);
    return OptionSelectDialog::Instance->cancelled == false;
}

int OptionSelectDialog::GetChoice(string title, vector<string> choices, int selected)
{
    if (OptionSelectDialog::Instance == NULL)
        OptionSelectDialog::Instance = new OptionSelectDialog();

    OptionSelectDialog::Instance->init(title, choices);
    OptionSelectDialog::Instance->getSelection(selected);

    return OptionSelectDialog::Instance->selectedIndex;
}

bool OptionSelectDialog::TryGetChoices(vector<bool> *selected, string title, vector<string> choices)
{
    if (OptionSelectDialog::Instance == NULL)
        OptionSelectDialog::Instance = new OptionSelectDialog();

    OptionSelectDialog::Instance->init(title, choices);
    OptionSelectDialog::Instance->getSelections(selected);

    return OptionSelectDialog::Instance->cancelled == false;
}

void OptionSelectDialog::showAndExec()
{
    if (App::Fullscreen)
        OptionSelectDialog::Instance->showFullScreen();
    else
    {
        OptionSelectDialog::Instance->move(App::WindowX, App::WindowY);
        OptionSelectDialog::Instance->show();
    }

    OptionSelectDialog::Instance->exec();
}


void OptionSelectDialog::itemClicked()
{
    QPushButton* button = (QPushButton*)sender();
    int index = std::find(buttons.begin(), buttons.end(), button) - buttons.begin();

    if (multiSelection)
    {
        selectedIndexes->at(index) = selectedIndexes->at(index) == false;
        updateButtons();
    }
    else
    {
        if (selectedIndex != index)
        {
            if (selectedIndex > -1)
                buttons[selectedIndex]->setChecked(false);
            if (index > -1)
                buttons[index]->setChecked(true);
        }
        selectedIndex = index;
        OptionSelectDialog::Instance->ui->pushButton_Enter->setEnabled(true);
    }
}

void OptionSelectDialog::on_pushButton_Enter_clicked()
{
    hide();
}

void OptionSelectDialog::on_pushButton_Cancel_clicked()
{
    cancelled = true;
    hide();
}

void OptionSelectDialog::on_selectNoneButton_clicked()
{
    for (int i=0; i<selectedIndexes->size(); i++)
        selectedIndexes->at(i) = false;
    updateButtons();
}

void OptionSelectDialog::on_selectAllButton_clicked()
{
    for (int i=0; i<selectedIndexes->size(); i++)
        selectedIndexes->at(i) = true;
    updateButtons();
}



void OptionSelectDialog::closeEvent(QCloseEvent *ev)
{
    cancelled = true;
}


OptionSelectDialog::~OptionSelectDialog()
{
    delete ui;
}
